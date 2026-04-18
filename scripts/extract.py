"""Clone a Python repo and extract raw architecture artifacts.

Outputs into <out>/:
  classes.mmd / classes.puml      - pyreverse class diagram (L4 source)
  packages.mmd / packages.puml    - pyreverse package diagram (L3 hint)
  modules.svg + modules.json      - pydeps module dependency graph
  source/                         - shallow clone of the repo (read-only ref)
  manifest.json                   - top-level packages + entrypoints detected

The downstream seeder + Claude refinement steps consume these files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


VENV_BIN = Path(sys.executable).parent


def _resolve(tool: str) -> str:
    """Find a CLI tool, preferring the active venv."""
    candidate = VENV_BIN / tool
    if candidate.exists():
        return str(candidate)
    found = shutil.which(tool)
    if found:
        return found
    raise SystemExit(
        f"{tool} not found. Install with: pip install -r requirements.txt"
    )


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)


def clone(repo: str, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    res = run(["git", "clone", "--depth", "1", repo, str(dest)])
    if res.returncode != 0:
        raise SystemExit(f"git clone failed:\n{res.stderr}")
    return dest


def detect_packages(src: Path) -> list[Path]:
    """Top-level importable packages: dirs containing __init__.py at depth ≤2."""
    pkgs: list[Path] = []
    skip = {".git", "tests", "test", "docs", "examples", "build", "dist", ".venv"}
    for p in sorted(src.iterdir()):
        if not p.is_dir() or p.name in skip or p.name.startswith("."):
            continue
        if (p / "__init__.py").exists():
            pkgs.append(p)
        else:
            # one level deeper (src-layout)
            for child in p.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    pkgs.append(child)
    return pkgs


def pyreverse(pkg: Path, out_dir: Path, fmt: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = run(
        [
            _resolve("pyreverse"),
            "-o", fmt,
            "-p", pkg.name,
            "-d", str(out_dir),
            "--colorized",
            str(pkg),
        ]
    )
    if res.returncode != 0:
        # pyreverse warns a lot but still emits useful output; surface stderr
        print(res.stderr, file=sys.stderr)


def pydeps(pkg: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pydeps_bin = _resolve("pydeps")
    svg = out_dir / f"{pkg.name}.modules.svg"
    res = run(
        [
            pydeps_bin,
            str(pkg),
            "--noshow",
            "--max-bacon", "2",
            "--cluster",
            "-o", str(svg),
        ]
    )
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
    # JSON deps for the seeder
    json_path = out_dir / f"{pkg.name}.modules.json"
    res = run([pydeps_bin, str(pkg), "--show-deps", "--no-output"])
    if res.returncode == 0 and res.stdout.strip():
        json_path.write_text(res.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", help="GitHub URL or local path")
    ap.add_argument("--out", default="build/raw", help="Output directory")
    ap.add_argument(
        "--format",
        default="mmd",
        choices=["mmd", "puml", "dot"],
        help="pyreverse output format",
    )
    args = ap.parse_args()

    out = Path(args.out).resolve()
    src_dir = out / "source"

    # Local path or URL?
    parsed = urlparse(args.repo)
    if parsed.scheme in {"http", "https", "git", "ssh"}:
        src = clone(args.repo, src_dir)
    else:
        src = Path(args.repo).resolve()
        if not src.exists():
            raise SystemExit(f"path not found: {src}")

    pkgs = detect_packages(src)
    if not pkgs:
        raise SystemExit("no top-level Python packages detected")
    print(f"detected packages: {[p.name for p in pkgs]}", file=sys.stderr)

    cls_dir = out / "classes"
    mod_dir = out / "modules"
    for pkg in pkgs:
        pyreverse(pkg, cls_dir, args.format)
        pydeps(pkg, mod_dir)

    manifest = {
        "repo": args.repo,
        "source": str(src),
        "packages": [p.name for p in pkgs],
        "format": args.format,
        "outputs": {
            "classes": sorted(str(p.relative_to(out)) for p in cls_dir.glob("*")),
            "modules": sorted(str(p.relative_to(out)) for p in mod_dir.glob("*")),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
