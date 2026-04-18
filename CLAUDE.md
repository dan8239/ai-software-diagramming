# Project: ai-software-diagramming

You reverse-engineer C4 architecture diagrams (L4 → L1) from a Python GitHub
repo and publish them as editable Lucidchart documents via the Lucid MCP server.

## Workflow

The user drives this with slash commands. Order is **bottom-up**: L4 → L1.

1. **Extract** (already run before the session, usually):
   ```
   python scripts/extract.py <repo-url> --out build/raw
   python scripts/seed_structurizr.py build/raw --out out/workspace.dsl
   ```
   Inputs to read:
   - `build/raw/manifest.json` — packages + file inventory
   - `build/raw/classes/*.mmd` — pyreverse class diagrams (L4 source-of-truth)
   - `build/raw/modules/*.json` — pydeps module graph (L3/L2 hint)
   - `build/raw/source/` — read-only clone of the target repo

2. **L4 — Code (`/l4`)**: For each container, pick the 1–3 most architecturally
   important classes (entrypoints, base classes, public API). Write a Mermaid
   `classDiagram` per container into `out/views/L4_<container>.mmd`. Trim
   pyreverse output rather than dumping it wholesale — humans want signal.

3. **L3 — Component (`/l3`)**: For each container in `out/workspace.dsl`,
   confirm/refine the components by reading the package source. Group by
   *responsibility*, not by file. Replace the seeded `component "<file>"`
   stubs. Add `<componentA> -> <componentB> "verb-phrase"` relationships
   based on actual import edges from `build/raw/modules/*.json`.

4. **L2 — Container (`/l2`)**: Read `pyproject.toml`, `setup.py`,
   `Dockerfile`, `docker-compose.yml`, GitHub workflows, and obvious
   entrypoints (`__main__.py`, CLI scripts) in `build/raw/source/`. Decide:
   what runs as a separate process/deployable? Common answers: CLI, library,
   web server, worker, scheduled job, DB. Edit containers in
   `out/workspace.dsl` accordingly — the seed treats every package as a
   container, which is almost always wrong.

5. **L1 — System Context (`/l1`)**: Add external systems (databases, APIs,
   queues, third-party services) by grepping for `requests.`, `httpx.`, SQL
   drivers, message-queue libs in the source. Add personas (user, admin,
   operator) based on auth/permission code.

## Output rules

- **Source of truth**: `out/workspace.dsl` (Structurizr DSL). One model, all
  views.
- **Class-level (L4)** lives outside the DSL as `out/views/L4_*.mmd`
  (Structurizr DSL doesn't model fields/methods).
- After each level, render a preview to Mermaid:
  ```bash
  # if structurizr-cli is available locally:
  structurizr-cli export -workspace out/workspace.dsl -format mermaid -output out/views
  ```
  If not installed, ask the user before installing it. Mermaid output is the
  intermediate format the Lucid MCP consumes.

## Publishing

The default publisher is **offline `.drawio` file generation** — it needs no
OAuth, produces editable files, and Lucid imports `.drawio` natively.

```bash
python scripts/render_drawio.py --yes   # out/drawio/*.drawio
```

`/publish` accepts `drawio` (default), `lucid`, or `mermaid`:

- **drawio**: writes `out/drawio/<viewKey>.drawio`. Open in draw.io desktop/
  web, or import into Lucid via `File > Import > draw.io`.
- **lucid**: requires Lucid MCP (`mcp__lucid__*` tools). Confirm target doc
  name with the user; default to native shapes for L1/L2, ask for L3/L4.
- **mermaid**: emits `out/views/structurizr-<Lx>.mmd` for paste-into-Lucid
  or Markdown embedding.

For L4 class diagrams (Structurizr doesn't model them), publish
`out/views/L4_*.mmd` as Mermaid — Lucid and draw.io both render Mermaid
class diagrams directly.

Never push silently to a hosted tool — always confirm the target document
with the user before calling a `create` MCP tool.

## Quality bar

- Every diagram should fit on one screen. If a view has >25 elements, split it
  or push detail down a level.
- Every relationship must have a verb-phrase label ("publishes to", "reads
  from", "authenticates via"), never blank or "uses".
- Component names should describe **responsibility**, not file path
  ("Session Manager", not "sessions.py").

## Don'ts

- Don't dump raw pyreverse output as the final L4. It's the *source*, not the
  product.
- Don't invent components, relationships, or external systems that aren't
  visible in the source. If unsure, ask the user.
- Don't push to Lucid silently — confirm the view name and target document
  first.
