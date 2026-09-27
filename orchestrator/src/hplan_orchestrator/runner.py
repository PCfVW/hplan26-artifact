"""End-to-end pipeline shared by scripts/run_mock.py and scripts/run_live.py (NEW code).

plan (GTPyhop) -> bind (mappings/<domain>.json) -> execute (OrchestrationMiddleware).

Both tools of the in-process planning server are called *through* the
middleware, so the execution plan is detected and orchestrated by the
middleware's own ``requires_client_orchestration`` path, as in the paper.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .clients.planner import PLANNER_SERVER, LocalPlanningClient
from .orchestration import OrchestrationMiddleware
from .orchestration.middleware import extract_json_path


class RecordingClient:
    """Wraps an MCP client and records the arguments it actually receives,
    i.e. after the middleware has substituted ${context.X} templates."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: List[Dict[str, Any]] = []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        self.calls.append({"tool": name, "arguments": dict(arguments)})
        return await self.inner.call_tool(name, arguments)


# Status label for a SUCCESS step some of whose output extractors found no value
SUCCESS_MISSING = "success, missing outputs"


@dataclass
class StepReport:
    step: int
    action: tuple
    server: str
    tool: str
    template_args: Dict[str, Any]
    actual_args: Optional[Dict[str, Any]]
    status: str
    duration_ms: Optional[float]
    extracted: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    note: Optional[str] = None
    output_extractors_missed: List[str] = field(default_factory=list)


@dataclass
class RunReport:
    plan_key: str
    plan_length: int
    payload: Dict[str, Any]
    result: Dict[str, Any]
    steps: List[StepReport]
    wall_clock_s: float

    @property
    def success(self) -> bool:
        return bool(self.result.get("success"))


async def run_pipeline(domain: str, problem: str, clients: Dict[str, Any],
                       runtime_params: Optional[Dict[str, Any]] = None,
                       timeout_per_step: float = 45.0,
                       progress_bar: bool = False) -> RunReport:
    planner = LocalPlanningClient()
    recorders = {name: RecordingClient(c) for name, c in clients.items()}
    middleware = OrchestrationMiddleware(
        {PLANNER_SERVER: planner, **recorders},
        auto_orchestrate=True, timeout_per_step=timeout_per_step,
        enable_progress_bar=progress_bar,
    )

    found = await middleware.call_tool(PLANNER_SERVER, "python_find_plan",
                                       {"domain": domain, "problem": problem})
    if found.get("status") != "success":
        raise RuntimeError(found.get("error"))
    plan_key = found["plan_key"]

    # Also keep the raw payload for display (the middleware consumes its own copy).
    payload = await planner.call_tool("python_execute_plan", {
        "plan_key": plan_key, "execution_mode": "mcp_distributed", "parameters": runtime_params or {}})

    t0 = time.perf_counter()
    result = await middleware.call_tool(PLANNER_SERVER, "python_execute_plan", {
        "plan_key": plan_key, "execution_mode": "mcp_distributed",
        "parameters": runtime_params or {}, "dry_run": False, "max_retries": 0,
        "stop_on_failure": True,
    })
    wall = time.perf_counter() - t0

    # Re-derive the per-step view: actual (substituted) arguments from the
    # recorders, extracted values with the middleware's own extract_json_path.
    call_cursor = {name: 0 for name in recorders}
    results_by_step = {r["step"]: r for r in result.get("step_results", [])}
    steps: List[StepReport] = []
    for s in payload["plan"]["steps"]:
        r = results_by_step.get(s["step"])
        actual = None
        status = getattr(r["status"], "value", r["status"]) if r else "not run"
        if r is not None and status != "skipped":  # a skipped step never reached its server
            rec = recorders[s["server"]]
            actual = rec.calls[call_cursor[s["server"]]]["arguments"]
            call_cursor[s["server"]] += 1
        extracted: Dict[str, Any] = {}
        note = None
        missed = list((r or {}).get("missing_outputs") or [])
        if status == "success":
            data = r["result"]
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            # A tool may report an error as plain text without setting isError
            # (PubMed never sets it); flag results that carry no JSON data.
            if isinstance(data, dict) and set(data) == {"text"}:
                note = "tool returned text, not JSON: " + _short(data["text"], 90)
            for var, path in (s.get("output_extractors") or {}).items():
                if var not in missed:
                    extracted[var] = extract_json_path(data, path)
            if missed:
                status = SUCCESS_MISSING
        steps.append(StepReport(
            step=s["step"], action=tuple(s["action"]), server=s["server"], tool=s["tool"],
            template_args=s["arguments"], actual_args=actual,
            status=status, duration_ms=(r or {}).get("duration_ms"),
            extracted=extracted, error=(r or {}).get("error"), note=note,
            output_extractors_missed=missed,
        ))
    return RunReport(plan_key, found["plan_length"], payload, result, steps, wall)


def _short(v: Any, n: int = 70) -> str:
    s = repr(v) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 3] + "..."


def format_report(rep: RunReport, show_args: bool = True, max_rows: Optional[int] = None) -> str:
    out = [f"plan_key: {rep.plan_key}   plan length: {rep.plan_length}   "
           f"bound steps: {len(rep.steps)}   servers_required: {', '.join(rep.payload['servers_required'])}"]
    out.append(f"{'#':>3}  {'server':<18} {'tool':<30} {'status':<25} {'ms':>9}")
    for i, s in enumerate(rep.steps):
        if max_rows is not None and i == max_rows:
            out.append(f"  ... {len(rep.steps) - max_rows} more steps (use --verbose)")
            break
        ms = f"{s.duration_ms:9.0f}" if s.duration_ms is not None else f"{'-':>9}"
        out.append(f"{s.step:>3}  {s.server:<18} {s.tool:<30} {s.status:<25} {ms}")
        if show_args:
            for k, tv in s.template_args.items():
                av = (s.actual_args or {}).get(k, tv)
                if av != tv:
                    out.append(f"       {k}: {tv}  ->  {_short(av)}")
                else:
                    out.append(f"       {k}: {_short(tv)}")
            for k, v in s.extracted.items():
                out.append(f"       => context.{k} = {_short(v)}")
            if s.note:
                out.append(f"       (note: {s.note})")
        if s.output_extractors_missed:
            out.append(f"       ?? no value for: {', '.join(s.output_extractors_missed)}")
        if s.error:
            out.append(f"       !! {s.error}")
    out.append(summary_line(rep))
    return "\n".join(out)


def status_counts(rep: RunReport) -> Dict[str, int]:
    """Per-status step counts, from the middleware's execution record."""
    r = rep.result
    return {"succeeded": r.get("steps_succeeded", 0),
            "succeeded with missing outputs": r.get("steps_succeeded_with_missing_outputs", 0),
            "failed": r.get("steps_failed", 0),
            "skipped": r.get("steps_skipped", 0),
            "not run": r.get("steps_not_run", 0)}


def summary_line(rep: RunReport) -> str:
    counts = status_counts(rep)
    parts = [f"{v} {k}" for k, v in counts.items() if v or k != "not run"]
    return (f"steps: {', '.join(parts)} (of {rep.result.get('total_steps')})   "
            f"all succeeded: {rep.success}   wall-clock: {rep.wall_clock_s:.1f} s")


def substitution_chain(rep: RunReport) -> List[str]:
    """Context variables in the order they were first captured."""
    seen: List[str] = []
    for s in rep.steps:
        for k in s.extracted:
            if k not in seen:
                seen.append(k)
    return seen
