#!/usr/bin/env python
"""(c) Live run: drug_target_discovery, scenario 1 (breast cancer), against the
eight Augmented Nature MCP servers over stdio.

    python scripts/run_live.py --servers-root ~/mcp-servers [--runs 3] [--log evidence/run.log]

Needs `pip install -e ".[live]"`, Node.js, and the servers built with
servers/setup_servers.{sh,ps1}. Issues 8 read-only queries per run to public
biology APIs (OpenTargets, UniProt, Reactome, RCSB PDB, AlphaFold DB, ChEMBL,
NCBI E-utilities); KEGG is connected, as in the paper, but not called by this
plan. No API keys are needed. The tool surface (Table 1) is also listed via
MCP ListTools, which each server answers locally. There is NO silent fallback to mocks: if a
server cannot be started the script stops and says which one.

Each step is reported as success, success with missing outputs (an output
extractor found no value), failed (the call raised, or the tool returned
isError / success: false) or skipped (an argument needs a ${context.X} that no
earlier step captured). The exit status is 1 unless every step succeeded.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import _bootstrap  # noqa: F401
from hplan_orchestrator import planning
from hplan_orchestrator.clients.live import (
    RealMCPClient, load_server_config, resolve_servers_root, SERVERS_ROOT_ENV)
from hplan_orchestrator.runner import format_report, run_pipeline, substitution_chain

DOMAIN, PROBLEM = "drug_target_discovery", "scenario_1_breast_cancer"
PAPER_TOOLS = {"opentargets-server": 6, "uniprot-server": 26, "reactome-server": 8, "kegg-server": 33,
               "pdb-server": 5, "alphafold-server": 19, "chembl-server": 27, "pubmed-server": 16}


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


async def main_async(args) -> int:
    try:
        import mcp  # noqa: F401
    except ImportError:
        print('ERROR: the MCP Python SDK is not installed; run: pip install -e ".[live]"')
        return 2
    root = resolve_servers_root(args.servers_root)
    config = load_server_config(root)
    missing = [n for n, c in config.items() if not Path(c["args"][0]).is_file()]
    print(f"servers root: <SERVERS_ROOT> ({len(config)} servers configured)")
    if missing:
        print(f"ERROR: build/index.js not found for: {', '.join(missing)}. "
              f"Run servers/setup_servers.sh (or .ps1), or pass --servers-root / set {SERVERS_ROOT_ENV}.")
        return 2

    clients = {n: RealMCPClient(n, c.get("command", "node"), c["args"], env=c.get("env"), timeout=45.0)
               for n, c in config.items()}
    t0 = time.perf_counter()
    ok = await asyncio.gather(*(c.connect() for c in clients.values()))
    print(f"connected {sum(ok)}/{len(ok)} stdio servers in {time.perf_counter() - t0:.1f} s")
    failed = [n for n, good in zip(clients, ok) if not good]
    try:
        if failed:
            for n in failed:
                print(f"ERROR: could not connect to {n}: {clients[n]._connection_error}")
            return 3

        # Tool surface (paper, Table 1): ListTools is answered locally by each
        # server, no upstream API is called.
        tool_lists = await asyncio.gather(*(c.list_tools() for c in clients.values()))
        print("\ntools advertised via ListTools (paper, Table 1):")
        for (name, _), tools in zip(clients.items(), tool_lists):
            print(f"  {name:<20} {len(tools):>3}  (paper: {PAPER_TOOLS[name]})")
        total = sum(len(t) for t in tool_lists)
        print(f"  {'total':<20} {total:>3}  (paper: {sum(PAPER_TOOLS.values())})")

        rc = 0
        for i in range(1, args.runs + 1):
            print(f"\n=== run {i}/{args.runs} ({'cold: just spawned' if i == 1 else 'warm: reused'}) ===")
            rep = await run_pipeline(DOMAIN, PROBLEM, clients, timeout_per_step=45.0)
            print(format_report(rep))
            print("substitution chain: " + " -> ".join(substitution_chain(rep)))
            if args.dump_responses:
                Path(args.dump_responses).write_text(json.dumps(
                    [{"server": s.server, "tool": s.tool, "result": r.get("result")}
                     for s, r in zip(rep.steps, rep.result.get("step_results", []))],
                    indent=1, default=str), encoding="utf-8")
            rc = rc or (0 if rep.success else 1)
        return rc
    finally:
        await asyncio.gather(*(c.disconnect() for c in clients.values()), return_exceptions=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--servers-root", help=f"directory holding the 8 *-MCP-Server checkouts "
                   f"(default: ${SERVERS_ROOT_ENV} or ~/mcp-servers)")
    p.add_argument("--runs", type=int, default=1, help="replays of the same plan on the same subprocesses")
    p.add_argument("--log", help="also write the console output to this file")
    p.add_argument("--dump-responses", help=argparse.SUPPRESS)  # developer aid: raw step results as JSON
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
    log_file = open(args.log, "w", encoding="utf-8") if args.log else None
    if log_file:
        sys.stdout = Tee(sys.__stdout__, log_file)
    try:
        print(f"run_live.py  {datetime.now(timezone.utc).isoformat(timespec='seconds')}  "
              f"python {platform.python_version()}  gtpyhop {planning.gtpyhop_version()}  "
              f"{DOMAIN}/{PROBLEM}")
        return asyncio.run(main_async(args))
    finally:
        if log_file:
            sys.stdout = sys.__stdout__
            log_file.close()


if __name__ == "__main__":
    sys.exit(main())
