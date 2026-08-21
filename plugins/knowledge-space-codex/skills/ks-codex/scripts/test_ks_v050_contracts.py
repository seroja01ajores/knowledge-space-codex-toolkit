#!/usr/bin/env python3
"""Release contracts for the adaptive Knowledge Space Codex v0.5 line."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

import ks_capability_plan as planner
import ks_execution_receipt as receipt
import ks_task_handoff as handoff


SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
PLUGIN_ROOT = SKILL_ROOT.parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]


class V050ReleaseContractTests(unittest.TestCase):
    def test_manifest_readme_and_release_contract_are_synchronized(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(manifest["version"], "0.5.0")
        self.assertEqual(readme.count("--ref v0.5.0"), 2)
        self.assertIn("docs/release-0.5.md", readme)
        self.assertTrue((REPO_ROOT / "CHANGELOG.md").is_file())
        self.assertTrue((REPO_ROOT / "docs" / "release-0.5.md").is_file())

    def test_capability_schemas_have_no_numeric_area_limit(self) -> None:
        request_schema = json.loads(
            (SKILL_ROOT / "references" / "capability-request.schema.json").read_text(
                encoding="utf-8"
            )
        )
        plan_schema = json.loads(
            (SKILL_ROOT / "references" / "task-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn(
            "maxItems",
            request_schema["properties"]["capabilities"],
        )
        self.assertNotIn(
            "maxItems",
            plan_schema["properties"]["capabilities"],
        )

    def test_discovery_and_progressive_disclosure_resources_are_present(self) -> None:
        index = json.loads(
            (SKILL_ROOT / "references" / "capability-index.json").read_text(
                encoding="utf-8"
            )
        )
        areas = {area["id"]: area for area in index["areas"]}
        discovery = areas["capability-discovery"]
        operations = {item["id"] for item in discovery["operations"]}
        self.assertEqual(
            operations,
            {
                "inspect-api",
                "inspect-ui-network",
                "inspect-server-readonly",
                "record-gap",
            },
        )

        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for resource in (
            "adaptive-context-packs.md",
            "task-handoff.md",
            "self-learning.md",
            "execution-receipts.md",
            "use-case-patterns.md",
        ):
            with self.subTest(resource=resource):
                self.assertIn(resource, skill)
                self.assertTrue((SKILL_ROOT / "references" / resource).is_file())

    def test_new_v050_python_modules_parse_and_known_receipt_bug_stays_fixed(self) -> None:
        names = (
            "ks_capability_plan.py",
            "ks_task_handoff.py",
            "ks_knowledge.py",
            "ks_execution_receipt.py",
        )
        sources: dict[str, str] = {}
        for name in names:
            source = (SCRIPT_ROOT / name).read_text(encoding="utf-8")
            sources[name] = source
            with self.subTest(module=name):
                ast.parse(source, filename=name)

        self.assertNotIn(
            "for part in [root / Path(*relative.parts[:index])]",
            sources["ks_execution_receipt.py"],
        )
        self.assertIn(
            "(root / Path(*relative.parts[:index])).is_symlink()",
            sources["ks_execution_receipt.py"],
        )
        handoff_schema = (
            SKILL_ROOT / "references" / "task-handoff.schema.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("containsCredentials", handoff_schema)
        self.assertNotIn("containsCredentials", sources["ks_task_handoff.py"])
        self.assertIn("sensitiveValuesPresent", handoff_schema)
        self.assertIn("sensitiveValuesPresent", sources["ks_task_handoff.py"])

    def test_generated_handoff_validates_itself_without_secret_false_positive(self) -> None:
        index = planner.load_capability_index(
            planner.DEFAULT_INDEX_ROOT,
            planner.DEFAULT_INDEX_NAME,
        )
        plan = planner.build_plan(
            {
                "format": "teamvalue.ks-capability-request",
                "formatVersion": "1.0",
                "mode": "coordinated",
                "phase": "analysis",
                "capabilities": [
                    {"id": "dashboard-ui", "operation": "inspect"}
                ],
                "verification": [],
                "knowledge": {
                    "search": False,
                    "captureCandidate": False,
                },
            },
            index,
        )
        phase_ids = [item["id"] for item in plan["phases"]]
        state = {
            "format": "teamvalue.ks-handoff-state",
            "formatVersion": "1.0",
            "completedPhaseId": phase_ids[0],
            "phaseStatus": "completed",
            "nextPhaseId": phase_ids[1],
            "target": {
                "standAlias": None,
                "projectUuid": None,
                "projectUuidStatus": "not-applicable",
            },
            "facts": [],
            "unknowns": [],
            "contradictions": [],
            "approvals": [],
            "artifacts": [],
            "verification": [],
            "nextAction": "Continue with the next read-only phase",
        }
        generated = handoff.prepare_handoff(plan, state)
        self.assertFalse(generated["safety"]["sensitiveValuesPresent"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "handoff.json").write_text(
                json.dumps(generated),
                encoding="utf-8",
            )
            loaded = handoff.load_task_handoff(root, "handoff.json")
        self.assertEqual(loaded["handoffSha256"], generated["handoffSha256"])

    def test_receipt_resolves_nested_file_and_rejects_symlink_component(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            artifact = nested / "artifact.json"
            artifact.write_text("{}\n", encoding="utf-8")
            resolved, relative = receipt._resolve_artifact(
                root,
                "nested/artifact.json",
            )
            self.assertEqual(resolved, artifact.resolve())
            self.assertEqual(relative.as_posix(), "nested/artifact.json")

            outside = Path(outside_dir)
            (outside / "artifact.json").write_text("{}\n", encoding="utf-8")
            (root / "linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(receipt.ExecutionReceiptError):
                receipt._resolve_artifact(root, "linked/artifact.json")


if __name__ == "__main__":
    unittest.main()
