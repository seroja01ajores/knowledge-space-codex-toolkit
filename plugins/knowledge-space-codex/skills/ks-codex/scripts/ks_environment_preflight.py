#!/usr/bin/env python3
"""Offline dependency preflight for the canonical KS Codex scripts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
from typing import Any, Callable, Sequence


MINIMUM_PYTHON = (3, 10)


def _module_available(name: str, finder: Callable[[str], Any]) -> bool:
    try:
        return finder(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def collect_preflight(
    *,
    require_roundtrip: bool = False,
    python_version: tuple[int, int, int] | None = None,
    module_finder: Callable[[str], Any] = importlib.util.find_spec,
    executable_finder: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Collect dependency state without network calls or environment mutation."""
    version = python_version or tuple(sys.version_info[:3])
    python_ok = version >= MINIMUM_PYTHON
    requests_ok = _module_available("requests", module_finder)
    zstd_path = executable_finder("zstd")
    node_path = executable_finder("node")

    checks = [
        {
            "name": "python",
            "available": python_ok,
            "required": True,
            "detected": ".".join(str(part) for part in version),
            "requirement": ">=3.10",
            "purpose": "all canonical KS scripts",
        },
        {
            "name": "requests",
            "available": requests_ok,
            "required": True,
            "detected": "installed" if requests_ok else "missing",
            "purpose": "official KS API client scripts",
        },
        {
            "name": "zstd",
            "available": bool(zstd_path),
            "required": require_roundtrip,
            "detected": zstd_path or "missing",
            "purpose": "packed backup roundtrip in sibling skill ks-diagram-roundtrip",
            "siblingDependency": True,
        },
        {
            "name": "node",
            "available": bool(node_path),
            "required": False,
            "detected": node_path or "missing",
            "purpose": "optional browser API capture script ks_capture_api_calls.mjs",
        },
    ]
    blocking = [check["name"] for check in checks if check["required"] and not check["available"]]
    return {
        "ready": not blocking,
        "platform": platform.platform(),
        "roundtripRequired": require_roundtrip,
        "blocking": blocking,
        "checks": checks,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = ["KS environment preflight"]
    for check in report["checks"]:
        if check["available"]:
            state = "OK"
        elif check["required"]:
            state = "FAIL"
        else:
            state = "WARN"
        requirement = f" (required {check['requirement']})" if check.get("requirement") else ""
        lines.append(
            f"[{state}] {check['name']}: {check['detected']}{requirement} - {check['purpose']}"
        )
    lines.append("Result: READY" if report["ready"] else f"Result: BLOCKED ({', '.join(report['blocking'])})")
    if not report["roundtripRequired"]:
        lines.append("Tip: use --require-roundtrip when packed backup unpack/pack is part of the task.")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check local dependencies for KS API scripts and optional capture/backup workflows."
    )
    parser.add_argument(
        "--require-roundtrip",
        action="store_true",
        help="Treat sibling ks-diagram-roundtrip's zstd executable as required.",
    )
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_preflight(require_roundtrip=args.require_roundtrip)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report), end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
