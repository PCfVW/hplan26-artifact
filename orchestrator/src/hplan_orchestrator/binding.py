"""Binding layer: GTPyhop plan + mappings/<domain>.json -> execution-plan payload.

This is NEW code written for this artifact. In the system the paper describes,
the binding step ran inside the private backend's ``python_execute_plan`` tool
(``execution_mode="mcp_distributed"``), which read the stored plan and the
action->tool mapping edges from a graph database. Here the same step reads the
plan directly from GTPyhop and the mappings directly from the JSON files the
database was populated from. The returned dictionary reproduces that tool's
payload field for field:

    {"requires_client_orchestration": True,
     "plan": ExecutionPlan, "metadata": OrchestrationMetadata,
     "servers_required": sorted([...])}

Behaviour preserved from the original:
  * steps are numbered from 1 in plan order;
  * action parameters are stringified (``str(p)``), both in the action tuple
    and in the tool arguments;
  * ``parameter_mapping`` {"<index>": "<tool argument>"} maps positional action
    parameters to named tool arguments; indices beyond the action's arity are
    skipped (so tool-side defaults apply);
  * without a ``parameter_mapping``, parameters are passed as arg0, arg1, ...;
  * ``${var}`` is substituted with runtime parameters at binding time, while
    ``${context.var}`` is left untouched for the middleware to substitute at
    execution time;
  * an action with no mapping is skipped (``strict=False``); by default this
    artifact is stricter and raises instead.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .orchestration.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    OrchestrationMetadata,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MAPPINGS_DIR = REPO_ROOT / "mappings"
SCHEMA_PATH = REPO_ROOT / "schemas" / "action_tool_mapping_schema.json"


def load_mapping(name_or_path: str | Path, validate: bool = True) -> Dict[str, Any]:
    """Load mappings/<name>.json (or an explicit path) and validate it against the schema."""
    path = Path(name_or_path)
    if not path.suffix:
        path = MAPPINGS_DIR / f"{name_or_path}.json"
    with open(path, encoding="utf-8") as f:
        mapping = json.load(f)
    if validate:
        validate_mapping(mapping)
    return mapping


def validate_mapping(mapping: Dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the mapping violates the schema,
    ValueError if verify_bijection is set and two actions share a (server, tool)."""
    import jsonschema

    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(mapping, schema)
    if mapping.get("verify_bijection"):
        actions = [m["action"] for m in mapping["mappings"]]
        tools = [(m["server"], m["tool"]) for m in mapping["mappings"]]
        if len(set(actions)) != len(actions) or len(set(tools)) != len(tools):
            raise ValueError(f"{mapping['domain']}: action<->tool correspondence is not one-to-one")


def substitute_runtime_params(value: str, params: Dict[str, Any]) -> str:
    """Substitute ${var} with a runtime parameter; keep ${context.var} for execution time."""
    if not isinstance(value, str) or not params:
        return value

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        if var_name.startswith("context."):
            return match.group(0)
        return str(params.get(var_name, match.group(0)))

    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def unmapped_actions(plan: Sequence[Tuple], mapping: Dict[str, Any]) -> List[str]:
    known = {m["action"] for m in mapping["mappings"]}
    return sorted({a[0] for a in plan if a[0] not in known})


def bind_plan(
    plan: Sequence[Tuple],
    mapping: Dict[str, Any],
    plan_id: str,
    goal: str = "Execute plan",
    runtime_params: Optional[Dict[str, Any]] = None,
    strict: bool = True,
) -> Dict[str, Any]:
    """Join a GTPyhop plan with a binding-layer mapping into an execution-plan payload."""
    by_action = {m["action"]: m for m in mapping["mappings"]}
    runtime_params = runtime_params or {}
    if strict and (missing := unmapped_actions(plan, mapping)):
        raise KeyError(f"Actions without a mapping in {mapping['domain']}: {missing}")

    exec_steps: List[ExecutionStep] = []
    servers = set()
    for sequence, action in enumerate(plan, start=1):
        m = by_action.get(action[0])
        if m is None:
            continue  # original behaviour: silently skip unmapped actions
        action_name, parameters = action[0], list(action[1:])
        param_mapping = m.get("parameter_mapping") or {}
        servers.add(m["server"])

        tool_args: Dict[str, Any] = {}
        if param_mapping and parameters:
            for idx_str, arg_name in param_mapping.items():
                idx = int(idx_str)
                if idx < len(parameters):
                    tool_args[arg_name] = substitute_runtime_params(str(parameters[idx]), runtime_params)
        elif parameters:
            tool_args = {f"arg{i}": substitute_runtime_params(str(p), runtime_params)
                         for i, p in enumerate(parameters)}

        exec_steps.append(ExecutionStep(
            step=sequence,
            action=(action_name, *[str(p) for p in parameters]),
            server=m["server"],
            tool=m["tool"],
            arguments=tool_args,
            dependencies=[],
            description=f"{action_name} on {m['server']}",
            output_extractors=m.get("output_extractors") or {},
        ))

    now = datetime.now(timezone.utc)
    exec_plan = ExecutionPlan(plan_id=plan_id, goal=goal, steps=exec_steps,
                              created_at=now, total_steps=len(exec_steps))
    metadata = OrchestrationMetadata(
        execution_id=f"exec_{plan_id}_{now.strftime('%Y%m%d_%H%M%S')}",
        started_at=now, status="pending", steps_completed=0, steps_failed=0, current_step=0,
    )
    return {
        "requires_client_orchestration": True,
        "plan": exec_plan.model_dump(),
        "metadata": metadata.model_dump(),
        "servers_required": sorted(servers),
    }


def make_plan_id(problem: str, when: Optional[datetime] = None) -> str:
    """Plan key in the backend's format, e.g. plan_20251210_161447_scenario_1_breast_ca."""
    when = when or datetime.now()
    return f"plan_{when.strftime('%Y%m%d_%H%M%S')}_{problem[:20]}"
