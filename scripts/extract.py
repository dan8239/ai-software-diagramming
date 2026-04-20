"""Walk a Python/TypeScript/Go (mono)repo and emit a unit+import manifest.

A "unit" is a directory that declares its own identity with one of:
  - go.mod        -> Go module
  - package.json  -> npm/yarn/pnpm package (TS or JS)
  - pyproject.toml / setup.py / setup.cfg   -> Python distribution
  - or a dir containing __init__.py at repo root / depth 1 (legacy Python)

For each unit we scan source files for imports using language-specific
regexes, classify them as internal (same unit), cross-unit (another
detected unit in the repo), or external (third-party), and write a
consolidated manifest.json.

No external tooling required; stdlib only. Good enough for C4-scale
architecture discovery — not an AST-perfect analyzer.

Output layout:
  build/raw/
    manifest.json   - units + summary stats
    imports/<unit>.json   - detailed per-unit import graph
    source/          - shallow git clone of the target repo
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# shared helpers

SKIP_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "vendor", "target",
    "dist", "build", "out", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".idea", ".vscode",
    "testdata", "fixtures",
}

SOURCE_EXTS = {
    "python": {".py"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "go": {".go"},
}


def _iter_files(root: Path, exts: set[str]) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if os.path.splitext(name)[1] in exts:
                out.append(Path(dirpath) / name)
    return out


# ---------------------------------------------------------------------------
# unit detection

@dataclass
class Unit:
    id: str
    language: str
    path: str              # relative to repo root
    package_name: str      # import-path / npm name / python dist name
    component_dirs: list[str] = field(default_factory=list)
    files: int = 0
    deployable: bool = False   # has Dockerfile/main/entrypoint/start-script


def _read_go_mod(path: Path) -> str | None:
    try:
        text = path.read_text()
    except Exception:
        return None
    m = re.search(r"^\s*module\s+(\S+)", text, re.M)
    return m.group(1) if m else None


def _read_package_json(path: Path) -> tuple[str | None, bool]:
    """Returns (name, is_typescript)."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None, False
    name = data.get("name")
    # TS if tsconfig.json exists next to package.json OR any .ts files in subtree
    is_ts = (path.parent / "tsconfig.json").exists() or bool(
        _iter_files(path.parent, SOURCE_EXTS["typescript"])
    )
    return name, is_ts


def _read_pyproject_name(path: Path) -> str | None:
    try:
        text = path.read_text()
    except Exception:
        return None
    m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return m.group(1) if m else None


def _derive_python_package_name(unit_dir: Path) -> str | None:
    """If pyproject didn't give us a name, guess from top-level package dir."""
    for child in unit_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            return child.name
    return None


def _unique_id(base: str, taken: set[str]) -> str:
    cand = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_") or "unit"
    if cand not in taken:
        return cand
    i = 2
    while f"{cand}_{i}" in taken:
        i += 1
    return f"{cand}_{i}"


def detect_units(src: Path) -> list[Unit]:
    units: list[Unit] = []
    ids_taken: set[str] = set()
    unit_roots: set[Path] = set()

    # walk once; a dir may hold multiple manifest files but only yields one unit
    # (priority: go.mod > package.json > pyproject.toml > setup.py)
    candidates: list[tuple[Path, str]] = []  # (dir, language)
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        d = Path(dirpath)
        if "go.mod" in filenames:
            candidates.append((d, "go"))
        elif "package.json" in filenames:
            candidates.append((d, "js_or_ts"))
        elif "pyproject.toml" in filenames or "setup.py" in filenames or "setup.cfg" in filenames:
            candidates.append((d, "python"))

    # strip nested units inside a parent unit root (e.g. a subpackage with its
    # own pyproject is its own unit; but a test fixture dir that happens to
    # contain a package.json inside node_modules is already filtered by
    # SKIP_DIRS). Here we just keep all candidates — the walk already skipped
    # node_modules/vendor/etc.
    for d, tag in sorted(candidates, key=lambda c: len(c[0].parts)):
        if tag == "go":
            name = _read_go_mod(d / "go.mod") or d.name
            language = "go"
        elif tag == "js_or_ts":
            name, is_ts = _read_package_json(d / "package.json")
            name = name or d.name
            language = "typescript" if is_ts else "javascript"
        else:
            name = None
            for fname in ("pyproject.toml", "setup.cfg", "setup.py"):
                if (d / fname).exists():
                    name = _read_pyproject_name(d / fname) if fname != "setup.py" else None
                    break
            name = name or _derive_python_package_name(d) or d.name
            language = "python"

        uid = _unique_id(name.split("/")[-1], ids_taken)
        ids_taken.add(uid)
        rel = str(d.relative_to(src))
        components = _detect_components(d, language, name.split("/")[-1])
        files = len(_iter_files(d, SOURCE_EXTS.get(language, set()) | (
            SOURCE_EXTS["javascript"] if language == "typescript" else set()
        )))
        deployable = _is_deployable(d, language, name)
        units.append(
            Unit(
                id=uid,
                language=language,
                path=rel if rel != "." else ".",
                package_name=name,
                component_dirs=components,
                files=files,
                deployable=deployable,
            )
        )
        unit_roots.add(d)

    # Fallback for Python repos that don't have pyproject/setup — detect
    # top-level dirs with __init__.py (matches the old behavior for
    # psf/requests-style layouts).
    if not any(u.language == "python" for u in units):
        for p in sorted(src.iterdir()):
            if not p.is_dir() or p.name in SKIP_DIRS or p.name.startswith("."):
                continue
            if (p / "__init__.py").exists():
                _add_python_fallback_unit(src, p, units, ids_taken)
            elif p.name == "src":
                for child in p.iterdir():
                    if child.is_dir() and (child / "__init__.py").exists():
                        _add_python_fallback_unit(src, child, units, ids_taken)

    return units


def _is_deployable(unit_dir: Path, language: str, package_name: str) -> bool:
    """Heuristic: does this unit run as its own process?"""
    # Dockerfile anywhere in the unit (not just root) is a strong signal
    for df in unit_dir.rglob("Dockerfile"):
        if not any(part in SKIP_DIRS for part in df.relative_to(unit_dir).parts):
            return True

    if language == "go":
        if (unit_dir / "main.go").exists():
            return True
        cmd = unit_dir / "cmd"
        if cmd.is_dir():
            for sub in cmd.iterdir():
                if sub.is_dir() and (sub / "main.go").exists():
                    return True
        return False

    if language == "python":
        short = package_name.split("/")[-1]
        candidates = [
            unit_dir / short / "__main__.py",
            unit_dir / "src" / short / "__main__.py",
        ]
        if any(c.exists() for c in candidates):
            return True
        pyproject = unit_dir / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text()
                if re.search(r'^\s*\[project\.(gui-)?scripts\]', text, re.M):
                    return True
                if re.search(r'^\s*\[project\.entry-points\.', text, re.M):
                    return True
            except Exception:
                pass
        setup_cfg = unit_dir / "setup.cfg"
        if setup_cfg.exists():
            try:
                if "console_scripts" in setup_cfg.read_text():
                    return True
            except Exception:
                pass
        return False

    if language in {"typescript", "javascript"}:
        pkg_json = unit_dir / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
            except Exception:
                return False
            if data.get("bin"):
                return True
            scripts = data.get("scripts") or {}
            for key in ("start", "dev", "serve", "preview"):
                if key in scripts:
                    return True
        return False

    return False


def _add_python_fallback_unit(src: Path, pkg_dir: Path, units: list[Unit], taken: set[str]) -> None:
    uid = _unique_id(pkg_dir.name, taken)
    taken.add(uid)
    rel = str(pkg_dir.parent.relative_to(src)) or "."
    units.append(
        Unit(
            id=uid,
            language="python",
            path=rel,
            package_name=pkg_dir.name,
            component_dirs=_detect_components(pkg_dir.parent, "python", pkg_dir.name),
            files=len(_iter_files(pkg_dir, SOURCE_EXTS["python"])),
            deployable=_is_deployable(pkg_dir.parent, "python", pkg_dir.name),
        )
    )


def _detect_components(unit_dir: Path, language: str, package_name: str | None = None) -> list[str]:
    """Pick per-language subunits that become L3 components."""
    if language == "python":
        # Find the real package dir. Preference order:
        #   1. <unit>/<package_name>/__init__.py          (flat, name matches)
        #   2. <unit>/src/<package_name>/__init__.py      (src, name matches)
        #   3. any <unit>/<X>/__init__.py where X is not "tests"/"docs"/etc.
        #   4. any <unit>/src/<X>/__init__.py
        base: Path | None = None
        candidates: list[Path] = []
        if package_name:
            candidates += [
                unit_dir / package_name,
                unit_dir / "src" / package_name,
            ]
        for c in candidates:
            if c.is_dir() and (c / "__init__.py").exists():
                base = c
                break
        non_pkg_names = {"tests", "test", "docs", "examples", "scripts", "bin"}
        if base is None:
            for parent in (unit_dir, unit_dir / "src"):
                if not parent.is_dir():
                    continue
                for c in sorted(parent.iterdir()):
                    if c.name.startswith((".", "_")) or c.name in SKIP_DIRS or c.name in non_pkg_names:
                        continue
                    if c.is_dir() and (c / "__init__.py").exists():
                        base = c
                        break
                if base:
                    break
        if base is None:
            base = unit_dir
        items: list[str] = []
        for child in sorted(base.iterdir()):
            if child.name.startswith((".", "_")):
                continue
            if child.is_dir() and (child / "__init__.py").exists():
                items.append(child.name)
            elif child.suffix == ".py" and child.stem != "__init__":
                items.append(child.stem)
        return items[:40]
    if language in {"typescript", "javascript"}:
        src = unit_dir / "src"
        base = src if src.is_dir() else unit_dir
        items = []
        for child in sorted(base.iterdir()):
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if child.is_dir():
                items.append(child.name)
            elif child.suffix in SOURCE_EXTS["typescript"] | SOURCE_EXTS["javascript"]:
                items.append(child.stem)
        return items[:40]
    if language == "go":
        items = []
        for child in sorted(unit_dir.iterdir()):
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if child.is_dir():
                # include nested Go packages (at least one .go file anywhere inside)
                if _iter_files(child, SOURCE_EXTS["go"]):
                    items.append(child.name)
        if not items and _iter_files(unit_dir, SOURCE_EXTS["go"]):
            items.append(unit_dir.name)
        return items[:40]
    return []


# ---------------------------------------------------------------------------
# per-language import scanners

PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+(\S+)\s+import\s+\S|import\s+([\w.]+))", re.M)
TS_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*(?:import\s+(?:[\s\S]*?)\s+from\s+|import\s+|export\s+[\s\S]*?\s+from\s+)['"]([^'"]+)['"]"""
)
TS_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
GO_IMPORT_SINGLE_RE = re.compile(r'^\s*import\s+(?:\w+\s+)?"([^"]+)"', re.M)
GO_IMPORT_BLOCK_RE = re.compile(r"^\s*import\s*\(\s*([\s\S]*?)\n\s*\)", re.M)
GO_IMPORT_LINE_RE = re.compile(r'^\s*(?:\w+\s+)?"([^"]+)"', re.M)


def _scan_python(unit: Unit, root: Path) -> list[str]:
    imports: set[str] = set()
    for f in _iter_files(root / unit.path, SOURCE_EXTS["python"]):
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for m in PY_IMPORT_RE.finditer(text):
            mod = m.group(1) or m.group(2)
            if mod:
                imports.add(mod)
    return sorted(imports)


def _scan_ts(unit: Unit, root: Path) -> list[str]:
    imports: set[str] = set()
    exts = SOURCE_EXTS["typescript"] | SOURCE_EXTS["javascript"]
    for f in _iter_files(root / unit.path, exts):
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for m in TS_IMPORT_RE.finditer(text):
            imports.add(m.group(1))
        for m in TS_REQUIRE_RE.finditer(text):
            imports.add(m.group(1))
    return sorted(imports)


def _scan_go(unit: Unit, root: Path) -> list[str]:
    imports: set[str] = set()
    for f in _iter_files(root / unit.path, SOURCE_EXTS["go"]):
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for m in GO_IMPORT_SINGLE_RE.finditer(text):
            imports.add(m.group(1))
        for block_match in GO_IMPORT_BLOCK_RE.finditer(text):
            for m in GO_IMPORT_LINE_RE.finditer(block_match.group(1)):
                imports.add(m.group(1))
    return sorted(imports)


SCANNERS = {
    "python": _scan_python,
    "typescript": _scan_ts,
    "javascript": _scan_ts,
    "go": _scan_go,
}


# ---------------------------------------------------------------------------
# classification: internal vs cross-unit vs external

# Complete Python stdlib module list (Python 3.10+). Falls back to a small
# hand-curated set on older interpreters.
try:
    PY_STDLIB_HINTS: set[str] = set(sys.stdlib_module_names)  # type: ignore[attr-defined]
except AttributeError:
    PY_STDLIB_HINTS = {
        "sys", "os", "re", "json", "math", "typing", "pathlib", "subprocess",
        "dataclasses", "collections", "itertools", "functools", "argparse",
        "asyncio", "logging", "io", "time", "datetime", "enum", "uuid",
        "urllib", "http", "email", "hashlib", "secrets", "unittest",
        "contextlib", "warnings", "copy", "inspect", "abc", "types",
    }
# Python 2 stdlib names occasionally found via compat shims.
PY_STDLIB_HINTS |= {
    "BaseHTTPServer", "SimpleHTTPServer", "StringIO", "cStringIO",
    "dummy_threading", "urlparse", "urllib2", "httplib", "Queue",
    "ConfigParser", "cPickle", "xmlrpclib",
}

GO_STDLIB_HINTS = {
    "context", "fmt", "os", "io", "net", "net/http", "encoding", "encoding/json",
    "database/sql", "time", "errors", "log", "strings", "strconv",
    "bytes", "bufio", "sync", "sort", "path", "path/filepath",
    "regexp", "crypto", "crypto/rand", "testing",
}


def _classify(
    language: str,
    imports: list[str],
    unit: Unit,
    by_pkg: dict[str, str],   # package_name -> unit_id
) -> dict[str, list[str]]:
    internal: list[str] = []
    cross: list[str] = []  # cross-unit -> stores destination unit_ids
    external: list[str] = []

    for imp in imports:
        if language == "python":
            # relative imports ("from .x import y") stay within the unit
            if imp.startswith("."):
                internal.append(imp)
                continue
            head = imp.split(".")[0]
            # same unit?
            if imp == unit.package_name or imp.startswith(unit.package_name + "."):
                internal.append(imp)
            elif head in by_pkg and by_pkg[head] != unit.id:
                cross.append(by_pkg[head])
            elif head in PY_STDLIB_HINTS or any(
                imp.startswith(s + ".") for s in PY_STDLIB_HINTS
            ):
                pass  # stdlib, ignore
            else:
                external.append(imp)

        elif language in {"typescript", "javascript"}:
            if imp.startswith(".") or imp.startswith("/"):
                internal.append(imp)
            elif imp in by_pkg and by_pkg[imp] != unit.id:
                cross.append(by_pkg[imp])
            elif any(imp == name or imp.startswith(name + "/") for name in by_pkg if by_pkg[name] != unit.id):
                for name, uid in by_pkg.items():
                    if uid != unit.id and (imp == name or imp.startswith(name + "/")):
                        cross.append(uid)
                        break
            else:
                external.append(imp)

        elif language == "go":
            if imp == unit.package_name or imp.startswith(unit.package_name + "/"):
                internal.append(imp)
            elif imp in by_pkg and by_pkg[imp] != unit.id:
                cross.append(by_pkg[imp])
            elif any(
                imp == name or imp.startswith(name + "/")
                for name, uid in by_pkg.items() if uid != unit.id
            ):
                for name, uid in by_pkg.items():
                    if uid != unit.id and (imp == name or imp.startswith(name + "/")):
                        cross.append(uid)
                        break
            elif imp in GO_STDLIB_HINTS or "." not in imp.split("/")[0]:
                pass  # heuristic: stdlib paths have no domain in first segment
            else:
                external.append(imp)

    return {
        "internal": sorted(set(internal)),
        "cross_unit": sorted(set(cross)),
        "external": sorted(set(external)),
    }


# ---------------------------------------------------------------------------
# clone + orchestrate

def clone(repo: str, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["git", "clone", "--depth", "1", repo, str(dest)],
        check=False, capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise SystemExit(f"git clone failed:\n{res.stderr}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", help="GitHub URL or local path")
    ap.add_argument("--out", default="build/raw")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    src_dir = out / "source"

    parsed = urlparse(args.repo)
    if parsed.scheme in {"http", "https", "git", "ssh"}:
        src = clone(args.repo, src_dir)
    else:
        src = Path(args.repo).resolve()
        if not src.exists():
            raise SystemExit(f"path not found: {src}")
        # mirror local into build/raw/source so downstream paths are stable
        if src != src_dir:
            if src_dir.exists():
                shutil.rmtree(src_dir)
            shutil.copytree(src, src_dir, symlinks=False, ignore=shutil.ignore_patterns(*SKIP_DIRS))
            src = src_dir

    units = detect_units(src)
    if not units:
        raise SystemExit("no units detected (no go.mod / package.json / pyproject.toml)")

    by_pkg = {u.package_name: u.id for u in units}

    imports_dir = out / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "repo": args.repo,
        "source": str(src),
        "languages": sorted({u.language for u in units}),
        "units": [],
    }

    for u in units:
        scanner = SCANNERS.get(u.language)
        raw_imports = scanner(u, src) if scanner else []
        classified = _classify(u.language, raw_imports, u, by_pkg)
        (imports_dir / f"{u.id}.json").write_text(json.dumps({
            "unit": asdict(u),
            "imports": classified,
            "raw": raw_imports,
        }, indent=2))
        entry = asdict(u)
        entry["cross_unit_to"] = classified["cross_unit"]
        entry["external_count"] = len(classified["external"])
        entry["external_sample"] = classified["external"][:15]
        manifest["units"].append(entry)

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(
        {"languages": manifest["languages"], "units": [(u["id"], u["language"], u["package_name"]) for u in manifest["units"]]},
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
