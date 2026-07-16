#!/usr/bin/env python3
"""Focused tests for the offline KS environment preflight."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ks_environment_preflight import build_parser, collect_preflight, render_text  # noqa: E402


class EnvironmentPreflightTests(unittest.TestCase):
    def test_core_requirements_block_but_optional_tools_only_warn(self):
        report = collect_preflight(
            python_version=(3, 9, 18),
            module_finder=lambda _name: None,
            executable_finder=lambda _name: None,
        )
        self.assertFalse(report["ready"])
        self.assertEqual(report["blocking"], ["python", "requests"])
        self.assertNotIn("zstd", report["blocking"])
        self.assertNotIn("node", report["blocking"])

    def test_roundtrip_mode_requires_sibling_zstd_but_never_node(self):
        report = collect_preflight(
            require_roundtrip=True,
            python_version=(3, 10, 0),
            module_finder=lambda name: object() if name == "requests" else None,
            executable_finder=lambda name: None if name in {"zstd", "node"} else f"/bin/{name}",
        )
        self.assertFalse(report["ready"])
        self.assertEqual(report["blocking"], ["zstd"])
        text = render_text(report)
        self.assertIn("[FAIL] zstd", text)
        self.assertIn("[WARN] node", text)

    def test_help_describes_roundtrip_and_json_modes(self):
        help_text = build_parser().format_help()
        self.assertIn("--require-roundtrip", help_text)
        self.assertIn("--json", help_text)


if __name__ == "__main__":
    unittest.main()
