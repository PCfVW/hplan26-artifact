"""Planning layer: load the five MCP-orchestration domains shipped with GTPyhop
and plan their scenarios.

The domains are not vendored. They are imported from the ``gtpyhop-examples``
distribution, which the ``gtpyhop`` meta-package (>=2.0.1,<3) installs at the
same version. They live under the package directory ``mcp-orchestration``,
whose hyphen makes it unreachable by a plain ``import`` statement, hence
``importlib.import_module``.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

EXAMPLES_PACKAGE = "gtpyhop.examples.mcp-orchestration"

# Domain package name in gtpyhop-examples -> mapping file in mappings/ (None =
# planning layer only, as stated in the paper's Coverage paragraph).
DOMAINS: Dict[str, Optional[str]] = {
    "drug_target_discovery": "drug_target_discovery",
    "bio_opentrons": "bio_opentrons",
    "omega_hdq_dna_bacteria_flex_96_channel": "omega_hdq_dna_bacteria",
    "tnf_cancer_modelling": None,
    "cross_server": None,
}


def pcr_plan_length(n_samples: int) -> int:
    """Closed form reported in the paper for bio_opentrons: 31 + 6n + 2(ceil(n/40) - 1)."""
    return 31 + 6 * n_samples + 2 * (math.ceil(n_samples / 40) - 1)


# Expected plan lengths, as reported in the paper (Sec. 4).
PCR_SAMPLES = {"scenario_1": 4, "scenario_2": 8, "scenario_3": 16,
               "scenario_4": 32, "scenario_5": 48, "scenario_6": 96}

EXPECTED_LENGTHS: Dict[str, Dict[str, int]] = {
    "drug_target_discovery": {
        "scenario_1_breast_cancer": 8,
        "scenario_2_alzheimers": 8,
        "scenario_3_diabetes": 8,
    },
    "bio_opentrons": {name: pcr_plan_length(n) for name, n in PCR_SAMPLES.items()},
    "omega_hdq_dna_bacteria_flex_96_channel": {
        "scenario_1_standard": 129,
        "scenario_2_dry_run": 91,
        "scenario_3_manual_mixing": 89,
    },
    "tnf_cancer_modelling": {"scenario_1_multiscale": 12},
    "cross_server": {
        "scenario_1_pick_and_place": 9,
        "scenario_2_multi_transfer": 15,
    },
}


@dataclass
class PlanResult:
    domain: str
    problem: str
    description: str
    tasks: List[Tuple]
    plan: Optional[List[Tuple]]

    @property
    def length(self) -> Optional[int]:
        return None if self.plan is None else len(self.plan)


def gtpyhop_version() -> str:
    from importlib.metadata import version
    return version("gtpyhop")


def load_domain(domain: str) -> Any:
    """Import a domain package from gtpyhop-examples, silencing GTPyhop's banner."""
    if domain not in DOMAINS:
        raise KeyError(f"Unknown domain {domain!r}; expected one of {list(DOMAINS)}")
    with contextlib.redirect_stdout(io.StringIO()):
        return importlib.import_module(f"{EXAMPLES_PACKAGE}.{domain}")


def get_problems(domain: str) -> Dict[str, Tuple[Any, List[Tuple], str]]:
    """Return {problem_name: (initial_state, tasks, description)}."""
    return load_domain(domain).get_problems()


def plan(domain: str, problem: str) -> PlanResult:
    """Plan one scenario with a GTPyhop PlannerSession (verbose=0)."""
    with contextlib.redirect_stdout(io.StringIO()):
        import gtpyhop  # first import prints a banner

    module = load_domain(domain)
    problems = module.get_problems()
    if problem not in problems:
        raise KeyError(f"Unknown problem {problem!r} for {domain}; expected one of {list(problems)}")
    state, tasks, description = problems[problem]
    with contextlib.redirect_stdout(io.StringIO()):
        with gtpyhop.PlannerSession(domain=module.the_domain, verbose=0) as session:
            result = session.find_plan(state, tasks)
    plan_ = None if result.plan is None or result.plan is False else list(result.plan)
    return PlanResult(domain, problem, description, list(tasks), plan_)


def plan_all() -> List[PlanResult]:
    return [plan(d, p) for d in DOMAINS for p in get_problems(d)]
