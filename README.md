# ai-software-diagramming

Reverse-engineer C4 architecture diagrams (L1 System Context → L2 Container →
L3 Component) from a **Python / TypeScript / Go (mono)repo** and output
editable diagrams as `.drawio` files by default, or publish into Lucidchart
via the official Lucid MCP server.

**L4 (Code)** is deliberately skipped — class-level detail is noise at the
architecture-review granularity most teams want.

## Pipeline

```
GitHub repo (or local path)
   │
   ▼ scripts/extract.py
build/raw/
   ├── manifest.json        # detected units + summary
   └── imports/<unit>.json  # internal / cross-unit / external imports per unit
   │
   ▼ scripts/seed_structurizr.py
out/workspace.dsl           # seed Structurizr DSL (one container per unit)
   │
   ▼ Claude Code (interactive): /l3 → /l2 → /l1
out/workspace.dsl           # refined model
   │
   ▼ scripts/render_drawio.py   (default — offline, no auth)
out/drawio/*.drawio         # open in draw.io / import into Lucid
   │
   ▼ optional: Lucid MCP / draw.io MCP / paste Mermaid into Lucid
Lucidchart document (editable)
```

## Unit detection

A "unit" is a directory that declares its own identity:

| Manifest         | Unit type         | Name                           |
| ---------------- | ----------------- | ------------------------------ |
| `go.mod`         | Go module         | `module` directive             |
| `package.json`   | npm/TS package    | `"name"` field                 |
| `pyproject.toml` | Python dist       | `[project].name`               |
| `setup.py`/`.cfg`| Python dist       | dir name (fallback)            |

Each unit becomes one container in the seeded Structurizr DSL. Cross-unit
imports (`@acme/shared` from `@acme/web`, or `common.log` from `worker`, or
`github.com/acme/mono/pkg/x` from `github.com/acme/mono/svc/y`) become
container-to-container relationships.

## Quick start

```bash
pip install -r requirements.txt        # no runtime deps; stdlib-only
python scripts/extract.py https://github.com/your/repo --out build/raw
python scripts/seed_structurizr.py build/raw --out out/workspace.dsl
python scripts/render_drawio.py --yes  # writes out/drawio/*.drawio

# open the .drawio files in draw.io, or in Claude Code run:
#   /l3           # cluster components per container
#   /l2           # collapse library-units into deployable containers
#   /l1           # add external systems + personas
#   /publish drawio    # regenerate .drawio (default)
#   /publish lucid     # push via Lucid MCP (requires OAuth)
```

First run of `render_drawio.py` auto-downloads Structurizr CLI into `.tools/`
(prompts unless `--yes` is passed, or set `STRUCTURIZR_CLI=/path/to/structurizr.sh`).

## Why this stack

| Layer            | Tool                          | Why                                                                |
| ---------------- | ----------------------------- | ------------------------------------------------------------------ |
| Code extraction  | Stdlib regex scanners         | Handles py/ts/go uniformly; no pyreverse/madge/goda to install     |
| Model            | Structurizr DSL               | Single model → all C4 levels; created by C4's author               |
| Refinement       | Claude Code (this project)    | LLM clusters raw graph into meaningful components/containers       |
| Render (default) | `render_drawio.py`            | Offline `.drawio` XML — opens in draw.io, imports into Lucid       |
| Render (live)    | Lucid MCP (`mcp.lucid.app`)   | Native editable shapes in Lucidchart; OAuth                        |
| Render (fallback)| draw.io MCP (jgraph official) | Opens the `.drawio` in a live draw.io app session                  |

## Fixture

`tests/fixtures/mixed/` is a tiny Go + Python + TypeScript monorepo (5 units,
2 cross-unit edges) used to exercise the full pipeline without network.

```bash
python scripts/extract.py tests/fixtures/mixed --out build/raw
python scripts/seed_structurizr.py build/raw
python scripts/render_drawio.py --yes
```

## MCP configuration

`.mcp.json` is checked in and configures Lucid + draw.io MCP servers.
On first use Claude Code prompts you to OAuth into Lucid. The draw.io
server runs locally via `npx`.

## Status

End-to-end pipeline tested on `psf/requests` (Python-only) and the mixed
fixture. `.drawio` output validated as well-formed XML with correct
vertex/edge counts at every level.
