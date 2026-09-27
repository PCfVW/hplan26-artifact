# Evidence

Two logs of live runs of the eight-step drug-target-discovery plan (scenario 1, breast cancer) against the eight Augmented Nature MCP servers.

| File | What it is | Produced by |
|---|---|---|
| `live_runs_2025-12-13.log` | **The original record of the paper's three live runs (Table 2).** Excerpt of the backend log, sanitised (see header). | The private backend (FastAPI, browser plan controller, graph-database plan store), **not included in this artifact**, with GTPyhop 1.6.0 (see note below) |
| `live_run_2026-09-27.log` | One re-run, made while preparing this artifact, of the same plan through this repository's pipeline: GTPyhop → `mappings/drug_target_discovery.json` → `OrchestrationMiddleware` → eight stdio servers built by `servers/setup_servers.ps1` at the pinned commits. | `python scripts/run_live.py --log evidence/live_run_2026-09-27.log` with gtpyhop 2.0.1 and Python 3.13 on Windows 11 |

## Reading the original log against Table 2

The log lines carry wall-clock times with a resolution of one second, so the durations below are ±1 s. The paper's figures came from the Server-Sent Events stream, which has millisecond resolution.

| Run | `POST /api/execute/start` | `Execution completed: 8 steps` | Duration from the log | Table 2 |
|---|---|---|---|---|
| 1 (cold) | 20:05:30 | 20:06:05 | 35 s | 35 s |
| 2 (warm) | 20:07:32 | 20:08:02 | 30 s | 29 s |
| 3 (warm) | 20:08:50 | 20:09:06 | 16 s | 15 s |

All three runs execute the same eight (server, tool) steps in the same order. Step 7 (`search_by_uniprot` on ChEMBL) accounts for most of the wall-clock time: 30 s, 27 s and 13 s. This agrees with the caption of Table 2.

The log has no date. The file was created at 19:24 and last written at 20:09:06 CET on **2025-12-13**, which is when the runs took place. The plan key `plan_20251210_161447_…` records when the plan was stored, on 2025-12-10.

The log's `Imported GTPyhop version 1.6.0` banner is the version the backend process imported. The paper's Implementation paragraph cites GTPyhop v1.9.7, the maintained release at the time of writing. This artifact uses gtpyhop ≥ 2.0.1.

## Reading the re-run

- **Same plan structure.** The re-run has the same eight (server, tool) steps in the same order, the same `${context.X}` chain, 8/8 steps completed, and a wall-clock time of 2.8 s. The `ListTools` counts match Table 1 exactly (140 tools in total).
- **Data may differ.** Intermediate values depend on the current state of the upstream databases, and the original log did not record them. In September 2026, OpenTargets resolves "breast cancer" to `MONDO_0007254` and ranks BRCA2 as its top target.
- **Step 6 (AlphaFold) returns an error.** AlphaFold DB has no model for BRCA2 / P51587, so the server returns the text `Error fetching AlphaFold structure: Request failed with status code 404`. The middleware counts any returned tool result as a completed step. This is also how "8/8" is counted in Table 2. The re-run log therefore flags the step with a note.
- **Step 7 (ChEMBL) returns nothing.** ChEMBL has no target for P51587. It returns an empty list, so its extractors capture nothing.
- Neither `alphafold_model` nor the ChEMBL variables is consumed by a later step, so the chain is unaffected.

## Licence

The files in this directory are data and are licensed under CC-BY-4.0 (`LICENSE`).
