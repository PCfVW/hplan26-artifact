"""Error reporting: tool-level errors, extractor misses, skipped steps and the
per-status summary (NEW; tests the changes to the middleware and the live
client listed in NOTICE)."""

import asyncio
from types import SimpleNamespace

from hplan_orchestrator.clients.live import RealMCPClient
from hplan_orchestrator.clients.mock import RecordedBiologyMCPClient
from hplan_orchestrator.orchestration.execution_plan import ExecutionStatus
from hplan_orchestrator.orchestration.middleware import OrchestrationMiddleware
from hplan_orchestrator.runner import format_report, run_pipeline, status_counts

DRUG_SERVERS = ["opentargets-server", "uniprot-server", "reactome-server", "kegg-server",
                "pdb-server", "alphafold-server", "chembl-server", "pubmed-server"]


class ScriptedClient:
    """Returns the scripted result for each tool name and records the calls."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        r = self.results[name]
        if isinstance(r, Exception):
            raise r
        return r


def _plan(steps):
    return {
        "requires_client_orchestration": True,
        "plan": {"plan_id": "p", "goal": "g", "steps": [
            {"action": [s["tool"]], "server": "srv", "arguments": {}, **s} for s in steps]},
        "metadata": {"execution_id": "e"},
        "servers_required": ["srv"],
    }


async def _run(steps, results, **kwargs):
    client = ScriptedClient(results)
    planner = ScriptedClient({"plan": _plan(steps)})
    mw = OrchestrationMiddleware({"planner": planner, "srv": client}, enable_progress_bar=False, **kwargs)
    return await mw.call_tool("planner", "plan", {}), client, mw


# 1. Tool-level errors -------------------------------------------------------

async def test_live_client_honours_is_error():
    """RealMCPClient.call_tool turns CallToolResult.isError into success: False."""
    c = RealMCPClient("alphafold-server", "node", [])
    c._connected, c._session = True, object()
    c._call_queue, c._response_queue = asyncio.Queue(), asyncio.Queue()
    text = "Error fetching AlphaFold structure: Request failed with status code 404"
    await c._response_queue.put((True, SimpleNamespace(isError=True, content=[SimpleNamespace(text=text)])))
    r = await c.call_tool("get_structure", {"uniprotId": "P51587"})
    assert r["success"] is False and r["isError"] is True and r["error"] == text
    await c._response_queue.put((True, SimpleNamespace(isError=False, content=[SimpleNamespace(text='{"a": 1}')])))
    r = await c.call_tool("get_structure", {"uniprotId": "P00533"})
    assert r["success"] is True and r["data"] == {"a": 1} and "isError" not in r


async def test_is_error_result_is_failed():
    res, _, _ = await _run([{"step": 1, "tool": "t"}],
                           {"t": {"isError": True, "data": {"text": "404 no model"}}})
    assert res["success"] is False and res["steps_failed"] == 1 and res["steps_completed"] == 0
    assert res["step_results"][0]["status"] == ExecutionStatus.FAILED
    assert res["step_results"][0]["error"] == "404 no model"


async def test_success_false_dict_is_failed():
    res, _, _ = await _run([{"step": 1, "tool": "t"}], {"t": {"success": False, "error": "bad input"}})
    assert res["steps_failed"] == 1 and res["step_results"][0]["error"] == "bad input"


async def test_call_tool_result_model_with_is_error_is_failed():
    class FakeCallToolResult:
        def model_dump(self):
            return {"isError": True, "content": [{"type": "text", "text": "upstream 500"}]}

    res, _, _ = await _run([{"step": 1, "tool": "t"}], {"t": FakeCallToolResult()})
    assert res["steps_failed"] == 1 and res["step_results"][0]["error"] == "upstream 500"


# 2. Extractor misses --------------------------------------------------------

async def test_extractor_miss_is_recorded():
    res, _, _ = await _run(
        [{"step": 1, "tool": "t", "output_extractors": {"found": "a", "gone": "targets[0].id", "empty": "b"}}],
        {"t": {"success": True, "data": {"a": "x", "targets": [], "b": []}}})
    r = res["step_results"][0]
    assert r["status"] == ExecutionStatus.SUCCESS
    assert r["missing_outputs"] == ["gone", "empty"]
    assert res["success"] is True
    assert res["steps_succeeded"] == 0 and res["steps_succeeded_with_missing_outputs"] == 1


async def test_extractor_miss_on_empty_data():
    res, _, _ = await _run([{"step": 1, "tool": "t", "output_extractors": {"v": "x"}}],
                           {"t": {"success": True, "data": {}}})
    assert res["step_results"][0]["missing_outputs"] == ["v"]


# 3. Unresolved dependencies -------------------------------------------------

STEPS = [
    {"step": 1, "tool": "fail", "output_extractors": {"gene": "gene"}},
    {"step": 2, "tool": "dependent", "arguments": {"q": "${context.gene}"}},
    {"step": 3, "tool": "independent", "arguments": {"q": "fixed"}, "output_extractors": {"n": "n"}},
    {"step": 4, "tool": "declared", "dependencies": [1]},
]
RESULTS = {"fail": {"isError": True, "error": "boom"}, "dependent": {"success": True},
           "independent": {"success": True, "data": {"n": 3}}, "declared": {"success": True}}


async def test_dependent_step_skipped_independent_step_runs():
    res, client, _ = await _run(STEPS, RESULTS)
    statuses = [r["status"] for r in res["step_results"]]
    assert statuses == [ExecutionStatus.FAILED, ExecutionStatus.SKIPPED,
                        ExecutionStatus.SUCCESS, ExecutionStatus.SKIPPED]
    # The skipped steps never reached the server; no literal placeholder was sent
    assert [name for name, _ in client.calls] == ["fail", "independent"]
    assert "${context.gene}" in res["step_results"][1]["error"]
    assert "dependency step(s) 1" in res["step_results"][3]["error"]


async def test_stop_on_failure_restores_original_policy():
    res, client, _ = await _run(STEPS, RESULTS, stop_on_failure=True)
    assert [name for name, _ in client.calls] == ["fail"]
    assert res["steps_not_run"] == 3 and res["success"] is False


# 4. Summary counts ----------------------------------------------------------

async def test_summary_counts():
    steps = STEPS + [{"step": 5, "tool": "partial", "output_extractors": {"m": "missing"}}]
    res, _, mw = await _run(steps, {**RESULTS, "partial": {"success": True, "data": {"x": 1}}})
    counts = {k: res[k] for k in ("steps_succeeded", "steps_succeeded_with_missing_outputs",
                                  "steps_failed", "steps_skipped", "steps_not_run")}
    assert counts == {"steps_succeeded": 1, "steps_succeeded_with_missing_outputs": 1,
                      "steps_failed": 1, "steps_skipped": 2, "steps_not_run": 0}
    assert res["success"] is False
    record = mw.get_execution_history()[0]
    assert record["steps_skipped"] == 2 and record["step_results"][4]["missing_outputs"] == ["m"]


async def test_pipeline_report_skips_the_chain_after_an_error():
    """End to end: an isError on step 2 leaves first_gene uncaptured, so every
    step that needs it (directly or through uniprot_accession) is skipped;
    PubMed, which needs no context value, still runs."""
    clients = {s: RecordedBiologyMCPClient(s) for s in DRUG_SERVERS}
    clients["opentargets-server"]._is_error.add("opentargets-server/get_disease_targets_summary")
    rep = await run_pipeline("drug_target_discovery", "scenario_1_breast_cancer", clients)
    assert [s.status for s in rep.steps] == ["success", "failed"] + ["skipped"] * 5 + ["success"]
    assert status_counts(rep) == {"succeeded": 2, "succeeded with missing outputs": 0,
                                  "failed": 1, "skipped": 5, "not run": 0}
    assert all(s.actual_args is None for s in rep.steps if s.status == "skipped")
    assert rep.steps[7].actual_args == {"query": "breast cancer drug target therapeutic"}
    assert "${context.uniprot_accession}" in rep.steps[4].error
    text = format_report(rep)
    assert "steps: 2 succeeded, 0 succeeded with missing outputs, 1 failed, 5 skipped (of 8)" in text
