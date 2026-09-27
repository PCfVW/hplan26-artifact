"""Planning layer: plan lengths of all five domains match the paper (NEW)."""

import pytest

from hplan_orchestrator import planning

CASES = [(d, p, n) for d, probs in planning.EXPECTED_LENGTHS.items() for p, n in probs.items()]


def test_gtpyhop_version_in_supported_range():
    major, minor, patch = (int(x) for x in planning.gtpyhop_version().split(".")[:3])
    assert (2, 0, 1) <= (major, minor, patch) < (3, 0, 0)


@pytest.mark.parametrize("domain,problem,expected", CASES, ids=[f"{d}-{p}" for d, p, _ in CASES])
def test_plan_length_matches_paper(domain, problem, expected):
    assert planning.plan(domain, problem).length == expected


def test_every_shipped_scenario_is_covered():
    for domain in planning.DOMAINS:
        assert set(planning.get_problems(domain)) == set(planning.EXPECTED_LENGTHS[domain])


@pytest.mark.parametrize("n,length", [(4, 55), (8, 79), (16, 127), (32, 223), (48, 321), (96, 611)])
def test_pcr_closed_form(n, length):
    assert planning.pcr_plan_length(n) == length


def test_drug_plan_carries_context_templates():
    plan = planning.plan("drug_target_discovery", "scenario_1_breast_cancer").plan
    assert plan[0] == ("a_search_disease", "breast cancer")
    assert plan[1] == ("a_get_disease_targets", "${context.disease_id}")
    assert plan[2] == ("a_get_protein_by_gene", "${context.first_gene}")
    assert [a[0] for a in plan] == [
        "a_search_disease", "a_get_disease_targets", "a_get_protein_by_gene",
        "a_find_pathways_by_gene", "a_get_pdb_structures", "a_get_alphafold_structure",
        "a_get_compounds_for_target", "a_search_literature"]


def test_drug_domain_size_matches_paper():
    """Sec. 4: ten primitive actions (eight used in the plan) and six methods."""
    dom = planning.load_domain("drug_target_discovery").the_domain
    assert len(dom._action_dict) == 10
    # GTPyhop registers two built-in verification methods (_verify_g, _verify_mg) in every domain.
    user_methods = [m for k, ms in dom._task_method_dict.items() if not k.startswith("_") for m in ms]
    assert len(user_methods) == 6
    used = {a[0] for a in planning.plan("drug_target_discovery", "scenario_1_breast_cancer").plan}
    assert len(used) == 8
