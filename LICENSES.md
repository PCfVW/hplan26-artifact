# Licensing

This repository is a research artifact assembled from parts with different provenance. It carries **two** licences. A third applies to a dependency that is installed, not included. The `LICENSE` files govern: the root `LICENSE` covers everything except `evidence/`, which has its own.

| Directory | Contents | Licence | Why |
|---|---|---|---|
| `orchestrator/` | the `hplan_orchestrator` package and its tests: the orchestration middleware and execution-plan models (from mcp-python-ingestion v0.29.2, unmodified), the live stdio client (`RealMCPClient`, unmodified), and the new binding glue, planning wrapper, mock clients and runner | **Apache-2.0** (root `LICENSE`) | The copied code is Apache-2.0, © 2025 Eric Jacopin. The new code is original work by the authors, under the same licence. |
| `mappings/`, `schemas/` | the three binding-layer mappings and their JSON Schema (from mcp-python-ingestion, unmodified) | **Apache-2.0** (root `LICENSE`) | Same provenance as the middleware. |
| `scripts/`, `servers/` | the three entry-point scripts; the server launch configuration, pin list and setup scripts | **Apache-2.0** (root `LICENSE`) | Original work by the authors. `servers/` contains **no server code** (see below). |
| `evidence/` | the original log of the paper's live runs and one re-run | **CC-BY-4.0** (`evidence/LICENSE`) | Research *data*. CC-BY-4.0 is the conventional choice for data and keeps attribution. |

`NOTICE` lists which files come from mcp-python-ingestion and what, if anything, was changed in each.

## Not included, and why

- **The five HTN domains.** They are not vendored. They are installed from PyPI as part of `gtpyhop` (a meta-package that pulls `gtpyhop-core` and `gtpyhop-examples` at the same version), under **The Clear BSD License**, © 2021 University of Maryland. If you redistribute them, retain that copyright notice as the licence requires.
- **The eight Augmented Nature MCP servers.** They are not vendored. `servers/setup_servers.{sh,ps1}` clones each at the commit used for the paper. `servers/servers.json` records the licence status of each:
  - at the pinned commits, six repositories carry an MIT `LICENSE` file;
  - KEGG and PubMed have no `LICENSE` file, and their `package.json` declares `"MIT"`;
  - on **2025-12-21**, after every pinned commit, upstream replaced the licence of all eight repositories with a custom licence. It permits personal, non-commercial use only and prohibits redistribution and modification without permission.

  This is one more reason not to redistribute them here. Users fetch them from the upstream repositories themselves.
- **The paper's backend** (FastAPI service, browser plan controller, graph-database store). It is not part of this artifact; see the README.

## Attribution

If you use this artifact, cite the paper and the archived DOI; see [CITATION.cff](CITATION.cff).
