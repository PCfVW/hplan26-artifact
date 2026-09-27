# HTN Planning as a Coordination Layer — Artifact

Artifact for the paper **"HTN Planning as a Coordination Layer for Multi-Server MCP Tool Orchestration"**, Workshop on Hierarchical Planning (HPlan) at ICAPS 2026, Dublin (non-archival).

Eliott Jacopin (RIKEN) · Eric Jacopin (Cosmic AI) · Koichi Takahashi (RIKEN)

> **Paper:** arXiv link — *TODO*
> **Archived:** Zenodo DOI — *TODO*

---

## What this is

The paper describes a three-layer architecture:

- A **planning layer**: a GTPyhop HTN planner produces a plan once.
- A **binding layer**: `mappings/<domain>.json` maps each primitive action to an MCP (server, tool) pair and declares JSON-path output extractors.
- An **execution layer**: an orchestration middleware walks the plan across isolated MCP servers and substitutes `${context.X}` templates with values extracted from earlier steps.

This repository lets a reader reproduce three things:

| | What | Needs |
|---|---|---|
| **(a)** | the planning layer for all five paper domains, with the plan lengths the paper reports | Python only, offline |
| **(b)** | planner → JSON binding → orchestration middleware, end to end, on mock servers, **with no database** | Python only, offline |
| **(c)** | the live drug-target-discovery run against the **eight real Augmented Nature MCP servers** | Python, Node.js, network |

## Artifact map

| Artifact | Where | Paper element |
|---|---|---|
| Five HTN domains (installed from PyPI `gtpyhop-examples`, not vendored) | `orchestrator/src/hplan_orchestrator/planning.py` loads them | §3 planning layer; §4 Setting, Scaling, Coverage |
| Plan-length check, PCR closed form `31 + 6n + 2(⌈n/40⌉ − 1)` | `scripts/run_planning.py`, `orchestrator/tests/test_planning.py` | §4 *Scaling: bio-laboratory PCR* (55 … 611); *Coverage* (Omega HDQ 89–129) |
| Binding-layer mappings + JSON Schema | `mappings/`, `schemas/` | §3 binding layer, Fig. 1 |
| Binding glue: plan + mapping → execution-plan payload (`requires_client_orchestration: true`) | `orchestrator/src/hplan_orchestrator/binding.py`, `clients/planner.py` | §3 *Implementation* (`python_find_plan`, `python_execute_plan`) |
| Orchestration middleware (`extract_json_path`, `${context.X}` substitution) | `orchestrator/src/hplan_orchestrator/orchestration/` | §3 execution layer, Fig. 1 |
| Offline end-to-end run with the substitution chain | `scripts/run_mock.py` | §4 *End-to-end execution* (the chain `disease_id → first_gene → uniprot_accession → … → pmids`) |
| Live stdio client, server pins, setup scripts | `clients/live.py`, `servers/` | §4 *Setting*; Table 1 |
| Live run + ListTools tool count | `scripts/run_live.py` | **Table 1** (6 + 26 + 8 + 33 + 5 + 19 + 27 + 16 = 140 tools); **Table 2** (step sequence) |
| Original log of the paper's three live runs; one re-run | `evidence/` | **Table 2** (35 s / 29 s / 15 s, 8/8 steps) |

## Quickstart

Python ≥ 3.10 is required (the `mcp` SDK needs it). We tested with Python 3.13 on Windows 11.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[test]"                               # add ",live" for (c)
pytest                                                 # 81 tests, offline
```

### (a) Planning layer — offline

```bash
python scripts/run_planning.py
```

The script plans all 15 scenarios of the five domains. It prints each plan length next to the paper's value and exits non-zero on any mismatch. Expected output (abridged):

```
drug_target_discovery                    scenario_1_breast_cancer         8      8  yes    OK
bio_opentrons                            scenario_1                      55     55  yes    OK  (n=4)
bio_opentrons                            scenario_6                     611    611  yes    OK  (n=96)
omega_hdq_dna_bacteria_flex_96_channel   scenario_1_standard            129    129  yes    OK
tnf_cancer_modelling                     scenario_1_multiscale           12     12  no     OK
cross_server                             scenario_2_multi_transfer       15     15  no     OK
15/15 scenarios match the paper
```

The `bound` column says whether the domain has a binding-layer mapping.

### (b) Planner → binding → middleware — offline, no database

```bash
python scripts/run_mock.py          # drug_target_discovery, scenario 1
python scripts/run_mock.py --all    # + PCR (4 and 96 samples) and all three Omega HDQ scenarios
```

For each step, the script prints:

- the server and tool;
- each argument as a template and as it reached the server (e.g. `diseaseId: ${context.disease_id} -> MONDO_0007254`);
- the context variables the step's extractors captured.

The drug-target run **replays responses recorded from the live servers** (`orchestrator/src/hplan_orchestrator/data/`). The extractors and the substitution therefore run on real response shapes. The Opentrons domains use an **echo mock**: it exercises planning, binding (named `parameter_mapping` for PCR, positional `arg0…argN` for Omega HDQ) and middleware sequencing, but it simulates no robot.

### (c) Live run against the eight Augmented Nature servers

This part needs git, **Node.js ≥ 18** and npm. We tested with Node 24.

```bash
pip install -e ".[live]"
servers/setup_servers.sh ~/mcp-servers            # Windows: pwsh servers/setup_servers.ps1 -Target $HOME\mcp-servers
python scripts/run_live.py --servers-root ~/mcp-servers
```

- **Setup.** The setup script clones each server at the commit used for the paper (`servers/servers.json`), then runs `npm install && npm run build`.
- **Servers root.** `run_live.py` takes the root from `--servers-root`. Otherwise it uses `$HPLAN_MCP_SERVERS_ROOT`, and then `~/mcp-servers`.
- **Startup and tool count.** The script spawns the eight servers as stdio subprocesses. It then prints each server's `ListTools` count next to Table 1.
- **The run.** It executes the eight-step breast-cancer plan and prints per-step timings and the substitution chain. Use `--runs 3` to replay the same plan on the same subprocesses, as in Table 2.
- **Queries.** A run issues eight read-only queries to public APIs (OpenTargets, UniProt, Reactome, RCSB PDB, AlphaFold DB, ChEMBL, NCBI E-utilities). No keys are needed.
- **No silent fallback to mocks.** If a server does not start, the script stops and names it.

`evidence/live_run_2026-09-27.log` is such a run: 8/8 steps in 2.8 s, 140 tools. `evidence/README.md` reads it against the paper.

## What differs from the system in the paper — please read

- **The binding step is re-implemented without the database.** In the paper, `python_execute_plan` ran in a private backend. It read the stored plan and the action→tool mapping edges from a graph database.
  - Here, `binding.py` (a short new module) reads the plan from GTPyhop and the mappings from the JSON files the database was populated from. It emits the same payload, field for field: step numbering, stringified parameters, `parameter_mapping`, `${var}` vs `${context.var}` handling, and `servers_required`.
  - The middleware that consumes the payload is the original code, unmodified.
  - The FastAPI backend, the browser plan controller with Server-Sent Events, and the graph database are **not** included.
- **The paper's live runs used that backend, with GTPyhop 1.6.0.** The original log records GTPyhop 1.6.0; the paper's *Implementation* paragraph cites v2.0.1, the version this artifact is tested against.
  - This artifact depends on `gtpyhop>=2.0.1,<3`. The test suite passes under both 2.0.1 and 2.0.2, whose five domains are byte-identical.
  - `evidence/live_runs_2025-12-13.log` is the original record. The runs took place on 2025-12-13; the plan they execute was stored on 2025-12-10.
- **The tool–action correspondence is hand-written.** The three mapping files are hand-written (the paper says so: none of the servers declares an output schema). No ingestion of all 140 tools is involved. The 140 figure is simply what the eight servers advertise via `ListTools`, which `run_live.py` re-counts.
- **TNF cancer modelling and cross-server pick-and-place are planning-layer only**, as the paper's *Coverage* paragraph states. They have no mapping, so they are exercised by (a) only.
- **"8/8 steps" means eight tool calls returned.** The middleware does not inspect tool-level error payloads. In the September 2026 re-run, AlphaFold DB has no model for the current top target (BRCA2, P51587) and returns an error text; ChEMBL returns an empty list for it. Neither value is consumed later in the chain. `evidence/README.md` has the details.
- **The mock differs from the original repository's mock.** The original `MockBiologyMCPClient` returns payloads whose shapes the mapping's extractors do not address, so no `${context.X}` would be substituted. It is replaced here by the recorded-response mock.

## Repository layout

```
orchestrator/src/hplan_orchestrator/
  orchestration/        middleware.py, execution_plan.py      (from mcp-python-ingestion, unmodified)
  utils/progress_bar.py                                        (from mcp-python-ingestion, unmodified)
  planning.py           load + plan the five gtpyhop-examples domains; expected lengths
  binding.py            plan + mapping JSON -> execution-plan payload; schema validation
  runner.py             plan -> bind -> execute, per-step report
  clients/planner.py    in-process python_find_plan / python_execute_plan
  clients/mock.py       recorded-response mock (drug) and echo mock (Opentrons)
  clients/live.py       RealMCPClient (stdio, from mcp-python-ingestion) + configurable server root
  data/                 recorded drug-target responses for the mock
orchestrator/tests/     ported middleware/model tests + planning, binding, consistency tests
mappings/               drug_target_discovery.json, bio_opentrons.json, omega_hdq_dna_bacteria.json
schemas/                action_tool_mapping_schema.json
scripts/                run_planning.py, run_mock.py, run_live.py
servers/                servers.json (pins, licences), mcp_servers.json (launch config), setup_servers.{sh,ps1}
evidence/               live_runs_2025-12-13.log (paper, Table 2), live_run_2026-09-27.log (re-run)
```

## Licensing

Code, mappings and scripts are Apache-2.0 (`LICENSE`); `evidence/` is CC-BY-4.0 (`evidence/LICENSE`). The GTPyhop domains (Clear BSD, © 2021 University of Maryland) and the eight MCP servers are installed from their upstream sources and are not redistributed here. See [LICENSES.md](LICENSES.md), including a note on the servers' licence change of 2025-12-21.

## Citing

See [CITATION.cff](CITATION.cff). Please cite both the paper and the archived artifact DOI.

## Related

- GTPyhop — <https://github.com/PCfVW/GTPyhop> · <https://pypi.org/project/gtpyhop/>
- Augmented Nature MCP servers — <https://github.com/Augmented-Nature>
- Model Context Protocol — <https://modelcontextprotocol.io>
