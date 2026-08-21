#!/usr/bin/env python3
"""Regression tests for structural versus runtime dashboard evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import ks_dashboard_cell_report
import ks_readonly_audit_runner


def iframe_cell(source: str, *, events: list[dict[str, str]] | None = None) -> dict[str, object]:
    return {
        "uuid": "00000000-0000-0000-0000-000000000010",
        "entity": {
            "type": "IFRAME",
            "iframeSrc": source,
        },
        "events": events or [],
        "settings": {
            "name": {"value": "iframe"},
            "cellStyle": {"zIndex": None},
            "sizeAndContent": {
                "left": {"value": 0},
                "top": {"value": 0},
                "width": {"value": 100},
                "height": {"value": 100},
            },
        },
    }


def snapshot(cell: dict[str, object]) -> dict[str, object]:
    dashboard = {
        "uuid": "00000000-0000-0000-0000-000000000020",
        "name": "runtime-test",
        "configuration": {"cells": [cell]},
    }
    return {
        "projectUuid": "00000000-0000-0000-0000-000000000001",
        "createdAt": "2026-01-01T00:00:00Z",
        "sections": {"dashboards": {"details": {"dashboard": dashboard}}},
    }


class DashboardRuntimeVerificationTests(unittest.TestCase):
    def test_dynamic_iframe_is_runtime_only_not_a_structural_risk(self) -> None:
        rows, _overlaps = ks_dashboard_cell_report.dashboard_rows(
            snapshot(iframe_cell("about:blank", events=[{"type": "getString", "action": "get"}]))
        )

        self.assertEqual(rows[0]["risks"], [])
        self.assertIn("blank or dynamic", " ".join(rows[0]["runtime_verification"]))
        self.assertIn("event trigger", " ".join(rows[0]["runtime_verification"]))

    def test_static_iframe_still_requires_browser_evidence(self) -> None:
        rows, _overlaps = ks_dashboard_cell_report.dashboard_rows(
            snapshot(iframe_cell("https://example.invalid/page"))
        )

        self.assertEqual(
            rows[0]["runtime_verification"],
            ["verify iframe DOM, console, and network in a browser"],
        )

    def test_audit_summary_counts_runtime_verification_separately(self) -> None:
        rows, overlaps = ks_dashboard_cell_report.dashboard_rows(
            snapshot(iframe_cell("about:blank"))
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "dashboard.json"
            report.write_text(
                json.dumps({"rows": rows, "overlaps": overlaps}),
                encoding="utf-8",
            )
            summary = ks_readonly_audit_runner.dashboard_summary(report)

        self.assertEqual(summary["riskyCells"], 0)
        self.assertEqual(summary["runtimeVerificationCells"], 1)


if __name__ == "__main__":
    unittest.main()
