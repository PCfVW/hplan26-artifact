"""Mock MCP clients for running the pipeline offline (NEW code).

``RecordedBiologyMCPClient`` replays responses recorded from the eight live
Augmented Nature servers (``data/drug_target_discovery_recorded.json``) and
wraps them exactly as ``RealMCPClient.call_tool`` does
(``{"success", "server", "tool", "data", "arguments"}``), so the binding
layer's JSON-path output extractors and the middleware's ``${context.X}``
substitution run on realistically shaped data.

Why not the original ``MockBiologyMCPClient`` of mcp-python-ingestion? Its
canned payloads (e.g. ``{"diseases": [...]}``) do not have the shapes the
mapping's extractors address (e.g. ``data.search.hits[0].id``), so none of the
extractors fire and the ``${context.X}`` templates would pass through
unsubstituted. It is therefore not used here.

``EchoMCPClient`` is a generic mock for the Opentrons domains: it echoes the
(already bound and substituted) arguments back. It exercises the binding
layer, parameter mapping and middleware sequencing faithfully; it does not
simulate the robot.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

RECORDED = Path(__file__).resolve().parents[1] / "data" / "drug_target_discovery_recorded.json"


class RecordedBiologyMCPClient:
    def __init__(self, server_name: str, delay_ms: float = 0.0, recorded: Path = RECORDED) -> None:
        self.server_name = server_name
        self.delay_ms = delay_ms
        self.call_count = 0
        self.tools_called: List[str] = []
        with open(recorded, encoding="utf-8") as f:
            self._responses: Dict[str, Any] = json.load(f)["responses"]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000.0)
        key = f"{self.server_name}/{name}"
        if key not in self._responses:
            raise KeyError(f"No recorded response for {key}")
        self.call_count += 1
        self.tools_called.append(name)
        return {"success": True, "server": self.server_name, "tool": name,
                "data": json.loads(json.dumps(self._responses[key])), "arguments": arguments}


class EchoMCPClient:
    def __init__(self, server_name: str, delay_ms: float = 0.0) -> None:
        self.server_name = server_name
        self.delay_ms = delay_ms
        self.call_count = 0
        self.tools_called: List[str] = []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000.0)
        self.call_count += 1
        self.tools_called.append(name)
        return {"success": True, "server": self.server_name, "tool": name,
                "data": {"echo": dict(arguments)}, "arguments": arguments}
