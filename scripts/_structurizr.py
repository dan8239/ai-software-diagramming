"""Locate or install the Structurizr CLI.

Checked locations, in order:
  1. $STRUCTURIZR_CLI (env var pointing at structurizr.sh or structurizr.bat)
  2. `structurizr-cli` on PATH
  3. `.tools/structurizr-cli/structurizr.sh` under the repo
  4. Download the latest release zip from GitHub into .tools/ and extract

Downloading requires network access and prompts the user first unless
--yes is passed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / ".tools"
CLI_DIR = TOOLS_DIR / "structurizr-cli"
CLI_SCRIPT = CLI_DIR / "structurizr.sh"
RELEASE_URL = "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.zip"


def _from_env() -> Path | None:
    p = os.environ.get("STRUCTURIZR_CLI")
    return Path(p) if p and Path(p).exists() else None


def _from_path() -> Path | None:
    p = shutil.which("structurizr-cli") or shutil.which("structurizr")
    return Path(p) if p else None


def _from_tools() -> Path | None:
    return CLI_SCRIPT if CLI_SCRIPT.exists() else None


def _download(auto_yes: bool = False) -> Path:
    if not auto_yes and sys.stdin.isatty():
        ans = input(
            f"Structurizr CLI not found. Download latest release to {CLI_DIR}? [y/N] "
        ).strip().lower()
        if ans not in {"y", "yes"}:
            raise SystemExit("aborted by user")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = TOOLS_DIR / "structurizr-cli.zip"
    print(f"downloading {RELEASE_URL} -> {zip_path}", file=sys.stderr)
    urllib.request.urlretrieve(RELEASE_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(CLI_DIR)
    zip_path.unlink(missing_ok=True)
    CLI_SCRIPT.chmod(0o755)
    return CLI_SCRIPT


def locate(auto_yes: bool = False) -> Path:
    for finder in (_from_env, _from_path, _from_tools):
        p = finder()
        if p:
            return p
    return _download(auto_yes=auto_yes)


def run(
    args: list[str],
    *,
    auto_yes: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    cli = locate(auto_yes=auto_yes)
    cmd = ["bash", str(cli), *args] if cli.suffix == ".sh" else [str(cli), *args]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)
