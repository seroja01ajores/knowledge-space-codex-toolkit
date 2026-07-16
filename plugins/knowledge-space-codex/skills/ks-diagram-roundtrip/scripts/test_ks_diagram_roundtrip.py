#!/usr/bin/env python3
"""Synthetic golden and negative tests for structural-v0.1."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import ks_diagram_roundtrip as rt


PROJECT = "10000000-0000-4000-8000-000000000001"
CLASS_A = "10000000-0000-4000-8000-000000000010"
CLASS_B = "10000000-0000-4000-8000-000000000020"
RELATION = "10000000-0000-4000-8000-000000000030"
HELPER_S = "10000000-0000-4000-8000-000000000031"
HELPER_T = "10000000-0000-4000-8000-000000000032"
TREE_A = "20000000-0000-4000-8000-000000000010"
TREE_B = "20000000-0000-4000-8000-000000000020"
TREE_R = "20000000-0000-4000-8000-000000000030"
STAMP = "2000-01-01T00:00:00.000Z"


def entity_data(
    entity_uuid: str,
    name: str,
    source: str | None = None,
    target: str | None = None,
    *,
    helper: bool = False,
) -> dict:
    return {
        "uuid": entity_uuid,
        "name": name,
        "description": "",
        "projectUuid": PROJECT,
        "descriptionStatus": "empty",
        "backupEntityCategory": "prod",
        "objectEntityCategory": "undefined" if helper else "prod",
        "createdBy": rt.ZERO_UUID,
        "createdAt": STAMP,
        "updatedAt": STAMP,
        "updatedBy": rt.ZERO_UUID,
        "objectsContainDiagrams": False,
        "diagramTemplateUuid": None,
        "storageType": "regular",
        "storageStructureAppliedAt": None,
        "relatedSourceUuid": source,
        "relatedDestinationUuid": target,
        "sourceObjectsLimit": 0,
        "destinationObjectsLimit": 0,
        "strictRelation": False,
        "objectsLimitInModel": False,
        "replaceOldRelationsType": "undefined",
        "restrictionLevelType": "undefined",
        "showWarning": False,
        "indicators": None,
        "dimensions": None,
        "usages": None,
    }


def class_record(
    entity_uuid: str,
    name: str,
    data: dict,
    parent: str | None = None,
) -> dict:
    return {
        "UUID": entity_uuid,
        "ProjectUUID": PROJECT,
        "Name": name,
        "ParentRelationUUID": parent,
        "Group": "class",
        "Type": "class",
        "Data": data,
    }


def tree_record(entity_uuid: str, tree_uuid: str, parent: str | None) -> dict:
    return {
        "UUID": tree_uuid,
        "ProjectUUID": rt.ZERO_UUID,
        "ParentRelationUUID": None,
        "Group": "class",
        "Type": "tree",
        "Data": {
            "uuid": tree_uuid,
            "type": "class",
            "parentUuid": parent,
            "projectUuid": PROJECT,
            "referenceUuid": entity_uuid,
            "createdAt": STAMP,
            "updatedAt": STAMP,
        },
    }


def l10n_record(entity_uuid: str, suffix: str, name: str) -> dict:
    l10n_uuid = f"30000000-0000-4000-8000-0000000000{suffix}"
    return {
        "UUID": l10n_uuid,
        "ProjectUUID": rt.ZERO_UUID,
        "Name": name,
        "ParentRelationUUID": None,
        "Group": "class",
        "Type": "classL10n",
        "Data": {
            "uuid": l10n_uuid,
            "classUuid": entity_uuid,
            "code": "ru_RU",
            "name": name,
        },
    }


def fixture_records() -> list[dict]:
    helper_s = entity_data(HELPER_S, f"{rt.HELPER_PREFIX}A_to_R", CLASS_A, RELATION, helper=True)
    helper_t = entity_data(HELPER_T, f"{rt.HELPER_PREFIX}R_to_B", RELATION, CLASS_B, helper=True)
    relation = entity_data(RELATION, "Fixture relation", CLASS_A, CLASS_B)
    relation["relations"] = [copy.deepcopy(helper_s), copy.deepcopy(helper_t)]
    class_a = entity_data(CLASS_A, "Fixture Class A")
    class_a["relations"] = [copy.deepcopy(helper_s), rt.without_relations(relation)]
    class_b = entity_data(CLASS_B, "Fixture Class B")
    class_b["relations"] = [rt.without_relations(relation), copy.deepcopy(helper_t)]
    return [
        class_record(CLASS_A, "Fixture Class A", class_a),
        class_record(CLASS_B, "Fixture Class B", class_b),
        class_record(HELPER_S, helper_s["name"], helper_s, CLASS_A),
        class_record(RELATION, "Fixture relation", relation, CLASS_B),
        class_record(HELPER_T, helper_t["name"], helper_t, CLASS_B),
        tree_record(CLASS_A, TREE_A, None),
        tree_record(CLASS_B, TREE_B, None),
        tree_record(RELATION, TREE_R, TREE_A),
        l10n_record(CLASS_A, "10", "Fixture Class A"),
        l10n_record(CLASS_B, "20", "Fixture Class B"),
        l10n_record(RELATION, "30", "Fixture relation"),
        {
            "UUID": PROJECT,
            "ProjectUUID": PROJECT,
            "Name": "Synthetic KS project",
            "ParentRelationUUID": None,
            "Group": "project",
            "Type": "project",
            "Data": {
                "uuid": PROJECT,
                "name": "Synthetic KS project",
                "description": "",
                "createdAt": STAMP,
                "updatedAt": STAMP,
            },
        },
    ]


def reversed_helper_fixture_records() -> list[dict]:
    records = fixture_records()
    by_uuid = {record["UUID"]: record for record in records}
    source_side_helper = entity_data(
        HELPER_S,
        f"{rt.HELPER_PREFIX}R_to_A",
        RELATION,
        CLASS_A,
        helper=True,
    )
    target_side_helper = entity_data(
        HELPER_T,
        f"{rt.HELPER_PREFIX}B_to_R",
        CLASS_B,
        RELATION,
        helper=True,
    )
    relation = entity_data(RELATION, "Fixture relation", CLASS_A, CLASS_B)
    relation["relations"] = [
        copy.deepcopy(source_side_helper),
        copy.deepcopy(target_side_helper),
    ]
    class_a = entity_data(CLASS_A, "Fixture Class A")
    class_a["relations"] = [
        copy.deepcopy(source_side_helper),
        rt.without_relations(relation),
    ]
    class_b = entity_data(CLASS_B, "Fixture Class B")
    class_b["relations"] = [
        rt.without_relations(relation),
        copy.deepcopy(target_side_helper),
    ]
    by_uuid[CLASS_A]["Data"] = class_a
    by_uuid[CLASS_B]["Data"] = class_b
    by_uuid[HELPER_S]["Name"] = source_side_helper["name"]
    by_uuid[HELPER_S]["Data"] = source_side_helper
    by_uuid[RELATION]["Data"] = relation
    by_uuid[HELPER_T]["Name"] = target_side_helper["name"]
    by_uuid[HELPER_T]["Data"] = target_side_helper
    return records


def self_relation_fixture_records() -> list[dict]:
    records = fixture_records()
    by_uuid = {record["UUID"]: record for record in records}
    source_helper = entity_data(
        HELPER_S,
        f"{rt.HELPER_PREFIX}A_to_R",
        CLASS_A,
        RELATION,
        helper=True,
    )
    target_helper = entity_data(
        HELPER_T,
        f"{rt.HELPER_PREFIX}R_to_A",
        RELATION,
        CLASS_A,
        helper=True,
    )
    relation = entity_data(RELATION, "Fixture self relation", CLASS_A, CLASS_A)
    relation["relations"] = [copy.deepcopy(source_helper), copy.deepcopy(target_helper)]
    class_a = entity_data(CLASS_A, "Fixture Class A")
    class_a["relations"] = [
        copy.deepcopy(source_helper),
        rt.without_relations(relation),
        copy.deepcopy(target_helper),
    ]
    class_b = entity_data(CLASS_B, "Fixture Class B")
    class_b["relations"] = []
    by_uuid[CLASS_A]["Data"] = class_a
    by_uuid[CLASS_B]["Data"] = class_b
    by_uuid[HELPER_S]["Data"] = source_helper
    by_uuid[RELATION]["Name"] = relation["name"]
    by_uuid[RELATION]["ParentRelationUUID"] = CLASS_A
    by_uuid[RELATION]["Data"] = relation
    by_uuid[HELPER_T]["Name"] = target_helper["name"]
    by_uuid[HELPER_T]["ParentRelationUUID"] = CLASS_A
    by_uuid[HELPER_T]["Data"] = target_helper
    return records


def artifacts() -> tuple[list[dict], dict, dict, dict, str]:
    records = fixture_records()
    source_sha = rt.semantic_sha256(records)
    normalized = rt.normalize_records(records)
    diagram = rt.diagram_from_normalized(normalized)
    bridge = rt.bridge_from_normalized(normalized, diagram, source_sha)
    return records, normalized, diagram, bridge, source_sha


def edited_diagram(diagram: dict) -> dict:
    edited = copy.deepcopy(diagram)
    class_id = "40000000-0000-4000-8000-000000000001"
    relation_id = "40000000-0000-4000-8000-000000000002"
    edited["updatedAt"] = "2000-01-02T00:00:00.000Z"
    edited["classes"].append(
        {
            "id": class_id,
            "name": "Fixture Class C",
            "description": "Synthetic description",
            "stereotype": "Object",
            "attributes": [
                {
                    "id": "40000000-0000-4000-8000-000000000003",
                    "name": "Diagram-only attribute",
                    "dataType": "string",
                    "required": False,
                    "description": "",
                    "knowledgeSpaceNotes": "",
                }
            ],
            "indicators": [],
            "position": {"x": 900, "y": 600},
            "size": {"width": 260, "height": 180},
            "objectCount": 3,
            "notes": "",
        }
    )
    edited["relationships"].append(
        {
            "id": relation_id,
            "sourceClassId": class_id,
            "targetClassId": diagram["classes"][0]["id"],
            "type": "association",
            "name": "Fixture new relation",
            "description": "Synthetic relationship description",
            "direction": "source_to_target",
            "cardinality": "1..1",
            "indicators": [],
            "notes": "",
        }
    )
    return edited


class RoundTripTests(unittest.TestCase):
    def test_from_ks_outputs_schema_bridge_and_normalized_baseline(self) -> None:
        records = fixture_records()
        diagram, bridge, normalized = rt.from_ks(records)
        self.assertTrue(rt.validate_ks_records(records)["valid"])
        self.assertEqual(diagram["schemaVersion"], "1.2")
        self.assertEqual(len(diagram["classes"]), 2)
        self.assertEqual(len(diagram["relationships"]), 1)
        self.assertEqual(diagram["classes"][0]["ksProperties"], [])
        self.assertEqual(diagram["relationships"][0]["ksProperties"], [])
        self.assertEqual(bridge["profile"], "structural-v0.1")
        self.assertEqual(bridge["mappingProfile"], "structural-v0.1")
        self.assertEqual(normalized["excludedHelperEntityUuids"], [HELPER_S, HELPER_T])
        self.assertEqual(bridge["source"]["semanticSha256"], rt.semantic_sha256(records))

    def test_legacy_reversed_helpers_are_read_with_explicit_endpoint_side_warning(self) -> None:
        records = reversed_helper_fixture_records()
        original = copy.deepcopy(records)
        report = rt.validate_ks_records(records)
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn(
            "reversed_helper_orientation",
            {warning["code"] for warning in report["warnings"]},
        )
        self.assertEqual(rt.rio.validate_structural_slice(records), [])

        diagram, bridge, normalized = rt.from_ks(records)
        relationship = normalized["relationships"][0]
        self.assertEqual(relationship["sourceHelperUuid"], HELPER_S)
        self.assertEqual(relationship["targetHelperUuid"], HELPER_T)
        self.assertEqual(relationship["helperOrientation"], "legacy_reversed")
        self.assertEqual(
            relationship["sourceWarnings"][0]["code"],
            "reversed_helper_orientation",
        )
        self.assertIn("Source warning:", diagram["relationships"][0]["notes"])
        self.assertEqual(
            bridge["entityMap"]["relationships"][0]["helperOrientation"],
            "legacy_reversed",
        )
        self.assertEqual(records, original)

    def test_existing_self_relation_is_read_but_new_self_relation_stays_forbidden(self) -> None:
        records = self_relation_fixture_records()
        original = copy.deepcopy(records)
        report = rt.validate_ks_records(records)
        self.assertTrue(report["valid"], report["errors"])
        self.assertIn(
            "existing_self_relationship",
            {warning["code"] for warning in report["warnings"]},
        )

        diagram, bridge, normalized = rt.from_ks(records)
        relationship = normalized["relationships"][0]
        self.assertEqual(
            relationship["sourceEntityUuid"], relationship["destinationEntityUuid"]
        )
        self.assertEqual(relationship["sourceHelperUuid"], HELPER_S)
        self.assertEqual(relationship["targetHelperUuid"], HELPER_T)
        self.assertEqual(
            relationship["sourceWarnings"][0]["code"],
            "existing_self_relationship",
        )
        self.assertEqual(records, original)

        edited = copy.deepcopy(diagram)
        new_self = copy.deepcopy(diagram["relationships"][0])
        new_self["id"] = "40000000-0000-4000-8000-000000000099"
        new_self["name"] = "New self relation"
        new_self["sourceClassId"] = diagram["classes"][0]["id"]
        new_self["targetClassId"] = diagram["classes"][0]["id"]
        edited["relationships"].append(new_self)
        plan = rt.create_diff_plan(records, diagram, edited, bridge)
        self.assertIn(
            "self_relationship_unsupported",
            {item["code"] for item in plan["forbiddenChanges"]},
        )

    def test_semantic_hash_is_path_and_format_independent(self) -> None:
        records = fixture_records()
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "one.json"
            second = Path(temp_dir) / "nested" / "two.json"
            second.parent.mkdir()
            first.write_text(json.dumps(records, indent=2), encoding="utf-8")
            second.write_text(json.dumps({"records": records}, separators=(",", ":")), encoding="utf-8")
            one = rt.records_from_document(rt.load_json(str(first)))
            two = rt.records_from_document(rt.load_json(str(second)))
            self.assertEqual(rt.semantic_sha256(one), rt.semantic_sha256(two))

    def test_diff_binds_every_input_and_classifies_deferred_paths(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        edited = edited_diagram(baseline)
        plan = rt.create_diff_plan(records, baseline, edited, bridge)
        self.assertFalse(plan["summary"]["applyBlocked"])
        self.assertFalse(plan["offlineBuildBlocked"])
        self.assertTrue(plan["liveRestoreBlocked"])
        self.assertEqual(plan["format"], "teamvalue.ks-diagram-change-plan")
        self.assertEqual(plan["summary"]["createClasses"], 1)
        self.assertEqual(plan["summary"]["createRelationships"], 1)
        for key, value in (
            ("sourceSemanticSha256", records),
            ("baselineSemanticSha256", baseline),
            ("editedSemanticSha256", edited),
            ("bridgeSemanticSha256", bridge),
        ):
            self.assertEqual(plan["binding"][key], rt.semantic_sha256(value))
        required = plan["requiredDeferredAcceptances"]
        self.assertTrue(any(path.endswith("/attributes") for path in required))
        self.assertTrue(any(path.endswith("/objectCount") for path in required))
        self.assertTrue(any(path.endswith("/type") for path in required))
        self.assertTrue(any(path.endswith("/direction") for path in required))
        self.assertFalse(any(path.endswith("/description") and "/relationships/" in path for path in required))

    def test_build_requires_exact_reviewed_plan_and_exact_acceptances(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        edited = edited_diagram(baseline)
        plan = rt.create_diff_plan(records, baseline, edited, bridge)
        required = plan["requiredDeferredAcceptances"]
        with self.assertRaises(rt.BuildBlocked) as missing_context:
            rt.build_backup(records, baseline, edited, bridge, plan, required[:-1], STAMP, rt.ZERO_UUID)
        self.assertEqual(len(missing_context.exception.report["deferredAcceptance"]["missing"]), 1)
        with self.assertRaises(rt.BuildBlocked) as unknown_context:
            rt.build_backup(records, baseline, edited, bridge, plan, required + ["/unknown/path"], STAMP, rt.ZERO_UUID)
        self.assertEqual(unknown_context.exception.report["deferredAcceptance"]["unknown"], ["/unknown/path"])
        tampered = copy.deepcopy(plan)
        tampered["summary"]["createClasses"] = 999
        with self.assertRaises(rt.BuildBlocked) as mismatch_context:
            rt.build_backup(records, baseline, edited, bridge, tampered, required, STAMP, rt.ZERO_UUID)
        self.assertFalse(mismatch_context.exception.report["planBinding"]["matches"])
        with self.assertRaises(rt.BuildBlocked) as duplicate_context:
            rt.build_backup(records, baseline, edited, bridge, plan, required + [required[0]], STAMP, rt.ZERO_UUID)
        self.assertEqual(duplicate_context.exception.report["deferredAcceptance"]["duplicates"], [required[0]])

    def test_existing_relationship_type_and_direction_are_deferred_not_local(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        edited = copy.deepcopy(baseline)
        relationship_id = edited["relationships"][0]["id"]
        edited["relationships"][0]["type"] = "composition"
        edited["relationships"][0]["direction"] = "bidirectional"
        plan = rt.create_diff_plan(records, baseline, edited, bridge)
        paths = set(plan["requiredDeferredAcceptances"])
        self.assertIn(rt._deferred_path("relationships", relationship_id, "type"), paths)
        self.assertIn(rt._deferred_path("relationships", relationship_id, "direction"), paths)
        local_paths = {item.get("path") for item in plan["localOnlyChanges"]}
        self.assertNotIn(rt._deferred_path("relationships", relationship_id, "type"), local_paths)
        edited["classes"][0]["notes"] = "Diagram-only class note"
        notes_plan = rt.create_diff_plan(records, baseline, edited, bridge)
        self.assertIn(rt._deferred_path("classes", edited["classes"][0]["id"], "notes"), notes_plan["requiredDeferredAcceptances"])

    def test_legacy_pilot_bridge_defaults_are_safe_but_explicit_unknowns_fail(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        legacy = copy.deepcopy(bridge)
        legacy.pop("profile")
        legacy.pop("mappingProfile")
        legacy.pop("mode")
        legacy["diagram"].pop("baselineSemanticSha256")
        legacy["writePolicy"] = {"allowedIntents": ["create_class", "create_relationship"]}
        self.assertTrue(rt.validate_bridge(legacy)["valid"])
        plan = rt.create_diff_plan(records, baseline, edited_diagram(baseline), legacy)
        self.assertFalse(plan["offlineBuildBlocked"])
        legacy["profile"] = "future-v9"
        self.assertFalse(rt.validate_bridge(legacy)["valid"])
        legacy["profile"] = rt.PROFILE
        legacy["mappingProfile"] = "future-v9"
        self.assertFalse(rt.validate_bridge(legacy)["valid"])

    def test_golden_create_adds_exactly_eight_and_preserves_unknown_records(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        opaque = {
            "UUID": "50000000-0000-4000-8000-000000000001",
            "ProjectUUID": PROJECT,
            "Name": "Opaque",
            "Group": "fixture",
            "Type": "unknownFixtureType",
            "Data": {"uuid": "50000000-0000-4000-8000-000000000001", "opaque": {"keep": [1, 2, 3]}},
        }
        records.append(copy.deepcopy(opaque))
        baseline, bridge, _ = rt.from_ks(records)
        edited = edited_diagram(baseline)
        plan = rt.create_diff_plan(records, baseline, edited, bridge)
        output, report = rt.build_backup(
            records, baseline, edited, bridge, plan,
            plan["requiredDeferredAcceptances"],
            "2000-01-02T00:00:00.000Z", rt.ZERO_UUID,
        )
        self.assertEqual(len(output), len(records) + 8)
        self.assertEqual(report["addedTopLevelRecords"], 8)
        self.assertEqual(report["expectedTopLevelRecords"], 8)
        self.assertEqual([item for item in output if item.get("UUID") == opaque["UUID"]][0], opaque)
        generated = report["generatedRelationships"][0]
        new_relation = next(item for item in output if item.get("UUID") == generated["ksEntityUuid"])
        self.assertEqual(new_relation["Data"]["description"], "Synthetic relationship description")
        self.assertEqual(len(new_relation["Data"]["relations"]), 2)
        target = next(item for item in output if item.get("UUID") == CLASS_A)
        target_members = [item["uuid"] for item in target["Data"]["relations"]]
        self.assertIn(generated["ksEntityUuid"], target_members)
        self.assertIn(generated["targetHelperUuid"], target_members)
        self.assertTrue(report["validation"]["valid"])
        self.assertEqual([item["uuid"] for item in report["mutatedExistingRecords"]], [CLASS_A])
        new_class = next(item for item in output if item.get("UUID") == report["generatedClasses"][0]["ksEntityUuid"])
        self.assertEqual(new_class["Data"]["storageType"], "regular")
        self.assertEqual(
            report["outputSemanticSha256"],
            "24ab3a8c2a13fd9d80e78d08b15834ddd3b542bd1fb9a2ebd44319540bef782f",
        )

    def test_existing_description_is_deferred_and_delete_endpoint_change_block(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        edited = copy.deepcopy(baseline)
        edited["classes"][0]["description"] = "updated synthetic description"
        plan = rt.create_diff_plan(records, baseline, edited, bridge)
        self.assertEqual(plan["summary"]["updateClassDescriptions"], 0)
        description_path = rt._deferred_path("classes", edited["classes"][0]["id"], "description")
        self.assertIn(description_path, plan["requiredDeferredAcceptances"])
        output, _ = rt.build_backup(records, baseline, edited, bridge, plan, [description_path], STAMP, rt.ZERO_UUID)
        self.assertEqual(next(item for item in output if item.get("UUID") == CLASS_A)["Data"]["description"], "")
        deleted = copy.deepcopy(baseline)
        deleted["classes"] = deleted["classes"][1:]
        self.assertIn("forbidden_changes", rt.create_diff_plan(records, baseline, deleted, bridge)["applyBlockedReasons"])
        changed = copy.deepcopy(baseline)
        changed["relationships"][0]["targetClassId"] = changed["relationships"][0]["sourceClassId"]
        self.assertIn("forbidden_changes", rt.create_diff_plan(records, baseline, changed, bridge)["applyBlockedReasons"])

    def test_missing_ids_and_unknown_profile_mode_schema_are_controlled(self) -> None:
        records, _, baseline, bridge, _ = artifacts()
        broken_records = copy.deepcopy(records)
        broken_records[0].pop("UUID")
        report = rt.validate_ks_records(broken_records)
        self.assertFalse(report["valid"])
        self.assertTrue(any(item["code"] == "missing_record_uuid" for item in report["errors"]))
        with self.assertRaises(rt.RoundTripError):
            rt.from_ks(broken_records)
        wrong_profile = copy.deepcopy(bridge)
        wrong_profile["profile"] = "future-v9"
        self.assertTrue(any(item["code"] == "unsupported_profile" for item in rt.validate_bridge(wrong_profile)["errors"]))
        wrong_mapping_profile = copy.deepcopy(bridge)
        wrong_mapping_profile["mappingProfile"] = "future-v9"
        self.assertTrue(any(item["code"] == "unsupported_profile" for item in rt.validate_bridge(wrong_mapping_profile)["errors"]))
        wrong_mode = copy.deepcopy(bridge)
        wrong_mode["mode"] = "live"
        self.assertTrue(any(item["code"] == "unsupported_mode" for item in rt.validate_bridge(wrong_mode)["errors"]))
        wrong_schema = copy.deepcopy(baseline)
        wrong_schema["schemaVersion"] = "9.9"
        self.assertTrue(any(item["code"] == "unsupported_schema" for item in rt.validate_diagram(wrong_schema)["errors"]))
        legacy_schema = copy.deepcopy(baseline)
        legacy_schema["schemaVersion"] = "1.1"
        self.assertTrue(rt.validate_diagram(legacy_schema)["valid"])
        legacy_bridge = copy.deepcopy(bridge)
        legacy_bridge["diagram"]["schemaVersion"] = "1.1"
        self.assertTrue(rt.validate_bridge(legacy_bridge)["valid"])
        self.assertEqual(rt.main(["validate", "--profile", "future-v9", "--input", "/missing"]), 2)
        self.assertEqual(rt.main(["validate", "--mode", "live", "--input", "/missing"]), 2)

    def test_tree_l10n_helper_and_formula_closure(self) -> None:
        records = fixture_records()
        missing_l10n = [item for item in records if item.get("Type") != "classL10n" or item["Data"].get("classUuid") != CLASS_A]
        self.assertFalse(rt.validate_ks_records(missing_l10n)["valid"])
        helper_tree = tree_record(HELPER_S, "60000000-0000-4000-8000-000000000001", None)
        self.assertFalse(rt.validate_ks_records(records + [helper_tree])["valid"])
        cyclic = copy.deepcopy(records)
        for item in cyclic:
            if item.get("UUID") == TREE_A:
                item["Data"]["parentUuid"] = TREE_R
        self.assertFalse(rt.validate_ks_records(cyclic)["valid"])
        indicator_uuid = "70000000-0000-4000-8000-000000000001"
        formula_uuid = "70000000-0000-4000-8000-000000000002"
        indicator = {"UUID": indicator_uuid, "ProjectUUID": PROJECT, "Name": "Synthetic indicator", "ParentRelationUUID": CLASS_A, "Group": "class", "Type": "indicator", "Data": {"uuid": indicator_uuid, "classUuid": CLASS_A}}
        indicator_tree = tree_record(indicator_uuid, "70000000-0000-4000-8000-000000000003", TREE_A)
        formula = {"UUID": formula_uuid, "ProjectUUID": PROJECT, "Name": "Synthetic formula", "ParentRelationUUID": CLASS_B, "Group": "class", "Type": "formula", "Data": {"uuid": formula_uuid, "classUuid": CLASS_B, "indicatorUuid": indicator_uuid}}
        formula_report = rt.validate_ks_records(records + [indicator, indicator_tree, formula])
        self.assertFalse(formula_report["valid"])
        self.assertTrue(any(item["code"] == "formula_owner" for item in formula_report["errors"]))

    def test_cli_diff_and_build_use_byte_bound_reviewed_plan(self) -> None:
        records = fixture_records()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.json"
            baseline_diagram = root / "baseline.diagram.json"
            bridge_path = root / "bridge.json"
            normalized = root / "baseline.normalized.json"
            edited_path = root / "edited.diagram.json"
            plan_path = root / "plan.json"
            output = root / "output.json"
            report_path = root / "build-report.json"
            source.write_text(json.dumps(records, indent=2), encoding="utf-8")
            self.assertEqual(rt.main(["from-ks", "--input", str(source), "--diagram", str(baseline_diagram), "--bridge", str(bridge_path), "--baseline", str(normalized)]), 0)
            edited = edited_diagram(rt.load_json(str(baseline_diagram)))
            edited_path.write_text(json.dumps(edited, indent=2), encoding="utf-8")
            self.assertEqual(rt.main(["diff", "--source", str(source), "--baseline", str(baseline_diagram), "--edited", str(edited_path), "--bridge", str(bridge_path), "--output", str(plan_path)]), 0)
            plan = rt.load_json(str(plan_path))
            self.assertEqual(plan["artifactHashMode"], "byte_sha256")
            self.assertEqual(plan["artifactHashes"]["sourceSha256"], rt.sha256_file(str(source)))
            build_args = ["build", "--input", str(source), "--baseline", str(baseline_diagram), "--edited", str(edited_path), "--bridge", str(bridge_path), "--plan", str(plan_path), "--output", str(output), "--report", str(report_path), "--timestamp", "2000-01-02T00:00:00.000Z", "--actor-uuid", rt.ZERO_UUID]
            for path in plan["requiredDeferredAcceptances"]:
                build_args.extend(["--accept-deferred-path", path])
            self.assertEqual(rt.main(build_args), 0)
            report = rt.load_json(str(report_path))
            self.assertTrue(report["planBinding"]["matches"])
            self.assertEqual(report["planBinding"]["artifactHashMode"], "byte_sha256")
            self.assertEqual(report["addedTopLevelRecords"], 8)

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_manifest_bound_pipeline_passes_baseline_and_final_bundle_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.json"
            baseline = root / "baseline.diagram.json"
            bridge = root / "bridge.json"
            normalized = root / "normalized.json"
            manifest = root / "run-manifest.json"
            baseline_bundle = root / "baseline.bundle.json"
            edited_path = root / "edited.diagram.json"
            plan_path = root / "plan.json"
            output = root / "output.json"
            build_report = root / "build-report.json"
            validation = root / "validation.json"
            packed = root / "packed.json"
            pack_report = root / "pack-report.json"
            final_bundle = root / "final.bundle.json"
            source.write_text(json.dumps(fixture_records()), encoding="utf-8")
            self.assertEqual(rt.main(["from-ks", "--input", str(source), "--diagram", str(baseline), "--bridge", str(bridge), "--baseline", str(normalized), "--manifest", str(manifest)]), 0)
            self.assertEqual(rt.main(["validate-bundle", "--manifest", str(manifest), "--report", str(baseline_bundle)]), 0)
            edited_path.write_text(json.dumps(edited_diagram(rt.load_json(str(baseline)))), encoding="utf-8")
            self.assertEqual(rt.main(["diff", "--source", str(source), "--baseline", str(baseline), "--edited", str(edited_path), "--bridge", str(bridge), "--output", str(plan_path), "--manifest", str(manifest)]), 0)
            plan = rt.load_json(str(plan_path))
            build_args = ["build", "--input", str(source), "--baseline", str(baseline), "--edited", str(edited_path), "--bridge", str(bridge), "--plan", str(plan_path), "--output", str(output), "--report", str(build_report), "--manifest", str(manifest)]
            for path in plan["requiredDeferredAcceptances"]:
                build_args.extend(["--accept-deferred-path", path])
            self.assertEqual(rt.main(build_args), 0)
            self.assertEqual(rt.main(["validate", "--input", str(output), "--output", str(validation), "--manifest", str(manifest)]), 0)
            self.assertEqual(rt.main(["pack", "--input", str(output), "--output", str(packed), "--report", str(pack_report), "--manifest", str(manifest)]), 0)
            self.assertEqual(rt.main(["validate-bundle", "--manifest", str(manifest), "--report", str(final_bundle)]), 0)
            report = rt.load_json(str(final_bundle))
            self.assertTrue(report["valid"])
            self.assertEqual(report["stage"], "final")
            self.assertTrue(report["liveRestoreBlocked"])
            self.assertEqual(len(rt.records_from_document(rt.load_json(str(output)))), 20)

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_pack_appends_exact_raw_metadata_tail(self) -> None:
        records = fixture_records()
        with tempfile.TemporaryDirectory() as temp_dir:
            clean = Path(temp_dir) / "clean.json"
            backup = Path(temp_dir) / "backup.json"
            clean.write_text(json.dumps(records), encoding="utf-8")
            report = rt.pack_backup(clean, backup)
            payload = backup.read_bytes()
            expected_tail = b"%backup_metadata_size=104%" + __import__("base64").b64encode(
                b'{"projectUuid":"00000000-0000-0000-0000-000000000000","isFileCompressed":true}'
            )
            self.assertTrue(payload.endswith(expected_tail))
            self.assertEqual(report["metadataTailBytes"], 130)
            compressed = Path(temp_dir) / "payload.zst"
            compressed.write_bytes(payload[:-130])
            result = subprocess.run([shutil.which("zstd"), "-q", "-d", "-c", str(compressed)], check=True, stdout=subprocess.PIPE)
            self.assertEqual(json.loads(result.stdout), records)


if __name__ == "__main__":
    unittest.main()
