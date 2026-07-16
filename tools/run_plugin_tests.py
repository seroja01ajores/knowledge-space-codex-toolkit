#!/usr/bin/env python3
"""Run every synthetic plugin test without relying on package discovery."""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "knowledge-space-codex"


def main() -> int:
    tests = sorted(
        path
        for path in PLUGIN_ROOT.rglob("test_*.py")
        if "__pycache__" not in path.parts
    )
    if not tests:
        print("No plugin tests found", file=sys.stderr)
        return 2
    grouped: dict[Path, list[str]] = defaultdict(list)
    for path in tests:
        grouped[path.parent].append(path.name)
    print(f"Running {len(tests)} plugin test modules in {len(grouped)} script directories")
    for script_dir in sorted(grouped):
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", *grouped[script_dir]],
            cwd=script_dir,
            check=False,
        )
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
