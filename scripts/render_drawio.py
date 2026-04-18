"""Render a Structurizr DSL workspace to draw.io `.drawio` XML files.

One `.drawio` file per view (L1 system context, L2 container, each L3
component view). Opens in the draw.io desktop/web app and imports cleanly
into Lucidchart via File > Import > .drawio.

Why not just emit Mermaid and rely on the Lucid/draw.io Mermaid support?
  - Mermaid-in-Lucid isn't fully editable (Lucid docs note this).
  - Emitting native shapes gives the user movable, editable boxes.

Layout is simple: grid-pack elements inside their owning boundary (system
for L1, system for L2, container for L3), with a fixed box size and
grid gaps. Users can move things afterward — the goal is "openable and
sensible", not "pretty".
"""

from __future__ import annotations

import argparse
import html
import json
import math
import uuid
from pathlib import Path
from typing import Any, Iterable

from _structurizr import run as structurizr_run

BOX_W = 200
BOX_H = 100
GAP_X = 60
GAP_Y = 60
PAD = 40
BOUNDARY_PAD = 30

# drawio reserves cell IDs "0" (root) and "1" (default layer), so all
# element IDs coming from Structurizr must be namespaced before use.
def _nid(eid: str) -> str:
    return f"n_{eid}"

# C4-ish color palette (Simon Brown's default-ish)
STYLES = {
    "person": (
        "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;"
        "html=1;outlineConnect=0;fillColor=#08427b;strokeColor=#073b6f;"
        "fontColor=#ffffff;"
    ),
    "external_system": (
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#999999;"
        "strokeColor=#6b6b6b;fontColor=#ffffff;fontSize=12;"
    ),
    "software_system": (
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#1168bd;"
        "strokeColor=#0b4884;fontColor=#ffffff;fontSize=12;"
    ),
    "container": (
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#438dd5;"
        "strokeColor=#2e6295;fontColor=#ffffff;fontSize=12;"
    ),
    "component": (
        "rounded=1;whiteSpace=wrap;html=1;fillColor=#85bbf0;"
        "strokeColor=#5d82a8;fontColor=#000000;fontSize=11;"
    ),
    "boundary": (
        "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;"
        "strokeColor=#444444;fontColor=#444444;verticalAlign=top;fontSize=11;"
    ),
    "edge": (
        "endArrow=open;html=1;endFill=0;strokeColor=#707070;fontSize=10;"
        "rounded=0;edgeStyle=orthogonalEdgeStyle;"
    ),
}


def _esc(s: str) -> str:
    """XML-escape for attribute values and text."""
    return html.escape(s or "", quote=True).replace("\n", "&#xa;")


def _h(s: str) -> str:
    """HTML-escape only (for label text that will be XML-escaped once more)."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _label(name: str, kind: str, desc: str | None) -> str:
    bits = [
        f"<b>{_h(name)}</b>",
        f"<font style='font-size: 9px'>[{_h(kind)}]</font>",
    ]
    if desc:
        bits.append(f"<font style='font-size: 9px'>{_h(desc)}</font>")
    return "<br>".join(bits)


def _index_model(workspace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten every element in the model into id -> element metadata."""
    idx: dict[str, dict[str, Any]] = {}
    model = workspace.get("model", {})

    for person in model.get("people", []):
        idx[person["id"]] = {
            "kind": "person",
            "name": person["name"],
            "description": person.get("description"),
            "parent_id": None,
            "tags": person.get("tags", ""),
            "relationships": person.get("relationships", []),
        }
    for system in model.get("softwareSystems", []):
        idx[system["id"]] = {
            "kind": "software_system",
            "name": system["name"],
            "description": system.get("description"),
            "parent_id": None,
            "tags": system.get("tags", ""),
            "relationships": system.get("relationships", []),
        }
        for container in system.get("containers", []):
            idx[container["id"]] = {
                "kind": "container",
                "name": container["name"],
                "description": container.get("description"),
                "technology": container.get("technology"),
                "parent_id": system["id"],
                "tags": container.get("tags", ""),
                "relationships": container.get("relationships", []),
            }
            for comp in container.get("components", []):
                idx[comp["id"]] = {
                    "kind": "component",
                    "name": comp["name"],
                    "description": comp.get("description"),
                    "technology": comp.get("technology"),
                    "parent_id": container["id"],
                    "tags": comp.get("tags", ""),
                    "relationships": comp.get("relationships", []),
                }
    return idx


def _collect_relationships(idx: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Relationships live on their source element; flatten to a single list."""
    rels: list[dict[str, Any]] = []
    for src_id, el in idx.items():
        for r in el.get("relationships", []):
            rels.append(
                {
                    "id": r.get("id") or str(uuid.uuid4()),
                    "source": r.get("sourceId", src_id),
                    "destination": r["destinationId"],
                    "description": r.get("description") or "",
                    "technology": r.get("technology") or "",
                }
            )
    return rels


def _grid(n: int) -> tuple[int, int]:
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = max(1, int(math.ceil(n / cols)))
    return cols, rows


def _layout(elements: list[str], origin_x: int, origin_y: int) -> dict[str, tuple[int, int]]:
    cols, _ = _grid(len(elements))
    pos: dict[str, tuple[int, int]] = {}
    for i, eid in enumerate(elements):
        row, col = divmod(i, cols)
        x = origin_x + col * (BOX_W + GAP_X)
        y = origin_y + row * (BOX_H + GAP_Y)
        pos[eid] = (x, y)
    return pos


def _xml_cell(cid: str, value_html: str, style: str, x: int, y: int, w: int, h: int, parent: str = "1") -> str:
    # value contains HTML markup; XML-escape it so the full string is a valid
    # XML attribute. draw.io then un-escapes it and renders the HTML.
    return (
        f'<mxCell id="{_esc(cid)}" value="{_esc(value_html)}" style="{_esc(style)}" '
        f'vertex="1" parent="{_esc(parent)}">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>'
        "</mxCell>"
    )


def _xml_edge(cid: str, source: str, target: str, label: str) -> str:
    return (
        f'<mxCell id="{_esc(cid)}" value="{_esc(label)}" style="{_esc(STYLES["edge"])}" '
        f'edge="1" parent="1" source="{_esc(source)}" target="{_esc(target)}">'
        '<mxGeometry relative="1" as="geometry"/>'
        "</mxCell>"
    )


def _render_flat(
    view_name: str,
    element_ids: list[str],
    idx: dict[str, dict[str, Any]],
    rels: list[dict[str, Any]],
) -> str:
    """No inner boundary grouping (L1/L2 style)."""
    pos = _layout(element_ids, PAD, PAD)
    cells: list[str] = []
    for eid in element_ids:
        el = idx[eid]
        x, y = pos[eid]
        kind_label = el["kind"].replace("_", " ").title()
        label = _label(el["name"], kind_label, el.get("description"))
        style = STYLES["external_system"] if "External" in el.get("tags", "") else STYLES[el["kind"]]
        cells.append(_xml_cell(_nid(eid), label, style, x, y, BOX_W, BOX_H))

    visible = set(element_ids)
    for r in rels:
        if r["source"] in visible and r["destination"] in visible:
            cells.append(
                _xml_edge(f'e_{r["id"]}', _nid(r["source"]), _nid(r["destination"]), r["description"])
            )
    return _wrap_xml(view_name, cells)


def _render_with_boundary(
    view_name: str,
    boundary_id: str,
    boundary_label: str,
    inside_ids: list[str],
    outside_ids: list[str],
    idx: dict[str, dict[str, Any]],
    rels: list[dict[str, Any]],
) -> str:
    """Container view / component view: inside items grouped in a dashed boundary."""
    cols, rows = _grid(len(inside_ids)) if inside_ids else (1, 1)
    boundary_w = max(BOX_W + BOUNDARY_PAD * 2, cols * BOX_W + (cols - 1) * GAP_X + BOUNDARY_PAD * 2)
    boundary_h = max(BOX_H + BOUNDARY_PAD * 2 + 30, rows * BOX_H + (rows - 1) * GAP_Y + BOUNDARY_PAD * 2 + 30)

    cells: list[str] = []
    # place outside elements in a column to the left
    ox, oy = PAD, PAD
    outside_pos: dict[str, tuple[int, int]] = {}
    for i, eid in enumerate(outside_ids):
        outside_pos[eid] = (ox, oy + i * (BOX_H + GAP_Y))
    outside_block_w = (BOX_W + GAP_X) if outside_ids else 0

    bx = PAD + outside_block_w
    by = PAD
    cells.append(
        _xml_cell(
            f"boundary_{boundary_id}",
            _label(boundary_label, "Boundary", None),
            STYLES["boundary"],
            bx,
            by,
            boundary_w,
            boundary_h,
        )
    )

    inside_pos = _layout(inside_ids, bx + BOUNDARY_PAD, by + BOUNDARY_PAD + 20)

    for eid in outside_ids:
        el = idx[eid]
        x, y = outside_pos[eid]
        style = STYLES["external_system"] if "External" in el.get("tags", "") else STYLES[el["kind"]]
        kind_label = el["kind"].replace("_", " ").title()
        cells.append(_xml_cell(_nid(eid), _label(el["name"], kind_label, el.get("description")), style, x, y, BOX_W, BOX_H))

    for eid in inside_ids:
        el = idx[eid]
        x, y = inside_pos[eid]
        kind_label = el["kind"].replace("_", " ").title()
        cells.append(_xml_cell(_nid(eid), _label(el["name"], kind_label, el.get("description")), STYLES[el["kind"]], x, y, BOX_W, BOX_H))

    visible = set(outside_ids) | set(inside_ids)
    for r in rels:
        if r["source"] in visible and r["destination"] in visible:
            cells.append(_xml_edge(f'e_{r["id"]}', _nid(r["source"]), _nid(r["destination"]), r["description"]))
    return _wrap_xml(view_name, cells)


def _wrap_xml(view_name: str, cells: Iterable[str]) -> str:
    body = "\n        ".join(cells)
    diagram_id = uuid.uuid4().hex[:16]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<mxfile host="app.diagrams.net" agent="ai-software-diagramming" version="24.0.0">\n'
        f'  <diagram id="{diagram_id}" name="{_esc(view_name)}">\n'
        '    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        'pageWidth="1600" pageHeight="1100" math="0" shadow="0">\n'
        '      <root>\n'
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f'        {body}\n'
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )


def render_workspace(workspace: dict[str, Any], out_dir: Path) -> list[Path]:
    idx = _index_model(workspace)
    rels = _collect_relationships(idx)
    views = workspace.get("views", {})
    written: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    for v in views.get("systemContextViews", []):
        eids = [e["id"] for e in v.get("elements", [])]
        xml = _render_flat(v.get("name") or v["key"], eids, idx, rels)
        p = out_dir / f"{v['key']}.drawio"
        p.write_text(xml)
        written.append(p)

    for v in views.get("containerViews", []):
        inside = [e["id"] for e in v.get("elements", []) if idx[e["id"]]["parent_id"] == v.get("softwareSystemId")]
        outside = [e["id"] for e in v.get("elements", []) if idx[e["id"]]["parent_id"] != v.get("softwareSystemId")]
        system = idx.get(str(v.get("softwareSystemId", "")), {}).get("name", "System")
        xml = _render_with_boundary(v.get("name") or v["key"], v["key"], system, inside, outside, idx, rels)
        p = out_dir / f"{v['key']}.drawio"
        p.write_text(xml)
        written.append(p)

    for v in views.get("componentViews", []):
        inside = [e["id"] for e in v.get("elements", []) if idx[e["id"]]["parent_id"] == v.get("containerId")]
        outside = [e["id"] for e in v.get("elements", []) if idx[e["id"]]["parent_id"] != v.get("containerId")]
        container = idx.get(str(v.get("containerId", "")), {}).get("name", "Container")
        xml = _render_with_boundary(v.get("name") or v["key"], v["key"], container, inside, outside, idx, rels)
        p = out_dir / f"{v['key']}.drawio"
        p.write_text(xml)
        written.append(p)

    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default="out/workspace.dsl")
    ap.add_argument("--out", default="out/drawio")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="Auto-confirm structurizr-cli download if missing.",
    )
    args = ap.parse_args()

    ws_path = Path(args.workspace).resolve()
    if not ws_path.exists():
        raise SystemExit(f"workspace not found: {ws_path}")

    tmp = Path(args.out).resolve().parent / ".structurizr_json"
    tmp.mkdir(parents=True, exist_ok=True)
    result = structurizr_run(
        ["export", "-workspace", str(ws_path), "-format", "json", "-output", str(tmp)],
        auto_yes=args.yes,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"structurizr-cli export failed:\n{result.stderr or result.stdout}")

    json_path = tmp / "workspace.json"
    if not json_path.exists():
        raise SystemExit(f"expected JSON not found: {json_path}")
    workspace = json.loads(json_path.read_text())

    out_dir = Path(args.out).resolve()
    written = render_workspace(workspace, out_dir)
    for p in written:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
