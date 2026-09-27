"""Unit tests for OrchestrationMiddleware.

Ported from mcp-python-ingestion v0.29.2 (tests/orchestration/test_middleware.py).
Change: import path mcp_python_ingestion.orchestration -> hplan_orchestrator.orchestration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from hplan_orchestrator.orchestration.middleware import OrchestrationMiddleware
from hplan_orchestrator.orchestration.execution_plan import (
    ExecutionStep,
    ExecutionPlan,
    ExecutionPlanResponse,
    OrchestrationMetadata,
    ExecutionStatus,
)


@pytest.fixture
def mock_clients():
    """Create mock MCP clients."""
    planning_client = AsyncMock()
    robot_client = AsyncMock()
    return {
        "mcp-python-ingestion": planning_client,
        "robot-server": robot_client,
    }


@pytest.fixture
def middleware(mock_clients):
    """Create middleware with mock clients."""
    return OrchestrationMiddleware(mock_clients)


class TestOrchestrationMiddlewareInit:
    """Tests for middleware initialization."""

    def test_initialization(self, mock_clients):
        """Test basic initialization."""
        middleware = OrchestrationMiddleware(mock_clients)
        assert len(middleware.clients) == 2
        assert middleware.auto_orchestrate is True
        assert middleware.timeout_per_step == 30.0

    def test_initialization_with_options(self, mock_clients):
        """Test initialization with custom options."""
        middleware = OrchestrationMiddleware(
            mock_clients,
            auto_orchestrate=False,
            timeout_per_step=60.0,
        )
        assert middleware.auto_orchestrate is False
        assert middleware.timeout_per_step == 60.0

    def test_get_registered_servers(self, middleware):
        """Test getting registered server names."""
        servers = middleware.get_registered_servers()
        assert "mcp-python-ingestion" in servers
        assert "robot-server" in servers
        assert len(servers) == 2


class TestCallToolPassthrough:
    """Tests for call_tool passthrough behavior."""

    @pytest.mark.asyncio
    async def test_call_tool_passthrough(self, mock_clients, middleware):
        """Test non-execution-plan results pass through."""
        mock_clients["robot-server"].call_tool.return_value = {"status": "success"}
        
        result = await middleware.call_tool("robot-server", "test_tool", {})
        
        assert result["status"] == "success"
        mock_clients["robot-server"].call_tool.assert_called_once_with("test_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_with_arguments(self, mock_clients, middleware):
        """Test tool call with arguments."""
        mock_clients["robot-server"].call_tool.return_value = {"picked": "block_a"}
        
        result = await middleware.call_tool(
            "robot-server",
            "pickup_block",
            {"block": "block_a"},
        )
        
        assert result["picked"] == "block_a"

    @pytest.mark.asyncio
    async def test_call_tool_unknown_server(self, middleware):
        """Test error when calling unknown server."""
        with pytest.raises(KeyError) as exc_info:
            await middleware.call_tool("unknown-server", "tool", {})
        
        assert "unknown-server" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_call_tool_converts_model_to_dict(self, mock_clients, middleware):
        """Test that pydantic models are converted to dict."""
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {"data": "value"}
        mock_clients["robot-server"].call_tool.return_value = mock_result
        
        result = await middleware.call_tool("robot-server", "tool", {})
        
        assert result == {"data": "value"}


class TestExecutionPlanDetection:
    """Tests for execution plan detection."""

    def test_is_execution_plan_true(self, middleware):
        """Test detection of execution plan response."""
        result = {"requires_client_orchestration": True, "plan": {}}
        assert middleware._is_execution_plan(result) is True

    def test_is_execution_plan_false(self, middleware):
        """Test non-execution-plan response."""
        result = {"status": "success", "data": []}
        assert middleware._is_execution_plan(result) is False

    def test_is_execution_plan_missing_key(self, middleware):
        """Test response without orchestration key."""
        result = {"plan": {}}
        assert middleware._is_execution_plan(result) is False

    def test_is_execution_plan_false_value(self, middleware):
        """Test response with False orchestration value."""
        result = {"requires_client_orchestration": False}
        assert middleware._is_execution_plan(result) is False


class TestOrchestration:
    """Tests for plan orchestration."""

    @pytest.mark.asyncio
    async def test_orchestrate_simple_plan(self, mock_clients, middleware):
        """Test orchestrating a simple plan."""
        # Create a plan response
        plan_response = {
            "requires_client_orchestration": True,
            "plan": {
                "plan_id": "test-plan",
                "goal": "Test goal",
                "steps": [
                    {
                        "step": 1,
                        "action": ["pickup", "block_a"],
                        "server": "robot-server",
                        "tool": "pickup",
                        "arguments": {"block": "block_a"},
                    }
                ],
            },
            "metadata": {"execution_id": "exec-001"},
            "servers_required": ["robot-server"],
        }
        
        # Mock the initial call and step execution
        mock_clients["mcp-python-ingestion"].call_tool.return_value = plan_response
        mock_clients["robot-server"].call_tool.return_value = {"success": True}
        
        result = await middleware.call_tool(
            "mcp-python-ingestion",
            "python_execute_plan",
            {"goal": "test"},
        )

        assert result["success"] is True
        assert result["steps_completed"] == 1

    @pytest.mark.asyncio
    async def test_orchestrate_multi_step_plan(self, mock_clients, middleware):
        """Test orchestrating a multi-step plan."""
        plan_response = {
            "requires_client_orchestration": True,
            "plan": {
                "plan_id": "multi-plan",
                "goal": "Stack blocks",
                "steps": [
                    {
                        "step": 1,
                        "action": ["pickup", "a"],
                        "server": "robot-server",
                        "tool": "pickup",
                        "arguments": {},
                    },
                    {
                        "step": 2,
                        "action": ["place", "a"],
                        "server": "robot-server",
                        "tool": "place",
                        "arguments": {},
                        "dependencies": [1],
                    },
                ],
            },
            "metadata": {"execution_id": "exec-002"},
            "servers_required": ["robot-server"],
        }

        mock_clients["mcp-python-ingestion"].call_tool.return_value = plan_response
        mock_clients["robot-server"].call_tool.side_effect = [
            {"picked": "a"},
            {"placed": "a"},
        ]

        result = await middleware.call_tool(
            "mcp-python-ingestion",
            "python_execute_plan",
            {},
        )

        assert result["success"] is True
        assert result["steps_completed"] == 2
        assert result["total_steps"] == 2

    @pytest.mark.asyncio
    async def test_orchestrate_step_failure(self, mock_clients, middleware):
        """Test orchestration stops on step failure."""
        plan_response = {
            "requires_client_orchestration": True,
            "plan": {
                "plan_id": "fail-plan",
                "goal": "Fail test",
                "steps": [
                    {"step": 1, "action": ["fail"], "server": "robot-server", "tool": "fail_tool", "arguments": {}},
                    {"step": 2, "action": ["skip"], "server": "robot-server", "tool": "skip_tool", "arguments": {}},
                ],
            },
            "metadata": {"execution_id": "exec-fail"},
            "servers_required": ["robot-server"],
        }

        mock_clients["mcp-python-ingestion"].call_tool.return_value = plan_response
        mock_clients["robot-server"].call_tool.side_effect = Exception("Tool failed")

        result = await middleware.call_tool(
            "mcp-python-ingestion",
            "python_execute_plan",
            {},
        )

        assert result["success"] is False
        assert result["steps_failed"] == 1
        # Step 2 should not be executed

    @pytest.mark.asyncio
    async def test_orchestrate_missing_server(self, mock_clients, middleware):
        """Test error when plan requires unavailable server."""
        plan_response = {
            "requires_client_orchestration": True,
            "plan": {
                "plan_id": "missing-plan",
                "goal": "Missing server",
                "steps": [],
            },
            "metadata": {"execution_id": "exec-miss"},
            "servers_required": ["unknown-server"],
        }

        mock_clients["mcp-python-ingestion"].call_tool.return_value = plan_response

        result = await middleware.call_tool(
            "mcp-python-ingestion",
            "python_execute_plan",
            {},
        )

        assert result["success"] is False
        assert "unknown-server" in str(result["error"])


class TestExecutionHistory:
    """Tests for execution history tracking."""

    @pytest.mark.asyncio
    async def test_history_recorded(self, mock_clients, middleware):
        """Test that execution is recorded in history."""
        plan_response = {
            "requires_client_orchestration": True,
            "plan": {
                "plan_id": "hist-plan",
                "goal": "History test",
                "steps": [
                    {"step": 1, "action": ["test"], "server": "robot-server", "tool": "test", "arguments": {}},
                ],
            },
            "metadata": {"execution_id": "exec-hist"},
            "servers_required": ["robot-server"],
        }

        mock_clients["mcp-python-ingestion"].call_tool.return_value = plan_response
        mock_clients["robot-server"].call_tool.return_value = {"done": True}

        await middleware.call_tool("mcp-python-ingestion", "python_execute_plan", {})

        history = middleware.get_execution_history()
        assert len(history) == 1
        assert history[0]["plan_id"] == "hist-plan"

    def test_clear_history(self, middleware):
        """Test clearing execution history."""
        middleware.execution_history.append({"test": "data"})
        middleware.clear_history()
        assert len(middleware.execution_history) == 0


class TestAutoOrchestrate:
    """Tests for auto_orchestrate setting."""

    @pytest.mark.asyncio
    async def test_auto_orchestrate_disabled(self, mock_clients):
        """Test that auto-orchestration can be disabled."""
        middleware = OrchestrationMiddleware(mock_clients, auto_orchestrate=False)

        plan_response = {
            "requires_client_orchestration": True,
            "plan": {"plan_id": "p", "goal": "g", "steps": []},
            "metadata": {"execution_id": "e"},
        }

        mock_clients["mcp-python-ingestion"].call_tool.return_value = plan_response

        result = await middleware.call_tool(
            "mcp-python-ingestion",
            "python_execute_plan",
            {},
        )

        # Should return raw response without orchestrating
        assert result["requires_client_orchestration"] is True

