---
description: Publish refined views to Lucidchart via Lucid MCP
argument-hint: [L1|L2|L3|L4|all]
---

Publish refined view(s) to Lucidchart.

Target: `$ARGUMENTS` (one of L1, L2, L3, L4, or "all"; default = all).

1. Check Lucid MCP is connected (tools prefixed `mcp__lucid__`). If not, tell
   the user to run `/mcp` and authenticate.
2. For each requested level, read the corresponding Mermaid file from
   `out/views/`:
   - L1 → `L1.mmd`
   - L2 → `L2.mmd`
   - L3 → `L3_*.mmd` (one per container)
   - L4 → `L4_*.mmd` (one per container)
3. For L1/L2: prefer creating native Lucid shapes via the MCP — these are
   small and the user wants them editable.
4. For L3/L4: ask the user first whether they want native shapes (slower) or
   embedded Mermaid (faster, less editable).
5. Confirm the target Lucid document/folder name with the user before any
   `create` call. Never push silently.
6. After publishing, return the Lucid document URL(s).

If Lucid MCP fails, offer the **draw.io MCP** as a fallback and produce
`.drawio` files in `out/` instead.
