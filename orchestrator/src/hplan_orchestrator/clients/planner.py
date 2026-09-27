"""In-process planning "server": python_find_plan / python_execute_plan without a database.

NEW code. In the paper's system these two tools lived on a separate MCP server
backed by a graph database. Here they are an in-process object that implements
the same ``call_tool(name, arguments)`` protocol the middleware expects, keeps
stored plans in a dict, and binds them with ``hplan_orchestrator.binding``.
Calling ``python_execute_plan`` through ``OrchestrationMiddleware.call_tool``
therefore exercises the middleware's own plan-detection path
(``requires_client_orchestration: true``), exactly as the backend did.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .. import binding, planning

PLANNER_SERVER = "gtpyhop-planner"


class LocalPlanningClient:
    def __init__(self) -> None:
        self.plans: Dict[str, Dict[str, Any]] = {}

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "python_find_plan":
            return self._find_plan(**arguments)
        if name == "python_execute_plan":
            return self._execute_plan(**arguments)
        raise ValueError(f"Unknown tool {name!r}")

    def _find_plan(self, domain: str, problem: str, plan_key: Optional[str] = None) -> Dict[str, Any]:
        result = planning.plan(domain, problem)
        if result.plan is None:
            return {"status": "failure", "error": f"No plan for {domain}/{problem}"}
        key = plan_key or binding.make_plan_id(problem)
        self.plans[key] = {"domain": domain, "problem": problem, "plan": result.plan,
                           "goal": result.description.strip().splitlines()[0] if result.description else "Execute plan"}
        return {"status": "success", "plan_key": key, "plan_length": len(result.plan),
                "plan": [list(a) for a in result.plan]}

    def _execute_plan(self, plan_key: str, execution_mode: str = "mcp_distributed",
                      parameters: Optional[Dict[str, Any]] = None, **_ignored: Any) -> Dict[str, Any]:
        if plan_key not in self.plans:
            return {"status": "failure", "error": f"Plan not found: {plan_key}"}
        if execution_mode != "mcp_distributed":
            return {"status": "failure", "error": "Only execution_mode='mcp_distributed' is supported here"}
        stored = self.plans[plan_key]
        mapping_name = planning.DOMAINS[stored["domain"]]
        if mapping_name is None:
            return {"status": "failure", "error": f"{stored['domain']} has no binding-layer mapping"}
        mapping = binding.load_mapping(mapping_name)
        return binding.bind_plan(stored["plan"], mapping, plan_id=plan_key,
                                 goal=stored["goal"], runtime_params=parameters or {})
