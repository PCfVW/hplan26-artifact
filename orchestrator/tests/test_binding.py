"""Binding layer (plan + mapping JSON -> execution-plan payload) and the
offline end-to-end pipeline (NEW)."""

import copy

import jsonschema
import pytest

from hplan_orchestrator import binding, planning
from hplan_orchestrator.clients.mock import EchoMCPClient, RecordedBiologyMCPClient
from hplan_orchestrator.orchestration import ExecutionPlanResponse
from hplan_orchestrator.runner import run_pipeline, status_counts, substitution_chain

MAPPINGS = ["drug_target_discovery", "bio_opentrons", "omega_hdq_dna_bacteria"]

# Server/tool sequence of the live runs (paper, Table 2 caption).
PAPER_SEQUENCE = [
    ("opentargets-server", "search_diseases"),
    ("opentargets-server", "get_disease_targets_summary"),
    ("uniprot-server", "search_by_gene"),
    ("reactome-server", "find_pathways_by_gene"),
    ("pdb-server", "search_by_uniprot"),
    ("alphafold-server", "get_structure"),
    ("chembl-server", "search_by_uniprot"),
    ("pubmed-server", "search_articles"),
]


@pytest.mark.parametrize("name", MAPPINGS)
def test_mappings_validate_against_schema(name):
    binding.load_mapping(name)  # raises on failure


def test_schema_rejects_bad_action_name():
    m = copy.deepcopy(binding.load_mapping("drug_target_discovery"))
    m["mappings"][0]["action"] = "search_disease"  # missing the a_ prefix
    with pytest.raises(jsonschema.ValidationError):
        binding.validate_mapping(m)


def test_bijection_check():
    m = copy.deepcopy(binding.load_mapping("drug_target_discovery"))
    m["mappings"][1]["tool"] = m["mappings"][0]["tool"]
    with pytest.raises(ValueError):
        binding.validate_mapping(m)


def _drug_payload():
    plan = planning.plan("drug_target_discovery", "scenario_1_breast_cancer").plan
    return binding.bind_plan(plan, binding.load_mapping("drug_target_discovery"),
                             plan_id="plan_test", goal="g")


def test_payload_shape_is_accepted_by_middleware_model():
    payload = _drug_payload()
    assert payload["requires_client_orchestration"] is True
    assert set(payload) == {"requires_client_orchestration", "plan", "metadata", "servers_required"}
    resp = ExecutionPlanResponse.from_plan_response(payload)
    assert resp.plan.total_steps == 8
    assert resp.metadata.execution_id.startswith("exec_plan_test_")


def test_drug_binding_matches_paper_sequence():
    steps = _drug_payload()["plan"]["steps"]
    assert [(s["server"], s["tool"]) for s in steps] == PAPER_SEQUENCE
    assert [s["step"] for s in steps] == list(range(1, 9))


def test_parameter_mapping_and_templates_preserved():
    steps = _drug_payload()["plan"]["steps"]
    assert steps[0]["arguments"] == {"query": "breast cancer"}  # index 1 (size) absent -> omitted
    assert steps[1]["arguments"] == {"diseaseId": "${context.disease_id}"}
    assert steps[0]["output_extractors"]["disease_id"] == "data.search.hits[0].id"


def test_positional_fallback_and_stringification():
    plan = planning.plan("omega_hdq_dna_bacteria_flex_96_channel", "scenario_1_standard").plan
    payload = binding.bind_plan(plan, binding.load_mapping("omega_hdq_dna_bacteria"), plan_id="p")
    mix = payload["plan"]["steps"][1]
    assert mix["tool"] == "mix"
    assert mix["arguments"] == {"arg0": "pip96", "arg1": "3", "arg2": "270", "arg3": "TL_reservoir", "arg4": "A1"}
    assert mix["action"] == ("a_mix", "pip96", "3", "270", "TL_reservoir", "A1")


def test_runtime_params_substituted_but_context_kept():
    mapping = {"domain": "t", "mappings": [{"action": "a_x", "server": "s", "tool": "t",
                                             "parameter_mapping": {"0": "q", "1": "r"}}]}
    payload = binding.bind_plan([("a_x", "${disease} study", "${context.gene}")], mapping,
                                plan_id="p", runtime_params={"disease": "asthma"})
    assert payload["plan"]["steps"][0]["arguments"] == {"q": "asthma study", "r": "${context.gene}"}


def test_unmapped_action_strict_and_lenient():
    mapping = {"domain": "t", "mappings": [{"action": "a_x", "server": "s", "tool": "t"}]}
    plan = [("a_x",), ("a_unknown", "1"), ("a_x",)]
    with pytest.raises(KeyError):
        binding.bind_plan(plan, mapping, plan_id="p")
    payload = binding.bind_plan(plan, mapping, plan_id="p", strict=False)
    assert [s["step"] for s in payload["plan"]["steps"]] == [1, 3]  # original: skipped, numbering kept


@pytest.mark.parametrize("domain", ["bio_opentrons", "omega_hdq_dna_bacteria_flex_96_channel"])
def test_every_opentrons_plan_action_is_bound(domain):
    mapping = binding.load_mapping(planning.DOMAINS[domain])
    for problem in planning.get_problems(domain):
        assert binding.unmapped_actions(planning.plan(domain, problem).plan, mapping) == []


async def test_mock_pipeline_substitution_chain():
    servers = {s for s, _ in PAPER_SEQUENCE} | {"kegg-server"}
    rep = await run_pipeline("drug_target_discovery", "scenario_1_breast_cancer",
                             {s: RecordedBiologyMCPClient(s) for s in servers})
    # The recording replays AlphaFold's 404 (isError) and ChEMBL's empty result
    assert not rep.success
    assert [s.status for s in rep.steps] == ["success"] * 5 + ["failed", "success, missing outputs", "success"]
    assert rep.steps[5].error.startswith("Error fetching AlphaFold structure")
    assert rep.steps[6].output_extractors_missed == ["chembl_target_id", "target_name"]
    assert status_counts(rep) == {"succeeded": 6, "succeeded with missing outputs": 1,
                                  "failed": 1, "skipped": 0, "not run": 0}
    chain = substitution_chain(rep)
    assert chain[0] == "disease_id" and chain[-2:] == ["pmids", "article_count"]
    assert chain.index("disease_id") < chain.index("first_gene") < chain.index("uniprot_accession")
    # ${context.X} templates were replaced before reaching the servers
    for s in rep.steps:
        assert all("${" not in str(v) for v in s.actual_args.values())
    assert rep.steps[1].actual_args["diseaseId"] == rep.steps[0].extracted["disease_id"]
    assert rep.steps[4].actual_args["uniprot_id"] == rep.steps[2].extracted["uniprot_accession"]


async def test_echo_pipeline_pcr_96():
    mapping = binding.load_mapping("bio_opentrons")
    servers = {m["server"] for m in mapping["mappings"]}
    rep = await run_pipeline("bio_opentrons", "scenario_6", {s: EchoMCPClient(s) for s in servers})
    assert rep.success and rep.result["steps_completed"] == 611
