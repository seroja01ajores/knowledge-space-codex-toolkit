#!/usr/bin/env python3
"""Safety regressions for offline KS project comparison."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ks_project_diff


def snapshot(*, errors: list[object] | None = None) -> dict[str, object]:
    return {
        "projectUuid": "00000000-0000-0000-0000-000000000001",
        "createdAt": "2026-01-01T00:00:00Z",
        "errors": errors or [],
        "sections": {},
    }


class ProjectDiffCompletenessTests(unittest.TestCase):
    def test_complete_snapshots_keep_structural_diff_available(self) -> None:
        report = ks_project_diff.render_report(snapshot(), snapshot(), "Complete")

        self.assertIn("- comparisonValid: `true`", report)
        self.assertIn("## Section Counts", report)
        self.assertIn("No high-level structural blockers", report)

    def test_incomplete_snapshot_blocks_missing_and_extra_inferences(self) -> None:
        report = ks_project_diff.render_report(
            snapshot(errors=[{"section": "dashboards", "status": 403}]),
            snapshot(),
            "Incomplete",
        )

        self.assertIn("- comparisonValid: `false`", report)
        self.assertIn("Comparison blocked", report)
        self.assertNotIn("## Section Counts", report)
        self.assertNotIn("No high-level structural blockers", report)

    def test_cli_returns_nonzero_and_still_writes_blocked_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.json"
            candidate = root / "candidate.json"
            report = root / "report.md"
            reference.write_text(
                json.dumps(snapshot(errors=[{"section": "classes", "status": 403}])),
                encoding="utf-8",
            )
            candidate.write_text(json.dumps(snapshot()), encoding="utf-8")

            with patch.object(
                sys,
                "argv",
                ["ks_project_diff.py", str(reference), str(candidate), "--out", str(report)],
            ):
                exit_code = ks_project_diff.main()

            self.assertEqual(exit_code, 2)
            self.assertTrue(report.is_file())
            self.assertIn("comparisonValid: `false`", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
