#!/usr/bin/env python
"""(b) Planner -> JSON binding -> orchestration middleware, offline, no database.

    python scripts/run_mock.py                 # drug_target_discovery, scenario 1
    python scripts/run_mock.py --all           # + bio_opentrons and Omega HDQ (echo mock)

drug_target_discovery replays the responses recorded from the eight live
servers, so the ${context.X} chain (disease_id -> first_gene ->
uniprot_accession -> ... -> pmids) is substituted on realistically shaped data.
The recording includes AlphaFold's 404 (isError) and ChEMBL's empty result, so
this run reports step 6 failed and step 7 succeeded with missing outputs, as the
live run does. Exit status: non-zero if a step of the chain was skipped or not
run (the expected, recorded failure of step 6 does not count), or if an echo
run did not succeed on every step.
bio_opentrons and omega_hdq use an echo mock: they exercise planning, binding
(parameter_mapping or positional arg0..argN) and middleware sequencing, but
simulate no robot.
"""

import argparse
import asyncio
import sys

import _bootstrap  # noqa: F401
from hplan_orchestrator import binding, planning
from hplan_orchestrator.clients.mock import EchoMCPClient, RecordedBiologyMCPClient
from hplan_orchestrator.runner import format_report, run_pipeline, substitution_chain

DRUG_SERVERS = ["opentargets-server", "uniprot-server", "reactome-server", "kegg-server",
                "pdb-server", "alphafold-server", "chembl-server", "pubmed-server"]

# Scenarios run with the echo mock under --all (smallest and largest PCR, all Omega HDQ).
ECHO_RUNS = [("bio_opentrons", "scenario_1"), ("bio_opentrons", "scenario_6"),
             ("omega_hdq_dna_bacteria_flex_96_channel", "scenario_1_standard"),
             ("omega_hdq_dna_bacteria_flex_96_channel", "scenario_2_dry_run"),
             ("omega_hdq_dna_bacteria_flex_96_channel", "scenario_3_manual_mixing")]


async def main_async(args) -> int:
    rc = 0
    print(f"gtpyhop {planning.gtpyhop_version()}\n")
    print("=== drug_target_discovery / scenario_1_breast_cancer (recorded-response mock) ===")
    clients = {s: RecordedBiologyMCPClient(s) for s in DRUG_SERVERS}
    rep = await run_pipeline("drug_target_discovery", "scenario_1_breast_cancer", clients)
    print(format_report(rep))
    print("substitution chain: " + " -> ".join(substitution_chain(rep)))
    res = rep.result
    rc |= bool(res.get("steps_skipped") or res.get("steps_not_run"))

    if args.all:
        for domain, problem in ECHO_RUNS:
            mapping = binding.load_mapping(planning.DOMAINS[domain])
            servers = sorted({m["server"] for m in mapping["mappings"]})
            print(f"\n=== {domain} / {problem} (echo mock) ===")
            rep = await run_pipeline(domain, problem, {s: EchoMCPClient(s) for s in servers})
            print(format_report(rep, show_args=True, max_rows=None if args.verbose else 4))
            per_server = {}
            for s in rep.steps:
                per_server[s.server] = per_server.get(s.server, 0) + 1
            print("steps per server: " + ", ".join(f"{k} {v}" for k, v in sorted(per_server.items())))
            rc |= not (rep.success and len(rep.steps) == rep.plan_length)
    return int(rc)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all", action="store_true", help="also run bio_opentrons and omega_hdq with the echo mock")
    p.add_argument("-v", "--verbose", action="store_true", help="show every step of the echo runs")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
