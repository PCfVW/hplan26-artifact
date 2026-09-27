"""Live MCP client: stdio connection to a real MCP server (Node.js subprocess).

``RealMCPClient`` is copied verbatim from mcp-python-ingestion v0.29.2,
``examples/orchestration_demo/demo_drug_target_discovery_full_mcp.py``
(the class the paper's backend imported for its live runs). Only the class was
extracted; the surrounding demo (graph-database planning, CLI) was not.
``MCPServerError`` is re-declared here as a plain Exception subclass (it
derived from a demo-specific base class there). ``load_server_config`` is new:
it replaces the demo's fixed ``~/mcp-servers`` resolution with a configurable
servers root.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hplan-orchestrator.live")

SERVERS_ROOT_ENV = "HPLAN_MCP_SERVERS_ROOT"
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "servers" / "mcp_servers.json"


class MCPServerError(Exception):
    """Error communicating with MCP server."""
    pass


def resolve_servers_root(cli_value: Optional[str] = None) -> Path:
    """--servers-root, else $HPLAN_MCP_SERVERS_ROOT, else ~/mcp-servers."""
    raw = cli_value or os.environ.get(SERVERS_ROOT_ENV) or str(Path.home() / "mcp-servers")
    return Path(raw).expanduser().resolve()


def load_server_config(servers_root: Path, config_path: Path = DEFAULT_CONFIG) -> Dict[str, Dict[str, Any]]:
    """Load servers/mcp_servers.json, replacing ${SERVERS_ROOT} in args."""
    with open(config_path, encoding="utf-8") as f:
        servers = json.load(f)["mcpServers"]
    for cfg in servers.values():
        cfg["args"] = [a.replace("${SERVERS_ROOT}", str(servers_root)) for a in cfg.get("args", [])]
    return servers


class RealMCPClient:
    """
    Real MCP client for Augmented Nature biology servers.

    Connects to actual MCP servers via stdio transport using the MCP Python SDK.
    Implements the MCPClientProtocol interface.

    The client manages connection lifecycle using an asyncio.Event signal pattern
    to ensure proper cleanup from the same task context that entered the context
    managers. This avoids the "Attempted to exit cancel scope in a different task"
    RuntimeError that occurs with anyio task groups.
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize real MCP client.

        Args:
            server_name: Human-readable server name
            command: Command to launch server (e.g., "node")
            args: Arguments to pass to command
            env: Environment variables for server process
            timeout: Timeout for tool calls in seconds
        """
        self.server_name = server_name
        self.command = command
        self.args = args
        self.env = env or {}
        self.timeout = timeout
        self.call_count = 0
        self.tools_called: List[str] = []
        self._session: Optional[Any] = None
        self._connected = False
        # Event-based cleanup pattern to avoid anyio task group issues
        self._shutdown_event: Optional[asyncio.Event] = None
        self._connection_task: Optional[asyncio.Task] = None
        self._ready_event: Optional[asyncio.Event] = None
        self._connection_error: Optional[Exception] = None
        # Queue for tool call requests/responses
        self._call_queue: Optional[asyncio.Queue] = None
        self._response_queue: Optional[asyncio.Queue] = None

    async def _connection_manager(self) -> None:
        """
        Background task that manages the MCP connection lifecycle.

        This task enters the context managers and stays alive until the
        shutdown event is set, ensuring cleanup happens in the same task
        that entered the context managers.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=self.env,
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._connected = True
                    logger.info(f"[OK] Connected to {self.server_name}")

                    # Signal that connection is ready
                    self._ready_event.set()

                    # Process tool calls until shutdown
                    while not self._shutdown_event.is_set():
                        try:
                            # Wait for a tool call request with timeout
                            request = await asyncio.wait_for(
                                self._call_queue.get(),
                                timeout=0.1
                            )
                            if request is None:
                                # Shutdown signal via queue
                                break

                            tool_name, arguments = request
                            try:
                                result = await asyncio.wait_for(
                                    session.call_tool(tool_name, arguments=arguments),
                                    timeout=self.timeout,
                                )
                                await self._response_queue.put((True, result))
                            except Exception as e:
                                await self._response_queue.put((False, e))

                        except asyncio.TimeoutError:
                            # No request, check shutdown event again
                            continue

        except FileNotFoundError as e:
            self._connection_error = e
            logger.warning(f"[!] Server not found for {self.server_name}: {e}")
        except Exception as e:
            self._connection_error = e
            logger.warning(f"[!] Failed to connect to {self.server_name}: {e}")
        finally:
            self._connected = False
            self._session = None
            if self._ready_event:
                self._ready_event.set()  # Unblock connect() if waiting

    async def connect(self) -> bool:
        """
        Establish connection to the MCP server.

        Starts a background task that manages the connection lifecycle,
        ensuring proper cleanup from the same task context.

        Returns:
            True if connection successful, False otherwise
        """
        self._shutdown_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._call_queue = asyncio.Queue()
        self._response_queue = asyncio.Queue()
        self._connection_error = None

        # Start the connection manager task
        self._connection_task = asyncio.create_task(
            self._connection_manager(),
            name=f"mcp-connection-{self.server_name}"
        )

        # Wait for connection to be ready (or fail)
        await self._ready_event.wait()

        if self._connection_error:
            return False

        return self._connected

    async def disconnect(self) -> None:
        """
        Close connection to the MCP server.

        Signals the connection manager task to shutdown, which will properly
        exit the context managers from the same task that entered them.
        """
        if self._shutdown_event:
            self._shutdown_event.set()

        # Send shutdown signal via queue
        if self._call_queue:
            await self._call_queue.put(None)

        # Wait for the connection task to complete
        if self._connection_task:
            try:
                await asyncio.wait_for(self._connection_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for {self.server_name} to disconnect")
                self._connection_task.cancel()
                try:
                    await self._connection_task
                except asyncio.CancelledError:
                    pass
            except Exception as e:
                logger.debug(f"Error during disconnect from {self.server_name}: {e}")

        self._connection_task = None
        self._shutdown_event = None
        self._ready_event = None
        self._call_queue = None
        self._response_queue = None
        self._connected = False
        self._session = None

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._session is not None

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the MCP server.

        Uses the queue-based pattern to send requests to the connection manager
        task, which executes them in the same task context as the context managers.

        Args:
            name: Tool name to call
            arguments: Tool arguments

        Returns:
            Tool result dictionary

        Raises:
            MCPServerError: If server not connected or call fails
        """
        if not self.is_connected:
            raise MCPServerError(
                f"Not connected to {self.server_name}. Call connect() first."
            )

        if not self._call_queue or not self._response_queue:
            raise MCPServerError(
                f"Connection queues not initialized for {self.server_name}"
            )

        try:
            self.call_count += 1
            self.tools_called.append(name)

            # Send request to connection manager task
            await self._call_queue.put((name, arguments))

            # Wait for response with timeout
            success, result = await asyncio.wait_for(
                self._response_queue.get(),
                timeout=self.timeout + 5.0  # Extra buffer for queue overhead
            )

            if not success:
                # Result is an exception
                raise result

            # Parse the result - MCP returns CallToolResult with content list
            response_data = {}
            if hasattr(result, "content") and result.content:
                for content_item in result.content:
                    if hasattr(content_item, "text"):
                        # Try to parse as JSON, fallback to raw text
                        try:
                            import json
                            response_data = json.loads(content_item.text)
                        except (json.JSONDecodeError, TypeError):
                            response_data = {"text": content_item.text}
                        break

            return {
                "success": True,
                "server": self.server_name,
                "tool": name,
                "data": response_data,
                "arguments": arguments,
            }

        except asyncio.TimeoutError:
            raise MCPServerError(
                f"Timeout calling {self.server_name}::{name} after {self.timeout}s"
            )
        except MCPServerError:
            raise
        except Exception as e:
            raise MCPServerError(
                f"Error calling {self.server_name}::{name}: {e}"
            ) from e

    async def list_tools(self) -> List[str]:
        """
        List available tools on the server.

        Note: This method accesses the session directly for listing tools,
        which is safe as it's a read-only operation that doesn't affect
        the context manager lifecycle.

        Returns:
            List of tool names
        """
        if not self.is_connected:
            return []

        try:
            tools_response = await self._session.list_tools()
            return [t.name for t in tools_response.tools]
        except Exception as e:
            logger.warning(f"Failed to list tools for {self.server_name}: {e}")
            return []

