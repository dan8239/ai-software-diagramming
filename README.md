# ai-software-diagramming

Reverse-engineer C4 architecture diagrams (L4 → L1) from a Python GitHub repo,
output editable diagrams in **Lucidchart** via the official Lucid MCP server.

## Pipeline

```
GitHub repo
   │
   ▼ scripts/extract.py
build/raw/   ← pyreverse classes.mmd + packages.mmd, pydeps modules.json
   │
   ▼ scripts/seed_structurizr.py
out/workspace.dsl   ← seed Structurizr DSL (containers/components stubbed)
   │
   ▼ Claude Code (interactive: /l4 → /l3 → /l2 → /l1)
out/workspace.dsl   ← refined model with L1–L4 views
   │
   ▼ structurizr-cli export -format mermaid
out/views/*.mmd
   │
   ▼ scripts/render_drawio.py   (default — offline, no auth)
out/drawio/*.drawio          ← openable in draw.io / importable into Lucid
   │
   ▼ optional: Lucid MCP / draw.io MCP / paste Mermaid into Lucid
Lucidchart document (editable)
```

## Quick start

```bash
pip install -r requirements.txt
python scripts/extract.py https://github.com/psf/requests --out build/raw
python scripts/seed_structurizr.py build/raw --out out/workspace.dsl
python scripts/render_drawio.py --yes    # writes out/drawio/*.drawio

# then open the .drawio files in draw.io or import into Lucid,
# OR open this directory in Claude Code and run:
#   /l4   # refine class-level
#   /l3   # cluster into components
#   /l2   # group into containers
#   /l1   # define system context + actors
#   /publish drawio   # regenerate .drawio after refinement (default)
#   /publish lucid    # push via Lucid MCP instead (requires OAuth)
```

**First run of `render_drawio.py`** auto-downloads Structurizr CLI into
`.tools/`. Prompts before downloading unless `--yes` is passed, or set
`STRUCTURIZR_CLI=/path/to/structurizr.sh` to point at your own install.

## Why this stack

| Layer            | Tool                          | Why                                                                 |
|------------------|-------------------------------|---------------------------------------------------------------------|
| Code extraction  | `pyreverse` + `pydeps`        | Standard for Python; outputs Mermaid/PlantUML/JSON                  |
| Model            | Structurizr DSL               | Single model → all 4 C4 levels; created by C4's author              |
| Refinement       | Claude Code (this project)    | LLM clusters raw graph into meaningful components/containers         |
| Render (default) | `render_drawio.py`            | Offline `.drawio` XML — opens in draw.io, imports into Lucid         |
| Render (live)    | Lucid MCP (`mcp.lucid.app`)   | Native editable shapes in Lucidchart; OAuth                          |
| Render (fallback)| draw.io MCP (jgraph official) | Opens the `.drawio` in a live draw.io app session                    |

## MCP configuration

`.mcp.json` is checked in and configures Lucid + draw.io. On first use Claude
Code will prompt you to OAuth into Lucid. The draw.io server runs locally via
`npx`.

## Status

Scaffold + extractor + seeder + slash commands. End-to-end tested on `psf/requests`.
