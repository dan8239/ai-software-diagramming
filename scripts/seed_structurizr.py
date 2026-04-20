"""Seed a Structurizr DSL workspace from the multi-language manifest.

For each detected unit (Go module / npm package / Python package) we create
one Structurizr container with a per-language `technology` tag. Components
are stubbed from the unit's subdirs/modules. Cross-unit imports become
container-to-container relationships.

External dependencies from `imports/*.json` are NOT materialized into L1
software systems here — that's the job of /l1 (the LLM refines them into
the right external systems: DBs, APIs, queues, etc.). We just surface a
commented list per unit to guide the refinement.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TECH_LABEL = {
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "go": "Go",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_") or "x"


def _sys_id(repo_name: str, units: list[dict]) -> str:
    base = _slug(repo_name)
    taken = {u["id"] for u in units}
    if base in taken:
        return base + "_sys"
    return base


def emit(raw_dir: Path, out_path: Path) -> None:
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    units = manifest["units"]
    repo_name = Path(manifest["repo"].rstrip("/")).name.replace(".git", "")
    sys_id = _sys_id(repo_name, units)

    out: list[str] = []
    out.append(f'workspace "{repo_name}" "Reverse-engineered C4 model" {{')
    out.append("")
    out.append("    model {")
    out.append('        user = person "User" "Primary actor (refine in L1)"')
    out.append(
        f'        {sys_id} = softwareSystem "{repo_name}" '
        f'"Reverse-engineered from {manifest["repo"]}" {{'
    )

    # containers
    for u in units:
        tech = TECH_LABEL.get(u["language"], u["language"])
        desc = f"{u['language']} unit at {u['path']} ({u['files']} files)"
        out.append(
            f'            {u["id"]} = container "{u["package_name"]}" '
            f'"{desc}" "{tech}" {{'
        )
        for comp in u.get("component_dirs", []):
            cid = f'{u["id"]}_{_slug(comp)}'
            out.append(
                f'                {cid} = component "{comp}" '
                f'"Module/subpackage" "{tech}"'
            )
        # hint: external deps to be promoted to L1 softwareSystems
        externals = u.get("external_sample", [])
        if externals:
            out.append(
                "                // externals to consider for L1: "
                + ", ".join(externals[:8])
            )
        out.append("            }")
    out.append("        }")

    # cross-unit relationships
    seen_rel: set[tuple[str, str]] = set()
    for u in units:
        for dest in u.get("cross_unit_to", []):
            edge = (u["id"], dest)
            if edge in seen_rel or u["id"] == dest:
                continue
            seen_rel.add(edge)
            out.append(f'        {u["id"]} -> {dest} "imports from"')

    out.append(f'        user -> {sys_id} "Uses"')
    out.append("    }")
    out.append("")
    out.append("    views {")
    out.append(f"        systemContext {sys_id} L1 {{")
    out.append("            include *")
    out.append("            autolayout lr")
    out.append("        }")
    out.append(f"        container {sys_id} L2 {{")
    out.append("            include *")
    out.append("            autolayout lr")
    out.append("        }")
    for u in units:
        if u.get("component_dirs"):
            out.append(f'        component {u["id"]} L3_{u["id"]} {{')
            out.append("            include *")
            out.append("            autolayout lr")
            out.append("        }")
    # theme intentionally omitted (validator fetches it over HTTP).
    out.append("    }")
    out.append("}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out) + "\n")
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
