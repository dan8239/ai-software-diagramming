"""Seed a Structurizr DSL workspace from the multi-language manifest.

High level:
  - One softwareSystem for the whole repo.
  - One container per *kept* unit. A unit is kept if it is deployable
    (has Dockerfile / main / __main__ / npm start-script), or if it is a
    non-deployable library with zero consumers, or with >1 consumers
    (shared library — kept with a "Shared Library" tag).
  - Non-deployable libraries with exactly one consumer are **collapsed**:
    their components become components of the consumer container, and
    their outbound cross-unit edges are rewritten to originate from the
    consumer. This keeps big monorepos legible by default.
  - L2 views are partitioned by top-level directory (services/, packages/,
    libs/, etc.) and a single L2_all view shows the full picture.
  - L3 views are emitted per kept container.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
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


def _plan_collapse(units: list[dict]) -> tuple[dict[str, str], set[str]]:
    """Return (collapse_map, shared_lib_ids).

    collapse_map: {library_unit_id -> consumer_unit_id} for pure libraries
    with exactly one cross-unit consumer.
    shared_lib_ids: non-deployable libraries with >1 consumers; kept as
    own containers but tagged "Shared Library".
    """
    consumers: dict[str, set[str]] = defaultdict(set)
    for u in units:
        for dest in u.get("cross_unit_to", []):
            if dest != u["id"]:
                consumers[dest].add(u["id"])

    collapse: dict[str, str] = {}
    shared: set[str] = set()
    for u in units:
        if u.get("deployable"):
            continue
        cons = consumers.get(u["id"], set())
        if len(cons) == 1:
            collapse[u["id"]] = next(iter(cons))
        elif len(cons) > 1:
            shared.add(u["id"])
        # 0 consumers: keep as its own container (could be a standalone tool)
    return collapse, shared


def _group_by_top_dir(units: list[dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for u in units:
        path = u.get("path", "")
        top = path.split("/", 1)[0] if path and path != "." else "root"
        # normalize to a DSL-safe identifier
        groups[_slug(top) or "root"].append(u["id"])
    return groups


def emit(raw_dir: Path, out_path: Path) -> None:
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    units: list[dict] = manifest["units"]
    units_by_id = {u["id"]: u for u in units}
    repo_name = Path(manifest["repo"].rstrip("/")).name.replace(".git", "")
    sys_id = _sys_id(repo_name, units)

    collapse, shared_libs = _plan_collapse(units)
    kept_unit_ids = [u["id"] for u in units if u["id"] not in collapse]
    kept_units = [units_by_id[uid] for uid in kept_unit_ids]

    # collapsed_into[consumer_id] = [library_unit_id, ...]
    collapsed_into: dict[str, list[str]] = defaultdict(list)
    for lib, consumer in collapse.items():
        collapsed_into[consumer].append(lib)

    # Rewrite cross-unit edges: skip edges where dest is collapsed
    # (the consumer IS the library now). Redirect edges from a collapsed
    # library to originate from its consumer.
    edges: list[tuple[str, str]] = []
    for u in units:
        src_id = collapse.get(u["id"], u["id"])
        for dest in u.get("cross_unit_to", []):
            if dest == u["id"]:
                continue
            dst_id = collapse.get(dest, dest)
            if src_id == dst_id:
                continue
            edges.append((src_id, dst_id))
    edges = sorted(set(edges))

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
    for u in kept_units:
        tech = TECH_LABEL.get(u["language"], u["language"])
        kind = "Shared Library" if u["id"] in shared_libs else ("Service" if u["deployable"] else "Library")
        desc = f"{u['language']} unit at {u['path']} ({u['files']} files, {kind})"
        tags = f'"{kind}"'
        out.append(
            f'            {u["id"]} = container "{u["package_name"]}" '
            f'"{desc}" "{tech}" {{'
        )
        out.append(f"                tags {tags}")
        # components from the unit itself
        for comp in u.get("component_dirs", []):
            cid = f'{u["id"]}_{_slug(comp)}'
            out.append(
                f'                {cid} = component "{comp}" '
                f'"Module/subpackage" "{tech}"'
            )
        # components from any collapsed libraries folded into this container
        for lib_id in collapsed_into.get(u["id"], []):
            lib = units_by_id[lib_id]
            lib_tech = TECH_LABEL.get(lib["language"], lib["language"])
            if lib.get("component_dirs"):
                for comp in lib["component_dirs"]:
                    cid = f'{lib_id}_{_slug(comp)}'
                    label = f'{lib["package_name"]}/{comp}'
                    out.append(
                        f'                {cid} = component "{label}" '
                        f'"Merged from {lib["package_name"]} library" "{lib_tech}"'
                    )
            else:
                cid = f'{lib_id}'
                out.append(
                    f'                {cid} = component "{lib["package_name"]}" '
                    f'"Merged from library (no subcomponents)" "{lib_tech}"'
                )
        externals = u.get("external_sample", [])
        if externals:
            out.append(
                "                // externals to consider for L1: "
                + ", ".join(externals[:8])
            )
        out.append("            }")
    out.append("        }")

    for src_id, dst_id in edges:
        out.append(f'        {src_id} -> {dst_id} "imports from"')
    out.append(f'        user -> {sys_id} "Uses"')
    out.append("    }")
    out.append("")
    out.append("    views {")
    out.append(f"        systemContext {sys_id} L1 {{")
    out.append("            include *")
    out.append("            autolayout lr")
    out.append("        }")
    # full L2
    out.append(f"        container {sys_id} L2_all {{")
    out.append('            description "All containers (unpartitioned)"')
    out.append("            include *")
    out.append("            autolayout lr")
    out.append("        }")
    # per-group L2 views, only if we'd gain anything by splitting
    groups = _group_by_top_dir(kept_units)
    multi_group = len(groups) > 1 and len(kept_units) > 3
    if multi_group:
        for group, ids in sorted(groups.items()):
            out.append(f"        container {sys_id} L2_{group} {{")
            out.append(f'            description "Containers in {group}/"')
            for cid in ids:
                out.append(f"            include {cid}")
            # also show their immediate cross-unit neighbours for context
            neighbours: set[str] = set()
            for cid in ids:
                for a, b in edges:
                    if a == cid and b not in ids:
                        neighbours.add(b)
                    elif b == cid and a not in ids:
                        neighbours.add(a)
            for nid in sorted(neighbours):
                out.append(f"            include {nid}")
            out.append("            autolayout lr")
            out.append("        }")
    for u in kept_units:
        # emit L3 only if there's at least one component to show
        has_comps = bool(u.get("component_dirs")) or any(
            units_by_id[lid].get("component_dirs") for lid in collapsed_into.get(u["id"], [])
        )
        if has_comps:
            out.append(f'        component {u["id"]} L3_{u["id"]} {{')
            out.append("            include *")
            out.append("            autolayout lr")
            out.append("        }")
    out.append("    }")
    out.append("}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out) + "\n")

    # terse summary so the user can see what collapsed
    print(f"wrote {out_path}")
    print(f"  kept {len(kept_units)} containers; collapsed {len(collapse)} libraries")
    for lib, consumer in collapse.items():
        print(f"    {lib} -> {consumer}")
    if shared_libs:
        print(f"  shared libraries kept as own containers: {sorted(shared_libs)}")
    if multi_group:
        print(f"  L2 partitioned by top-level dir: {sorted(groups)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_dir", help="Directory produced by extract.py")
    ap.add_argument("--out", default="out/workspace.dsl")
    args = ap.parse_args()
    emit(Path(args.raw_dir).resolve(), Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
