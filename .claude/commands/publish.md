---
description: Render refined views to .drawio files (default) or publish to Lucid via MCP
argument-hint: [drawio|lucid|mermaid] [L1|L2|L3|L4|all]
---

Publish refined view(s).

Arguments in `$ARGUMENTS` (both optional, order-insensitive):
- target: `drawio` (default), `lucid`, or `mermaid`
- level: `L1`, `L2`, `L3`, `L4`, or `all` (default)

### drawio (default — fully offline-testable)

```bash
python scripts/render_drawio.py --yes
```

Outputs `out/drawio/<viewKey>.drawio`. Open with:
- draw.io desktop: `File > Open`
- web: https://app.diagrams.net/ → `Open Existing Diagram`
- Lucid: `File > Import > draw.io` (Lucid converts .drawio natively)

If the draw.io **MCP** is connected (look for `mcp__drawio__*` tools), you can
also call `mcp__drawio__open_drawio_xml` with the file contents to open it in
a live draw.io app instance.

### lucid

1. Verify Lucid MCP is connected (tools prefixed `mcp__lucid__`). If not,
   tell the user to run `/mcp` and authenticate.
2. For each requested level, read the corresponding Mermaid file from
   `out/views/structurizr-<Lx>.mmd` (render with
   `scripts/_structurizr.py` export -format mermaid if missing).
3. For L1/L2: prefer creating native Lucid shapes via MCP.
4. For L3/L4: ask the user first — native shapes (editable, slower) or
   rendered Mermaid (fast, less editable).
5. Confirm the target Lucid document/folder name before any create call.
   Never push silently. Return the Lucid document URL(s).

### mermaid

Emits the Mermaid `.mmd` files from the DSL — copy-paste into Lucid (Mermaid
code-as-diagram) or any Markdown renderer.

```bash
# invoked via the structurizr helper so it downloads the CLI on first use
python -c "from scripts._structurizr import run; import sys; sys.exit(run(['export','-workspace','out/workspace.dsl','-format','mermaid','-output','out/views'], auto_yes=True).returncode)"
```

## Fallback flow

drawio → lucid (manual import) → mermaid (paste) — in that order of
editability/fidelity. If any step fails, fall through to the next.
