#!/usr/bin/env python3
"""Contract tests for the offline structured KS capability planner."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import ks_capability_plan as planner
import ks_safe_patch_lint as patch_lint


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / (
    "capability-scenarios.json"
)


class CapabilityPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = planner.load_capability_index(
            planner.DEFAULT_INDEX_ROOT,
            planner.DEFAULT_INDEX_NAME,
        )
        cls.corpus = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _load_request(self, value: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "request.json").write_text(
                json.dumps(value),
                encoding="utf-8",
            )
            return planner.load_capability_request(root, "request.json")

    def test_structured_scenario_corpus(self) -> None:
        self.assertEqual(
            self.corpus["format"],
            "teamvalue.ks-capability-scenarios",
        )
        self.assertEqual(self.corpus["formatVersion"], "1.0")

        for case in self.corpus["cases"]:
            with self.subTest(case=case["id"]):
                request = self._load_request(case["request"])
                plan = planner.build_plan(request, self.index)
                expected = case["expected"]

                direct = {
                    f"{item['id']}.{item['operation']}"
                    for item in plan["capabilities"]
                    if item["selection"] == "direct"
                }
                included_areas = {
                    item["id"] for item in plan["capabilities"]
                }
                phase_ids = {phase["id"] for phase in plan["phases"]}

                self.assertSetEqual(
                    direct,
                    set(expected["directCapabilities"]),
                )
                self.assertTrue(
                    set(expected["includedAreas"]).issubset(included_areas)
                )
                self.assertTrue(
                    set(expected["phaseIds"]).issubset(phase_ids)
                )
                self.assertEqual(
                    plan["safety"]["effectiveRisk"],
                    expected["effectiveRisk"],
                )
                self.assertEqual(
                    plan["safety"]["declaredCapabilityRisk"],
                    expected["effectiveRisk"],
                )
                self.assertIsNone(plan["contextPolicy"]["areaLimit"])
                self.assertEqual(
                    plan["contextPolicy"]["loadDetailedReferences"],
                    "current-phase-only",
                )
                self.assertTrue(plan["safety"]["planningOnly"])
                self.assertFalse(plan["safety"]["executionAuthorized"])
                self.assertFalse(plan["safety"]["liveKsCalled"])
                self.assertFalse(plan["safety"]["requestTextStored"])
                self.assertTrue(
                    plan["safety"]["requiresEndpointEffectClassification"]
                )
                self.assertTrue(
                    plan["safety"]["actualEffectMayEscalateRisk"]
                )
                self.assertFalse(
                    plan["safety"]["actualEffectMayDowngradeRisk"]
                )
                self.assertFalse(plan["knowledge"]["authorizesExecution"])

    def test_scenario_corpus_covers_material_risk_classes(self) -> None:
        case_ids = [case["id"] for case in self.corpus["cases"]]
        risks = {
            case["expected"]["effectiveRisk"]
            for case in self.corpus["cases"]
        }
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertTrue(
            {
                "read_only",
                "local_artifact_write",
                "project_write",
                "external_or_runtime",
                "destructive_or_global",
            }.issubset(risks)
        )

    def test_non_read_operations_gain_read_before_when_supported(self) -> None:
        by_id = {area["id"]: area for area in self.index["areas"]}
        for case in self.corpus["cases"]:
            request = self._load_request(case["request"])
            plan = planner.build_plan(request, self.index)
            selections = {
                (item["id"], item["operation"]): item["selection"]
                for item in plan["capabilities"]
            }
            for selected in request["capabilities"]:
                operations = {
                    item["id"]
                    for item in by_id[selected["id"]]["operations"]
                }
                if selected["operation"] == "inspect" or "inspect" not in operations:
                    continue
                with self.subTest(
                    case=case["id"],
                    capability=selected["id"],
                ):
                    self.assertEqual(
                        selections[(selected["id"], "inspect")],
                        "read-before",
                    )

    def test_non_read_scenarios_have_an_approval_boundary(self) -> None:
        for case in self.corpus["cases"]:
            if case["expected"]["effectiveRisk"] == "read_only":
                continue
            request = self._load_request(case["request"])
            plan = planner.build_plan(request, self.index)
            phase_ids = {phase["id"] for phase in plan["phases"]}
            with self.subTest(case=case["id"]):
                self.assertIn("approval-boundary", phase_ids)

    def test_multi_area_plan_has_no_numeric_area_cap(self) -> None:
        case = next(
            item
            for item in self.corpus["cases"]
            if item["id"] == "six-area-runtime-chain"
        )
        request = self._load_request(case["request"])
        plan = planner.build_plan(request, self.index)
        direct_area_ids = {
            item["id"]
            for item in plan["capabilities"]
            if item["selection"] == "direct"
        }
        self.assertGreaterEqual(len(direct_area_ids), 6)
        self.assertIsNone(plan["contextPolicy"]["areaLimit"])
        self.assertIn(
            "cross-area-synthesis",
            {phase["id"] for phase in plan["phases"]},
        )

    def test_parent_plan_hash_is_preserved_without_prior_raw_state(self) -> None:
        case = next(
            item
            for item in self.corpus["cases"]
            if item["id"] == "resumed-browser-verification"
        )
        request = self._load_request(case["request"])
        plan = planner.build_plan(request, self.index)
        self.assertEqual(
            plan["parentPlanSha256"],
            case["request"]["parentPlanSha256"],
        )
        self.assertFalse(plan["contextPolicy"]["storeRawResponses"])
        self.assertFalse(plan["contextPolicy"]["reloadReducedEvidence"])

    def test_loader_rejects_language_and_risk_overrides(self) -> None:
        base = {
            "format": "teamvalue.ks-capability-request",
            "formatVersion": "1.0",
            "mode": "coordinated",
            "capabilities": [
                {"id": "dashboard-ui", "operation": "inspect"}
            ],
        }
        for field, value in (
            ("requestText", "change the dashboard"),
            ("risk", "read_only"),
            ("actionMode", "read_only"),
        ):
            invalid = dict(base)
            invalid[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    planner.CapabilityPlanError,
                    "unsupported fields",
                ):
                    self._load_request(invalid)

    def test_loader_rejects_non_coordinated_modes(self) -> None:
        base = {
            "format": "teamvalue.ks-capability-request",
            "formatVersion": "1.0",
            "capabilities": [
                {"id": "dashboard-ui", "operation": "inspect"}
            ],
        }
        for mode in ("direct", "discovery"):
            invalid = dict(base)
            invalid["mode"] = mode
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(
                    planner.CapabilityPlanError,
                    "only for coordinated mode",
                ):
                    self._load_request(invalid)

    def test_loader_rejects_duplicate_capability_selection(self) -> None:
        with self.assertRaisesRegex(
            planner.CapabilityPlanError,
            "duplicate capability selection",
        ):
            self._load_request(
                {
                    "format": "teamvalue.ks-capability-request",
                    "formatVersion": "1.0",
                    "mode": "coordinated",
                    "capabilities": [
                        {"id": "tables", "operation": "inspect"},
                        {"id": "tables", "operation": "inspect"},
                    ],
                }
            )

    def test_unknown_capability_and_operation_fail_closed(self) -> None:
        for capability, operation in (
            ("unknown-area", "inspect"),
            ("dashboard-ui", "unknown-operation"),
        ):
            request = {
                "format": "teamvalue.ks-capability-request",
                "formatVersion": "1.0",
                "mode": "coordinated",
                "phase": "analysis",
                "capabilities": [
                    {"id": capability, "operation": operation}
                ],
                "verification": [],
                "knowledge": {
                    "search": False,
                    "captureCandidate": False,
                },
            }
            with self.subTest(capability=capability, operation=operation):
                with self.assertRaises(planner.CapabilityPlanError):
                    planner.build_plan(request, self.index)

    def test_planner_risk_maps_to_stable_execution_modes(self) -> None:
        expected = {
            "read_only": "dry_run",
            "project_write": "execute_project_writes",
            "external_or_runtime": "approved_runtime",
            "destructive_or_global": "approved_destructive",
            "server_or_db": "server_maintenance",
        }
        for risk, mode in expected.items():
            with self.subTest(risk=risk):
                self.assertEqual(patch_lint.RISK_REQUIRED_MODE[risk], mode)

    def test_actual_operation_effect_can_only_escalate_planner_risk(self) -> None:
        examples = (
            ("read_only", {"endpoint": "/integrator/integrate"}),
            ("project_write", {"endpoint": "/backups/load"}),
        )
        for declared_risk, operation in examples:
            actual_risk = patch_lint.classify_operation(operation)
            with self.subTest(
                declared=declared_risk,
                actual=actual_risk,
            ):
                self.assertGreater(
                    planner.RISK_ORDER[actual_risk],
                    planner.RISK_ORDER[declared_risk],
                )

    def test_catalog_is_compact_and_does_not_authorize_actions(self) -> None:
        catalog = planner.catalog(self.index)
        self.assertEqual(catalog["format"], "teamvalue.ks-capability-catalog")
        self.assertEqual(
            {area["id"] for area in catalog["areas"]},
            {area["id"] for area in self.index["areas"]},
        )
        for area in catalog["areas"]:
            self.assertNotIn("references", area)
            self.assertNotIn("scripts", area)
            self.assertNotIn("executionAuthorized", area)
            for operation in area["operations"]:
                self.assertNotIn("references", operation)
                self.assertNotIn("scripts", operation)
                self.assertNotIn("executionAuthorized", operation)


if __name__ == "__main__":
    unittest.main()
