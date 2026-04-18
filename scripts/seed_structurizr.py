"""Seed a Structurizr DSL workspace from extract.py output.

Strategy:
  - One softwareSystem named after the repo.
  - One container per top-level Python package (from manifest.json).
  - Components stubbed from each package's immediate subpackages/submodules.
  - Pre-baked views for systemContext (L1), container (L2), and one
    component view (L3) per container.
  - Class-level (L4) lives outside the DSL: keep the pyreverse Mermaid
    files in build/raw/classes/ and link them from the docs section.

The seed is intentionally rough — Claude refines it interactively
via /l4 → /l3 → /l2 → /l1 slash commands.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
    return s or "x"


def detect_components(pkg_dir: Path) -> list[str]:
    if not pkg_dir.is_dir():
        return []
    comps: list[str] = []
    for child in sorted(pkg_dir.iterdir()):
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            comps.append(child.name)
        elif child.suffix == ".py" and child.stem != "__init__":
            comps.append(child.stem)
    return comps[:30]  # cap; refinement will prune


def emit(raw_dir: Path, out_path: Path) -> None:
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    src_root = Path(manifest["source"])
    repo_name = Path(manifest["repo"].rstrip("/")).name.replace(".git", "")
    sys_id = slug(repo_name)

    lines: list[str] = []
    lines.append(f'workspace "{repo_name}" "Reverse-engineered C4 model" {{')
    lines.append("")
    lines.append("    model {")
    lines.append('        user = person "User" "Primary actor (refine in L1)"')
    lines.append(
        f'        {sys_id} = softwareSystem "{repo_name}" '
        f'"Reverse-engineered from {manifest["repo"]}" {{'
    )

    container_ids: list[str] = []
    for pkg in manifest["packages"]:
        cid = slug(pkg) + "_pkg"
        if cid == sys_id:  # extra safety
            cid = cid + "_c"
        container_ids.append(cid)
        lines.append(
            f'            {cid} = container "{pkg}" '
            f'"Python package" "Python" {{'
        )
        # find package on disk
        pkg_path = next(
            (p for p in src_root.rglob(pkg) if p.is_dir() and (p / "__init__.py").exists()),
            None,
        )
        for comp in detect_components(pkg_path) if pkg_path else []:
            lines.append(
                f'                {cid}_{slug(comp)} = component "{comp}" '
                f'"Module/subpackage" "Python"'
            )
        lines.append("            }")
    lines.append("        }")
    lines.append("        user -> " + sys_id + ' "Uses"')
    lines.append("    }")
    lines.append("")
    lines.append("    views {")
    lines.append(f"        systemContext {sys_id} L1 {{")
    lines.append("            include *")
    lines.append("            autolayout lr")
    lines.append("        }")
    lines.append(f"        container {sys_id} L2 {{")
    lines.append("            include *")
    lines.append("            autolayout lr")
    lines.append("        }")
    for cid in container_ids:
        lines.append(f"        component {cid} L3_{cid} {{")
        lines.append("            include *")
        lines.append("            autolayout lr")
        lines.append("        }")
        # theme intentionally omitted: validator fetches over HTTP and breaks
        # offline. Add `theme default` later if you want styling.
    lines.append("    }")
    lines.append("}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_dir", help="Directory produced by extract.py")
    ap.add_argument("--out", default="out/workspace.dsl")
    args = ap.parse_args()
    emit(Path(args.raw_dir).resolve(), Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
