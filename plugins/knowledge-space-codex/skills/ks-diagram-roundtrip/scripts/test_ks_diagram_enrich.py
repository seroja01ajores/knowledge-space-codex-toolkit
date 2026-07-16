#!/usr/bin/env python3
"""Synthetic tests for the portable Diagramm enrichment mapper."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import ks_diagram_enrich as enrich
import ks_diagram_roundtrip as rt
import ks_roundtrip_io as rio


PROJECT = "10000000-0000-4000-8000-000000000001"
CLASS_A = "10000000-0000-4000-8000-000000000010"
CLASS_B = "10000000-0000-4000-8000-000000000020"
RELATION = "10000000-0000-4000-8000-000000000030"
HELPER_SOURCE = "10000000-0000-4000-8000-000000000031"
HELPER_TARGET = "10000000-0000-4000-8000-000000000032"
FOLDER_TREE = "20000000-0000-4000-8000-000000000001"
TREE_A = "20000000-0000-4000-8000-000000000010"
TREE_B = "20000000-0000-4000-8000-000000000020"
TREE_RELATION = "20000000-0000-4000-8000-000000000030"
INDICATOR_CALCULATED = "50000000-0000-4000-8000-000000000001"
INDICATOR_ATTRIBUTE = "50000000-0000-4000-8000-000000000002"
INDICATOR_LOADED = "50000000-0000-4000-8000-000000000003"
FORMULA = "50000000-0000-4000-8000-000000000010"
FORMULA_ELEMENT = "50000000-0000-4000-8000-000000000011"
INTEGRATION = "60000000-0000-4000-8000-000000000001"
OPERATION = "60000000-0000-4000-8000-000000000010"
INTEGRATION_RELATION = "60000000-0000-4000-8000-000000000020"
SOURCE_SHA = "a" * 64
STAMP = "2000-01-02T03:04:05+00:00"


def _class_record(
    entity_uuid: str,
    name: str,
    source: str | None,
    target: str | None,
    relations: list[str],
    *,
    helper: bool = False,
    parent: str | None = None,
) -> dict:
    return {
        "UUID": entity_uuid,
        "ParentRelationUUID": parent,
        "Group": "class",
        "Type": "class",
        "Data": {
            "uuid": entity_uuid,
            "name": name,
            "description": f"Synthetic {name}",
            "relatedSourceUuid": source,
            "relatedDestinationUuid": target,
            "objectEntityCategory": "undefined" if helper else "prod",
            "storageType": "regular",
            "sourceObjectsLimit": 0,
            "destinationObjectsLimit": 0,
            "strictRelation": False,
            "relations": [{"uuid": item} for item in relations],
        },
    }


def _tree_record(
    tree_uuid: str, tree_type: str, reference_uuid: str | None, parent_uuid: str | None
) -> dict:
    data = {
        "uuid": tree_uuid,
        "type": tree_type,
        "parentUuid": parent_uuid,
    }
    if reference_uuid is not None:
        data["referenceUuid"] = reference_uuid
    return {
        "UUID": tree_uuid,
        "Group": "class",
        "Type": "tree",
        "Data": data,
    }


def _class_l10n(record_uuid: str, entity_uuid: str, name: str) -> dict:
    return {
        "UUID": record_uuid,
        "Group": "class",
        "Type": "classL10n",
        "Data": {
            "uuid": record_uuid,
            "classUuid": entity_uuid,
            "code": "ru_RU",
            "name": name,
        },
    }


def _indicator_records(
    indicator_uuid: str,
    owner_uuid: str,
    name: str,
    data_type: str,
    tree_uuid: str,
    tree_parent_uuid: str,
) -> list[dict]:
    return [
        {
            "UUID": indicator_uuid,
            "Group": "class",
            "Type": "indicator",
            "Data": {
                "uuid": indicator_uuid,
                "classUuid": owner_uuid,
                "name": name,
                "dataType": data_type,
                "valueType": "sum" if data_type == "number" else "none",
                "description": f"Synthetic {name}",
            },
        },
        _tree_record(tree_uuid, "indicator", indicator_uuid, tree_parent_uuid),
        {
            "UUID": tree_uuid[:-1] + "9",
            "Group": "class",
            "Type": "indicatorL10n",
            "Data": {
                "uuid": tree_uuid[:-1] + "9",
                "indicatorUuid": indicator_uuid,
                "code": "ru_RU",
                "name": name,
            },
        },
    ]


def synthetic_read_records() -> list[dict]:
    records = [
        _class_record(CLASS_A, "Class A", None, None, [HELPER_SOURCE, RELATION]),
        _class_record(CLASS_B, "Class B", None, None, [RELATION, HELPER_TARGET]),
        _class_record(
            HELPER_SOURCE,
            "[[_relation_]]_A_to_R",
            CLASS_A,
            RELATION,
            [],
            helper=True,
            parent=CLASS_A,
        ),
        _class_record(
            RELATION,
            "A to B",
            CLASS_A,
            CLASS_B,
            [HELPER_SOURCE, HELPER_TARGET],
            parent=CLASS_B,
        ),
        _class_record(
            HELPER_TARGET,
            "[[_relation_]]_R_to_B",
            RELATION,
            CLASS_B,
            [],
            helper=True,
            parent=CLASS_B,
        ),
        _tree_record(FOLDER_TREE, "folder", None, None),
        _tree_record(TREE_A, "class", CLASS_A, FOLDER_TREE),
        _tree_record(TREE_B, "class", CLASS_B, FOLDER_TREE),
        _tree_record(TREE_RELATION, "class", RELATION, TREE_A),
        _class_l10n("30000000-0000-4000-8000-000000000010", CLASS_A, "Class A"),
        _class_l10n("30000000-0000-4000-8000-000000000020", CLASS_B, "Class B"),
        _class_l10n(
            "30000000-0000-4000-8000-000000000030", RELATION, "A to B"
        ),
        {
            "UUID": "30000000-0000-4000-8000-000000000001",
            "Group": "class",
            "Type": "folderL10n",
            "Data": {
                "uuid": "30000000-0000-4000-8000-000000000001",
                "folderUuid": FOLDER_TREE,
                "code": "ru_RU",
                "name": "Synthetic folder",
            },
        },
        {
            "UUID": PROJECT,
            "Group": "project",
            "Type": "project",
            "Data": {
                "uuid": PROJECT,
                "name": "Synthetic project",
                "description": "Synthetic fixture",
                "createdAt": "2000-01-01T00:00:00Z",
                "updatedAt": "2000-01-01T00:00:00Z",
            },
        },
    ]
    records.extend(
        _indicator_records(
            INDICATOR_CALCULATED,
            CLASS_A,
            "Calculated metric",
            "number",
            "51000000-0000-4000-8000-000000000001",
            TREE_A,
        )
    )
    records.extend(
        _indicator_records(
            INDICATOR_ATTRIBUTE,
            CLASS_B,
            "Text attribute",
            "string",
            "52000000-0000-4000-8000-000000000001",
            TREE_B,
        )
    )
    records.extend(
        _indicator_records(
            INDICATOR_LOADED,
            RELATION,
            "Loaded metric",
            "number",
            "53000000-0000-4000-8000-000000000001",
            TREE_RELATION,
        )
    )
    records.extend(
        [
            {
                "UUID": FORMULA,
                "Group": "class",
                "Type": "formula",
                "Data": {
                    "uuid": FORMULA,
                    "indicatorUuid": INDICATOR_CALCULATED,
                    "classUuid": CLASS_A,
                    "type": "regular",
                    "enabled": True,
                    "isVersion": False,
                    "elements": [],
                },
            },
            {
                "UUID": FORMULA_ELEMENT,
                "Group": "class",
                "Type": "formulaElement",
                "Data": {
                    "uuid": FORMULA_ELEMENT,
                    "formulaUuid": FORMULA,
                    "indicatorUuid": INDICATOR_ATTRIBUTE,
                },
            },
        ]
    )
    raw_integration_records = [
        {
            "UUID": INTEGRATION,
            "Name": "wrapper must be removed",
            "Group": "integrator",
            "Type": "integration",
            "Data": {
                "uuid": INTEGRATION,
                "name": "Synthetic inbound",
                "direction": "input",
                "password": "must-not-survive",
            },
        },
        {
            "UUID": OPERATION,
            "Group": "integrator",
            "Type": "integrationOperation",
            "Data": {
                "uuid": OPERATION,
                "name": "Synthetic load",
                "integrationUuid": INTEGRATION,
                "disabled": False,
                "customQuery": "must-not-survive",
            },
        },
        {
            "UUID": INTEGRATION_RELATION,
            "Group": "integrator",
            "Type": "integrationRelation",
            "Data": {
                "uuid": INTEGRATION_RELATION,
                "operationUuid": OPERATION,
                "internalField": INDICATOR_LOADED,
                "isIndicator": True,
                "isActive": True,
                "settings": {"token": "must-not-survive"},
            },
        },
    ]
    records.extend(
        rio.sanitize_integration_record(record)[0]
        for record in raw_integration_records
    )
    return records


def read_model(
    records: list[dict], *, include_stats: bool, source_sha: str = SOURCE_SHA
) -> dict:
    source_counts = {"object/object": 3}
    class_stats = rio.build_class_stats(
        records,
        {
            CLASS_A: 2,
            CLASS_B: 0,
            RELATION: 1,
            HELPER_SOURCE: 0,
            HELPER_TARGET: 0,
        },
        source_backup_sha256=source_sha,
    )
    validation = rio.validate_diagram_read_records(
        records,
        class_stats=class_stats if include_stats else None,
        source_type_counts=source_counts if include_stats else None,
        source_sha256=source_sha,
    )
    if not validation["valid"]:
        raise AssertionError(validation["errors"])
    value = {
        "format": rio.DIAGRAM_READ_FORMAT,
        "formatVersion": enrich.FORMAT_VERSION,
        "profile": rio.DIAGRAM_READ_PROFILE,
        "createdAt": STAMP,
        "readOnly": True,
        "restorePayload": False,
        "liveRestoreBlocked": True,
        "source": {
            "kind": "synthetic-test",
            "projectUuid": PROJECT,
            "sha256": source_sha,
        },
        "sourceCounts": source_counts,
        "selectedRecordCount": len(records),
        "selectedCounts": validation["counts"],
        "validation": validation,
        "records": records,
    }
    if include_stats:
        value["classStats"] = class_stats
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class Fixture:
    def __init__(self, root: Path) -> None:
        records = synthetic_read_records()
        structural_records = [
            record for record in records if rio.is_structural_record(record)
        ]
        self.layout_value, self.bridge_value, _ = rt.from_ks(structural_records)
        self.source = root / "source-read.json"
        self.stats = root / "stats-read.json"
        self.layout = root / "layout.json"
        self.bridge = root / "bridge.json"
        self.model = root / "enriched.json"
        self.sidecar = root / "sidecar.json"
        self.report = root / "build-report.json"
        write_json(self.source, read_model(records, include_stats=False))
        write_json(self.stats, read_model(records, include_stats=True))
        write_json(self.layout, self.layout_value)
        write_json(self.bridge, self.bridge_value)

    def build(self) -> dict:
        return enrich.build_artifacts(
            source=self.source,
            stats_source=self.stats,
            layout=self.layout,
            bridge=self.bridge,
            output=self.model,
            sidecar=self.sidecar,
            report=self.report,
            generated_at=STAMP,
        )


class EnrichmentTests(unittest.TestCase):
    def test_build_and_validate_complete_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Fixture(Path(temp_dir))
            report = fixture.build()
            model = json.loads(fixture.model.read_text(encoding="utf-8"))
            sidecar = json.loads(fixture.sidecar.read_text(encoding="utf-8"))
            class_a = next(
                item for item in model["classes"] if item["id"] == f"ks-class:{CLASS_A}"
            )
            class_b = next(
                item for item in model["classes"] if item["id"] == f"ks-class:{CLASS_B}"
            )
            relation = model["relationships"][0]
            calculated = class_a["indicators"][0]
            attribute = class_b["indicators"][0]
            loaded = relation["indicators"][0]

            self.assertTrue(report["valid"])
            self.assertEqual(model["schemaVersion"], "1.2")
            self.assertEqual(class_a["objectCount"], 2)
            self.assertEqual(class_b["objectCount"], 0)
            self.assertTrue(class_a["ksProperties"])
            self.assertEqual(calculated["kind"], "calculated")
            self.assertEqual(
                calculated["dependencies"],
                [f"ks-indicator:{INDICATOR_ATTRIBUTE}"],
            )
            self.assertEqual(
                calculated["sourceConfig"]["formulaElementUuids"],
                [FORMULA_ELEMENT],
            )
            self.assertEqual(
                attribute["sourceConfig"]["presentationRole"], "attribute"
            )
            self.assertEqual(loaded["kind"], "loaded")
            self.assertFalse(sidecar["containsCredentials"])
            self.assertFalse(sidecar["containsObjectRecords"])
            self.assertNotIn("must-not-survive", json.dumps(sidecar))
            self.assertEqual(len(report["hashes"]["diagramSha256"]), 64)

            validation = enrich.validate_artifacts(
                source=fixture.source,
                stats_source=fixture.stats,
                layout=fixture.layout,
                bridge=fixture.bridge,
                model=fixture.model,
                sidecar=fixture.sidecar,
            )
            self.assertTrue(validation["valid"], validation["errors"])

    def test_validate_rejects_tampered_object_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Fixture(Path(temp_dir))
            fixture.build()
            model = json.loads(fixture.model.read_text(encoding="utf-8"))
            model["classes"][0]["objectCount"] += 1
            write_json(fixture.model, model)

            validation = enrich.validate_artifacts(
                source=fixture.source,
                stats_source=fixture.stats,
                layout=fixture.layout,
                bridge=fixture.bridge,
                model=fixture.model,
                sidecar=fixture.sidecar,
            )
            self.assertFalse(validation["valid"])
            self.assertIn("objectCount", "\n".join(validation["errors"]))

    def test_validate_rejects_sensitive_sidecar_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Fixture(Path(temp_dir))
            fixture.build()
            sidecar = json.loads(fixture.sidecar.read_text(encoding="utf-8"))
            sidecar["password"] = "synthetic-secret"
            write_json(fixture.sidecar, sidecar)
            validation = enrich.validate_artifacts(
                source=fixture.source,
                stats_source=fixture.stats,
                layout=fixture.layout,
                bridge=fixture.bridge,
                model=fixture.model,
                sidecar=fixture.sidecar,
            )
            self.assertFalse(validation["valid"])
            self.assertIn("forbidden", "\n".join(validation["errors"]))

    def test_build_rejects_source_mismatch_before_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Fixture(Path(temp_dir))
            records = synthetic_read_records()
            write_json(
                fixture.stats,
                read_model(records, include_stats=True, source_sha="b" * 64),
            )
            with self.assertRaisesRegex(enrich.EnrichmentError, "Source mismatch"):
                fixture.build()
            self.assertFalse(fixture.model.exists())
            self.assertFalse(fixture.sidecar.exists())

    def test_project_structural_edits_preserves_local_and_new_entities(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = Fixture(root)
            fixture.build()
            edited_path = root / "edited.json"
            projected_path = root / "projected.json"
            projection_report_path = root / "projection-report.json"
            edited = json.loads(fixture.model.read_text(encoding="utf-8"))
            edited["classes"][0]["position"] = {"x": 777, "y": 888}
            edited["frames"] = [
                {
                    "id": "local-frame",
                    "name": "Local frame",
                    "color": "#123abc",
                    "position": {"x": 0, "y": 0},
                    "size": {"width": 500, "height": 400},
                }
            ]
            new_class = {
                "id": "local-class",
                "name": "Local class",
                "description": "",
                "stereotype": "",
                "attributes": [
                    {
                        "id": "local-attribute",
                        "name": "Local attribute",
                        "dataType": "string",
                        "required": False,
                        "description": "",
                        "knowledgeSpaceNotes": "",
                    }
                ],
                "indicators": [
                    {
                        "id": "local-indicator",
                        "ownerType": "class",
                        "ownerId": "local-class",
                        "name": "Local indicator",
                        "kind": "input",
                        "valueType": "number",
                        "unit": "",
                        "description": "",
                        "dependencies": [],
                        "knowledgeSpaceNotes": "",
                    }
                ],
                "ksProperties": [],
                "position": {"x": 1000, "y": 1000},
                "size": {"width": 260, "height": 180},
                "notes": "",
            }
            edited["classes"].append(new_class)
            edited["relationships"].append(
                {
                    "id": "local-relation",
                    "sourceClassId": edited["classes"][0]["id"],
                    "targetClassId": "local-class",
                    "type": "association",
                    "name": "Local relation",
                    "description": "",
                    "direction": "source_to_target",
                    "cardinality": "* → *",
                    "indicators": [
                        {
                            "id": "local-relation-indicator",
                            "ownerType": "relationship",
                            "ownerId": "local-relation",
                            "name": "Local relationship indicator",
                            "kind": "input",
                            "valueType": "number",
                            "unit": "",
                            "description": "",
                            "dependencies": [],
                            "knowledgeSpaceNotes": "",
                        }
                    ],
                    "ksProperties": [],
                    "notes": "",
                }
            )
            write_json(edited_path, edited)
            report = enrich.project_structural_edits(
                structural_baseline=fixture.layout,
                enriched_baseline=fixture.model,
                edited=edited_path,
                bridge=fixture.bridge,
                output=projected_path,
                report=projection_report_path,
            )
            projected = json.loads(projected_path.read_text(encoding="utf-8"))
            existing = next(
                item
                for item in projected["classes"]
                if item["id"] == fixture.layout_value["classes"][0]["id"]
            )
            projected_new = next(
                item for item in projected["classes"] if item["id"] == "local-class"
            )
            self.assertEqual(existing["position"], {"x": 777, "y": 888})
            self.assertEqual(existing["indicators"], [])
            self.assertNotIn("objectCount", existing)
            self.assertEqual(projected_new["indicators"][0]["id"], "local-indicator")
            self.assertEqual(projected["frames"], edited["frames"])
            self.assertEqual(
                report["preservedForStructuralDiff"]["newClassIds"],
                ["local-class"],
            )
            self.assertEqual(
                report["preservedForStructuralDiff"]["newRelationshipIds"],
                ["local-relation"],
            )

    def test_project_structural_edits_rejects_read_only_indicator_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = Fixture(root)
            fixture.build()
            edited_path = root / "edited.json"
            edited = json.loads(fixture.model.read_text(encoding="utf-8"))
            edited["classes"][0]["indicators"][0]["name"] = "Tampered"
            write_json(edited_path, edited)
            with self.assertRaisesRegex(
                enrich.EnrichmentError, "Read-only enrichment changed"
            ):
                enrich.project_structural_edits(
                    structural_baseline=fixture.layout,
                    enriched_baseline=fixture.model,
                    edited=edited_path,
                    bridge=fixture.bridge,
                    output=root / "projected.json",
                    report=root / "projection-report.json",
                )

    def test_cli_parser_exposes_all_three_commands(self) -> None:
        parser = enrich.build_parser()
        for command in ("build", "validate", "project-structural-edits"):
            with self.subTest(command=command):
                with self.assertRaises(SystemExit) as context:
                    parser.parse_args([command, "--help"])
                self.assertEqual(context.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
