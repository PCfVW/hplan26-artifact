"""
Orchestration middleware for cross-server MCP plan execution.

This middleware intercepts MCP tool calls and provides automatic orchestration
when tools return execution plans requiring client-side coordination.

Dynamic Data Chaining:
- Supports output_extractors to extract key data from each step's response
- Maintains an execution context that accumulates outputs across steps
- Substitutes ${context.var_name} placeholders with real extracted data
"""

from typing import Awaitable, Callable, Dict, List, Any, Optional, Protocol, runtime_checkable, Union
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone

from .execution_plan import (
    ExecutionPlan,
    ExecutionPlanResponse,
    ExecutionStep,
    ExecutionStatus,
    OrchestrationMetadata,
    StepResult,
)
from ..utils.progress_bar import render_progress_bar, render_completion_message

logger = logging.getLogger(__name__)


def extract_json_path(data: Any, path: str) -> Any:
    """
    Extract a value from nested data using a simple JSON path syntax.

    Supports:
    - Dot notation: "data.search.hits"
    - Array indexing: "hits[0]"
    - Wildcard arrays: "rows[*].name" returns list of all names

    Args:
        data: The data structure to extract from
        path: The JSON path string

    Returns:
        The extracted value, or None if path doesn't exist
    """
    if not path or data is None:
        return None

    # Split path by dots, handling array notation
    parts = re.split(r'\.(?![^\[]*\])', path)
    current = data

    for part in parts:
        if current is None:
            return None

        # Check for array indexing: field[0] or field[*]
        array_match = re.match(r'^([^\[]*)\[([0-9]+|\*)\]$', part)

        if array_match:
            field_name = array_match.group(1)
            index_str = array_match.group(2)

            # Get the field first if there's a name
            if field_name:
                if isinstance(current, dict):
                    current = current.get(field_name)
                else:
                    return None

            if current is None or not isinstance(current, list):
                return None

            if index_str == '*':
                # Wildcard: return all elements (or extract from each if more path)
                return current  # Return the whole list for now
            else:
                idx = int(index_str)
                if idx < len(current):
                    current = current[idx]
                else:
                    return None
        else:
            # Regular field access
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None

    return current


def substitute_context_variables(
    value: str,
    context: Dict[str, Any]
) -> str:
    """
    Substitute ${context.var_name} placeholders with actual values from context.

    Args:
        value: The string potentially containing placeholders
        context: The execution context with extracted values

    Returns:
        The string with placeholders replaced by actual values
    """
    if not isinstance(value, str):
        return value

    # Match ${context.var_name} or ${var_name} patterns
    pattern = r'\$\{(?:context\.)?([^}]+)\}'

    def replacer(match):
        var_name = match.group(1)
        if var_name in context:
            val = context[var_name]
            return str(val) if val is not None else match.group(0)
        return match.group(0)  # Keep original if not found

    return re.sub(pattern, replacer, value)


@runtime_checkable
class MCPClientProtocol(Protocol):
    """Protocol for MCP client interface."""
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        ...


class OrchestrationMiddleware:
    """
    Middleware that intercepts MCP tool calls and provides automatic
    cross-server plan execution orchestration.

    Example::

        middleware = OrchestrationMiddleware({
            "mcp-python-ingestion": planning_client,
            "robot-server": robot_client
        })
        result = await middleware.call_tool(
            server="mcp-python-ingestion",
            tool="python_execute_plan",
            arguments={...}
        )

    """

    def __init__(
        self,
        mcp_clients: Dict[str, MCPClientProtocol],
        auto_orchestrate: bool = True,
        timeout_per_step: float = 30.0,
        enable_progress_bar: bool = True,
    ):
        """
        Initialize the orchestration middleware.

        Args:
            mcp_clients: Dictionary mapping server names to MCP client sessions.
            auto_orchestrate: If True, automatically orchestrate execution plans.
            timeout_per_step: Timeout in seconds for each step execution.
            enable_progress_bar: If True, display progress bar during execution.
        """
        self.clients = mcp_clients
        self.auto_orchestrate = auto_orchestrate
        self.timeout_per_step = timeout_per_step
        self.enable_progress_bar = enable_progress_bar
        self.execution_history: List[Dict[str, Any]] = []
        self._step_results: Dict[str, List[StepResult]] = {}

    async def call_tool(
        self,
        server: str,
        tool: str,
        arguments: Dict[str, Any],
        on_step_progress: Optional[Callable[[int, int, str, str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[float]], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Intercept tool call and handle orchestration if needed.

        Args:
            server: Name of the MCP server to call.
            tool: Name of the tool to invoke.
            arguments: Arguments to pass to the tool.
            on_step_progress: Optional async callback for step progress.
                Called with (step_index, total_steps, action_name, server, status,
                             arguments, result, duration_ms)
                where status is "start" or "complete".
                arguments/result/duration_ms are None for "start" status.

        Returns:
            Tool result, or orchestrated execution results if plan detected.

        Raises:
            KeyError: If server is not registered.
            TimeoutError: If step execution times out.
        """
        if server not in self.clients:
            raise KeyError(f"Server '{server}' not registered. Available: {list(self.clients.keys())}")
        
        client = self.clients[server]
        logger.debug(f"Calling tool '{tool}' on server '{server}'")
        
        # Call the tool
        result = await client.call_tool(tool, arguments)
        
        # Convert to dict if needed
        if hasattr(result, 'model_dump'):
            result_dict = result.model_dump()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {"result": result}
        
        # Check if result is an execution plan
        if self.auto_orchestrate and self._is_execution_plan(result_dict):
            logger.info("Execution plan detected, starting orchestration")
            return await self._orchestrate_plan(result_dict, on_step_progress)

        return result_dict

    def _is_execution_plan(self, result: Dict[str, Any]) -> bool:
        """
        Check if result is an execution plan requiring orchestration.

        Args:
            result: Tool result dictionary.

        Returns:
            True if result requires client orchestration.
        """
        return result.get("requires_client_orchestration", False) is True

    async def _orchestrate_plan(
        self,
        plan_data: Dict[str, Any],
        on_step_progress: Optional[Callable[[int, int, str, str, str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Orchestrate execution of a plan across multiple servers.

        Args:
            plan_data: Raw execution plan response data.
            on_step_progress: Optional callback for step progress events.

        Returns:
            Orchestration results with all step outcomes.
        """
        try:
            plan_response = ExecutionPlanResponse.model_validate(plan_data)
        except Exception as e:
            logger.error(f"Failed to parse execution plan: {e}")
            return {
                "success": False,
                "error": f"Invalid execution plan format: {e}",
                "original_response": plan_data,
            }

        execution_id = plan_response.metadata.execution_id
        plan = plan_response.plan

        # Validate required servers are available
        missing_servers = set(plan_response.servers_required) - set(self.clients.keys())
        if missing_servers:
            return {
                "success": False,
                "error": f"Missing required servers: {missing_servers}",
                "available_servers": list(self.clients.keys()),
            }

        # Execute steps sequentially with progress bar
        # Dynamic Data Chaining: maintain execution context for variable substitution
        step_results: List[StepResult] = []
        step_outputs: Dict[int, Any] = {}  # Map step number to raw output
        execution_context: Dict[str, Any] = {}  # Accumulated extracted values
        total_steps = len(plan.steps)
        start_time = time.time()

        for idx, step in enumerate(plan.steps):
            # Get action name for display
            action_name = step.action[0] if step.action else step.tool

            # Display progress bar if enabled
            if self.enable_progress_bar:
                elapsed = time.time() - start_time
                progress_text = render_progress_bar(
                    current=idx + 1,
                    total=total_steps,
                    elapsed_seconds=elapsed,
                    action_name=action_name
                )
                print(f"\r{progress_text}", end='', flush=True)

            # Notify callback that step is starting
            if on_step_progress:
                try:
                    await on_step_progress(
                        idx, total_steps, action_name, step.server, "start",
                        step.arguments, None, None  # No result yet
                    )
                except Exception as e:
                    logger.warning(f"Step progress callback error: {e}")

            result = await self._execute_step(step, step_outputs, execution_context)
            step_results.append(result)

            # Calculate duration from StepResult
            duration_ms = None
            if result.started_at and result.completed_at:
                duration_ms = (result.completed_at - result.started_at).total_seconds() * 1000

            # Notify callback that step is complete
            if on_step_progress:
                try:
                    status = "success" if result.status == ExecutionStatus.SUCCESS else "failed"
                    await on_step_progress(
                        idx, total_steps, action_name, step.server, status,
                        step.arguments, result.result, duration_ms
                    )
                except Exception as e:
                    logger.warning(f"Step progress callback error: {e}")

            if result.status == ExecutionStatus.SUCCESS:
                step_outputs[step.step] = result.result

                # Extract values using output_extractors and add to context
                # The result may have a 'data' wrapper from the MCP response
                extraction_data = result.result
                if isinstance(result.result, dict) and 'data' in result.result:
                    extraction_data = result.result['data']

                if step.output_extractors and extraction_data:
                    for var_name, json_path in step.output_extractors.items():
                        extracted = extract_json_path(extraction_data, json_path)
                        if extracted is not None:
                            execution_context[var_name] = extracted
                            logger.debug(f"Extracted {var_name}={extracted} from step {step.step}")
            else:
                # Stop on failure
                logger.error(f"Step {step.step} failed: {result.error}")
                break

        # Print newline after progress bar
        if self.enable_progress_bar:
            print()

        # Store in history
        self._step_results[execution_id] = step_results
        execution_record = {
            "execution_id": execution_id,
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "total_steps": plan.total_steps,
            "steps_completed": sum(1 for r in step_results if r.status == ExecutionStatus.SUCCESS),
            "steps_failed": sum(1 for r in step_results if r.status == ExecutionStatus.FAILED),
            "step_results": [r.model_dump() for r in step_results],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.execution_history.append(execution_record)

        # Determine overall success
        all_succeeded = all(r.status == ExecutionStatus.SUCCESS for r in step_results)

        # Display completion message if progress bar is enabled
        if self.enable_progress_bar:
            total_time = time.time() - start_time
            completion_msg = render_completion_message(
                total_steps=total_steps,
                elapsed_seconds=total_time,
                success=all_succeeded
            )
            print(completion_msg)

        return {
            "success": all_succeeded,
            "execution_id": execution_id,
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "total_steps": plan.total_steps,
            "steps_completed": execution_record["steps_completed"],
            "steps_failed": execution_record["steps_failed"],
            "step_results": execution_record["step_results"],
            "final_result": step_outputs.get(plan.total_steps) if all_succeeded else None,
        }

    async def _execute_step(
        self,
        step: ExecutionStep,
        previous_results: Dict[int, Any],
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> StepResult:
        """
        Execute a single step in the plan with dynamic data chaining.

        Args:
            step: The step to execute.
            previous_results: Results from previous steps (for dependency injection).
            execution_context: Accumulated context with extracted values from previous steps.

        Returns:
            StepResult with execution outcome.
        """
        started_at = datetime.now(timezone.utc)
        context = execution_context or {}

        # Check server availability
        if step.server not in self.clients:
            return StepResult(
                step=step.step,
                status=ExecutionStatus.FAILED,
                error=f"Server '{step.server}' not available",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        # Build arguments with context variable substitution
        arguments = {}
        for key, value in step.arguments.items():
            # Substitute ${context.var_name} or ${var_name} with actual values
            if isinstance(value, str):
                substituted = substitute_context_variables(value, context)
                arguments[key] = substituted
                if substituted != value:
                    logger.debug(f"Substituted {key}: '{value}' -> '{substituted}'")
            else:
                arguments[key] = value

        # Inject dependencies into arguments (legacy support)
        for dep_step in step.dependencies:
            if dep_step in previous_results:
                arguments[f"step_{dep_step}_result"] = previous_results[dep_step]

        try:
            client = self.clients[step.server]
            logger.info(f"Executing step {step.step}: {step.tool} on {step.server}")
            logger.debug(f"  Arguments: {arguments}")

            # Execute with timeout
            result = await asyncio.wait_for(
                client.call_tool(step.tool, arguments),
                timeout=self.timeout_per_step,
            )

            completed_at = datetime.now(timezone.utc)
            duration_ms = (completed_at - started_at).total_seconds() * 1000

            # Convert result to dict if needed
            # MCP CallToolResult has content[0].text with JSON data
            if hasattr(result, 'model_dump'):
                raw_result = result.model_dump()
                # Extract the actual data from MCP response structure
                result_dict = raw_result
                if 'content' in raw_result and raw_result['content']:
                    first_content = raw_result['content'][0]
                    if isinstance(first_content, dict) and 'text' in first_content:
                        try:
                            # Parse the JSON text to get actual API response
                            parsed_data = json.loads(first_content['text'])
                            result_dict = parsed_data
                            logger.debug(f"Parsed API response with keys: {list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'N/A'}")
                        except (json.JSONDecodeError, TypeError):
                            # Keep raw result if parsing fails
                            pass
            elif isinstance(result, dict):
                result_dict = result
            else:
                result_dict = {"result": result}

            return StepResult(
                step=step.step,
                status=ExecutionStatus.SUCCESS,
                result=result_dict,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            completed_at = datetime.now(timezone.utc)
            return StepResult(
                step=step.step,
                status=ExecutionStatus.FAILED,
                error=f"Step timed out after {self.timeout_per_step}s",
                started_at=started_at,
                completed_at=completed_at,
            )
        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            logger.exception(f"Step {step.step} failed with exception")
            return StepResult(
                step=step.step,
                status=ExecutionStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=completed_at,
            )

    def get_registered_servers(self) -> List[str]:
        """Return list of registered server names."""
        return list(self.clients.keys())

    def get_execution_history(self) -> List[Dict[str, Any]]:
        """Return the execution history."""
        return list(self.execution_history)

    def clear_history(self) -> None:
        """Clear execution history."""
        self.execution_history.clear()
        self._step_results.clear()

