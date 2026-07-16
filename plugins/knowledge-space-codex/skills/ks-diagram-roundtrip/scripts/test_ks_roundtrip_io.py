#!/usr/bin/env python3
"""Streaming backup I/O and manifest tests."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ks_roundtrip_io as rio
import ks_diagram_roundtrip as rt


def relation_fixture_records() -> list[dict]:
    project_uuid = "10000000-0000-4000-8000-000000000001"
    class_a = "10000000-0000-4000-8000-000000000010"
    class_b = "10000000-0000-4000-8000-000000000020"
    relation = "10000000-0000-4000-8000-000000000030"
    helper_s = "10000000-0000-4000-8000-000000000031"
    helper_t = "10000000-0000-4000-8000-000000000032"
    folder_tree = "20000000-0000-4000-8000-000000000001"
    tree_a = "20000000-0000-4000-8000-000000000010"
    tree_b = "20000000-0000-4000-8000-000000000020"
    tree_r = "20000000-0000-4000-8000-000000000030"

    def class_record(
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
                "relatedSourceUuid": source,
                "relatedDestinationUuid": target,
                "objectEntityCategory": "undefined" if helper else "prod",
                "relations": [{"uuid": item} for item in relations],
                "unknownStructuralField": {"must": "survive"},
            },
        }

    def tree_record(tree_uuid: str, reference_uuid: str, parent_uuid: str) -> dict:
        return {
            "UUID": tree_uuid,
            "Group": "class",
            "Type": "tree",
            "Data": {
                "uuid": tree_uuid,
                "type": "class",
                "referenceUuid": reference_uuid,
                "parentUuid": parent_uuid,
            },
        }

    def l10n_record(record_uuid: str, entity_uuid: str, name: str) -> dict:
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

    return [
        class_record(class_a, "A", None, None, [helper_s, relation]),
        class_record(class_b, "B", None, None, [relation, helper_t]),
        class_record(
            helper_s,
            "[[_relation_]]_A_to_R",
            class_a,
            relation,
            [],
            helper=True,
            parent=class_a,
        ),
        class_record(
            relation,
            "A to B",
            class_a,
            class_b,
            [helper_s, helper_t],
            parent=class_b,
        ),
        class_record(
            helper_t,
            "[[_relation_]]_R_to_B",
            relation,
            class_b,
            [],
            helper=True,
            parent=class_b,
        ),
        {
            "UUID": folder_tree,
            "Group": "class",
            "Type": "tree",
            "Data": {
                "uuid": folder_tree,
                "type": "folder",
                "parentUuid": None,
            },
        },
        tree_record(tree_a, class_a, folder_tree),
        tree_record(tree_b, class_b, folder_tree),
        tree_record(tree_r, relation, tree_a),
        l10n_record("30000000-0000-4000-8000-000000000010", class_a, "A"),
        l10n_record("30000000-0000-4000-8000-000000000020", class_b, "B"),
        l10n_record(
            "30000000-0000-4000-8000-000000000030", relation, "A to B"
        ),
        {
            "UUID": "30000000-0000-4000-8000-000000000001",
            "Group": "class",
            "Type": "folderL10n",
            "Data": {
                "uuid": "30000000-0000-4000-8000-000000000001",
                "folderUuid": folder_tree,
                "code": "ru_RU",
                "name": "Folder",
            },
        },
        {
            "UUID": project_uuid,
            "Group": "project",
            "Type": "project",
            "Data": {"uuid": project_uuid, "name": "Fixture"},
        },
        {
            "UUID": "40000000-0000-4000-8000-000000000001",
            "Group": "dataset",
            "Type": "data",
            "Data": {
                "uuid": "40000000-0000-4000-8000-000000000001",
                "businessPayload": "must-not-survive",
            },
        },
    ]


def diagram_read_fixture_records() -> list[dict]:
    records = relation_fixture_records()
    indicator_uuid = "50000000-0000-4000-8000-000000000001"
    formula_uuid = "50000000-0000-4000-8000-000000000010"
    integration_uuid = "60000000-0000-4000-8000-000000000001"
    operation_uuid = "60000000-0000-4000-8000-000000000010"
    records.extend(
        [
            {
                "UUID": indicator_uuid,
                "Group": "class",
                "Type": "indicator",
                "Data": {
                    "uuid": indicator_uuid,
                    "classUuid": "10000000-0000-4000-8000-000000000010",
                    "name": "Loaded KPI",
                    "dataType": "number",
                    "valueType": "max",
                    "formulas": [{"uuid": formula_uuid}],
                },
            },
            {
                "UUID": "50000000-0000-4000-8000-000000000002",
                "Group": "class",
                "Type": "tree",
                "Data": {
                    "uuid": "50000000-0000-4000-8000-000000000002",
                    "type": "indicator",
                    "referenceUuid": indicator_uuid,
                    "parentUuid": "20000000-0000-4000-8000-000000000010",
                },
            },
            {
                "UUID": "50000000-0000-4000-8000-000000000003",
                "Group": "class",
                "Type": "indicatorL10n",
                "Data": {
                    "uuid": "50000000-0000-4000-8000-000000000003",
                    "indicatorUuid": indicator_uuid,
                    "code": "ru_RU",
                    "name": "Показатель",
                },
            },
            {
                "UUID": "50000000-0000-4000-8000-000000000004",
                "Group": "class",
                "Type": "indicatorUnitL10n",
                "Data": {
                    "uuid": "50000000-0000-4000-8000-000000000004",
                    "indicatorUuid": indicator_uuid,
                    "code": "ru_RU",
                    "unit": "%",
                },
            },
            {
                "UUID": "50000000-0000-4000-8000-000000000005",
                "Group": "class",
                "Type": "indicatorDimension",
                "Data": {
                    "uuid": "50000000-0000-4000-8000-000000000005",
                    "indicatorUuid": indicator_uuid,
                    "dictionaryUuid": "50000000-0000-4000-8000-000000000099",
                },
            },
            {
                "UUID": formula_uuid,
                "Group": "class",
                "Type": "formula",
                "Data": {
                    "uuid": formula_uuid,
                    "indicatorUuid": indicator_uuid,
                    "classUuid": "10000000-0000-4000-8000-000000000010",
                    "type": "regular",
                    "enabled": True,
                    "isVersion": False,
                    "tokens": [],
                },
            },
            {
                "UUID": "50000000-0000-4000-8000-000000000011",
                "Group": "class",
                "Type": "formulaElement",
                "Data": {
                    "uuid": "50000000-0000-4000-8000-000000000011",
                    "formulaUuid": formula_uuid,
                    "indicatorUuid": indicator_uuid,
                },
            },
            {
                "UUID": integration_uuid,
                "Name": "wrapper name is deliberately dropped",
                "Group": "integrator",
                "Type": "integration",
                "Data": {
                    "uuid": integration_uuid,
                    "name": "Safe provenance name",
                    "sourcesUuids": ["60000000-0000-4000-8000-000000000099"],
                    "direction": "import",
                    "auth": "must-not-survive-auth",
                    "password": "must-not-survive-password",
                },
            },
            {
                "UUID": operation_uuid,
                "Group": "integrator",
                "Type": "integrationOperation",
                "Data": {
                    "uuid": operation_uuid,
                    "name": "Load indicator",
                    "integrationUuid": integration_uuid,
                    "classUuid": "10000000-0000-4000-8000-000000000010",
                    "isGeneratesData": True,
                    "customQuery": "select secret from private_table",
                    "options": {"token": "must-not-survive-token"},
                    "variables": [{"password": "must-not-survive-variable"}],
                },
            },
            {
                "UUID": "60000000-0000-4000-8000-000000000020",
                "Group": "integrator",
                "Type": "integrationRelation",
                "Data": {
                    "uuid": "60000000-0000-4000-8000-000000000020",
                    "operationUuid": operation_uuid,
                    "sourceUuid": "60000000-0000-4000-8000-000000000099",
                    "internalField": indicator_uuid,
                    "isIndicator": True,
                    "isActive": True,
                    "input": [
                        {
                            "type": "source",
                            "sourceUuid": "60000000-0000-4000-8000-000000000099",
                            "variableUuid": "must-not-survive-variable-uuid",
                            "constant": "must-not-survive-constant",
                        }
                    ],
                    "output": {
                        "type": "indicator",
                        "sourceUuid": indicator_uuid,
                        "variableUuid": "must-not-survive-output-variable",
                    },
                    "settings": {"body": "must-not-survive-body"},
                },
            },
            {
                "UUID": "60000000-0000-4000-8000-000000000030",
                "Group": "integrator",
                "Type": "integrationConnectionParam",
                "Data": {
                    "uuid": "60000000-0000-4000-8000-000000000030",
                    "password": "must-not-survive-connection-password",
                },
            },
            {
                "UUID": "70000000-0000-4000-8000-000000000001",
                "Group": "object",
                "Type": "object",
                "Data": {
                    "uuid": "70000000-0000-4000-8000-000000000001",
                    "classUuid": "10000000-0000-4000-8000-000000000010",
                    "name": "must-not-survive-object-name-1",
                    "businessPayload": "must-not-survive-object-value-1",
                },
            },
            {
                "UUID": "70000000-0000-4000-8000-000000000002",
                "Group": "object",
                "Type": "object",
                "Data": {
                    "uuid": "70000000-0000-4000-8000-000000000002",
                    "classUuid": "10000000-0000-4000-8000-000000000010",
                    "name": "must-not-survive-object-name-2",
                    "businessPayload": "must-not-survive-object-value-2",
                },
            },
            {
                "UUID": "70000000-0000-4000-8000-000000000003",
                "Group": "object",
                "Type": "object",
                "Data": {
                    "uuid": "70000000-0000-4000-8000-000000000003",
                    "classUuid": "10000000-0000-4000-8000-000000000030",
                    "name": "must-not-survive-relation-object-name",
                    "businessPayload": "must-not-survive-relation-object-value",
                },
            },
        ]
    )
    return records


def write_packed_backup(root: Path, records: list[dict]) -> tuple[Path, bytes]:
    clean = root / "clean.json"
    compressed = root / "payload.zst"
    backup = root / "source.backup"
    clean.write_text(json.dumps(records), encoding="utf-8")
    subprocess.run(
        [shutil.which("zstd"), "-q", "-f", str(clean), "-o", str(compressed)],
        check=True,
    )
    metadata = {"projectUuid": rio.ZERO_UUID, "isFileCompressed": True}
    encoded = base64.b64encode(
        json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    )
    tail = f"%backup_metadata_size={len(encoded)}%".encode("ascii") + encoded
    backup.write_bytes(compressed.read_bytes() + tail)
    return backup, tail


class BackupIOTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_slice_packed_read_model_is_complete_sanitized_and_not_restore_input(
        self,
    ) -> None:
        records = diagram_read_fixture_records()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, _ = write_packed_backup(root, records)
            output = root / "diagram-read.json"
            report = rio.slice_packed_diagram_read_model(backup, output)
            value = json.loads(output.read_text(encoding="utf-8"))
            rendered_records = json.dumps(value["records"], ensure_ascii=False)

            self.assertEqual(value["format"], rio.DIAGRAM_READ_FORMAT)
            self.assertEqual(value["profile"], rio.DIAGRAM_READ_PROFILE)
            self.assertTrue(value["readOnly"])
            self.assertFalse(value["restorePayload"])
            self.assertTrue(value["liveRestoreBlocked"])
            self.assertTrue(value["validation"]["valid"])
            self.assertEqual(value["validation"], report["validation"])
            self.assertEqual(report["validation"]["counts"]["indicators"], 1)
            self.assertEqual(report["validation"]["counts"]["formulas"], 1)
            self.assertEqual(report["validation"]["counts"]["formulaElements"], 1)
            self.assertEqual(
                report["validation"]["counts"]["objectRecordsAggregated"], 3
            )
            self.assertEqual(report["validation"]["counts"]["classStats"], 5)
            self.assertEqual(report["validation"]["counts"]["integrationProvenance"], 3)
            self.assertEqual(
                value["selection"]["integrationProvenance"]["selectedRecords"],
                3,
            )
            self.assertGreater(
                value["selection"]["integrationProvenance"]["removedFieldCount"],
                0,
            )
            for forbidden in (
                "must-not-survive",
                "customQuery",
                "password",
                "variables",
                "settings",
                "integrationConnectionParam",
                "must-not-survive-object",
            ):
                self.assertNotIn(forbidden, rendered_records)
            class_stats = value["classStats"]["byKsEntityUuid"]
            ordinary_stats = class_stats[
                "10000000-0000-4000-8000-000000000010"
            ]
            relation_stats = class_stats[
                "10000000-0000-4000-8000-000000000030"
            ]
            empty_stats = class_stats[
                "10000000-0000-4000-8000-000000000020"
            ]
            self.assertEqual(ordinary_stats["objectCount"], 2)
            self.assertEqual(ordinary_stats["displayIndicatorCount"], 1)
            self.assertEqual(ordinary_stats["derivedFormulaCount"], 1)
            self.assertEqual(ordinary_stats["actualFormulaRecordCount"], 1)
            self.assertEqual(ordinary_stats["activeRegularFormulaRecordCount"], 1)
            self.assertEqual(ordinary_stats["actualCalculatedIndicatorCount"], 1)
            self.assertEqual(relation_stats["objectCount"], 1)
            self.assertEqual(empty_stats["objectCount"], 0)
            self.assertEqual(value["sourceCounts"]["object/object"], 3)
            self.assertEqual(
                value["classStats"]["objectCountDigest"]["sourceBackupSha256"],
                value["source"]["sha256"],
            )
            self.assertEqual(
                len(value["classStats"]["objectCountDigest"]["sha256"]),
                64,
            )
            relation = next(
                record
                for record in value["records"]
                if record.get("Type") == "integrationRelation"
            )
            self.assertEqual(
                relation["Data"]["internalField"],
                "50000000-0000-4000-8000-000000000001",
            )
            self.assertEqual(
                relation["Data"]["input"],
                [
                    {
                        "type": "source",
                        "sourceUuid": "60000000-0000-4000-8000-000000000099",
                    }
                ],
            )
            with self.assertRaisesRegex(rt.RoundTripError, "read-only enrichment"):
                rt.records_from_document(value)
            self.assertEqual(rt.diagram_read_records_from_document(value), value["records"])

            tampered = json.loads(json.dumps(value))
            tampered["classStats"]["byKsEntityUuid"][
                "10000000-0000-4000-8000-000000000010"
            ]["derivedFormulaCount"] = 99
            tampered_report = rio.validate_diagram_read_records(
                tampered["records"],
                class_stats=tampered["classStats"],
                source_type_counts=tampered["sourceCounts"],
                source_sha256=tampered["source"]["sha256"],
            )
            self.assertFalse(tampered_report["valid"])
            self.assertTrue(
                any(
                    "derivedFormulaCount" in error
                    for error in tampered_report["errors"]
                )
            )
            with self.assertRaisesRegex(rt.RoundTripError, "classStats are invalid"):
                rt.diagram_read_records_from_document(tampered)

            redistributed = json.loads(json.dumps(value))
            redistributed_stats = redistributed["classStats"]["byKsEntityUuid"]
            redistributed_stats[
                "10000000-0000-4000-8000-000000000010"
            ]["objectCount"] = 1
            redistributed_stats[
                "10000000-0000-4000-8000-000000000030"
            ]["objectCount"] = 2
            redistributed_report = rio.validate_diagram_read_records(
                redistributed["records"],
                class_stats=redistributed["classStats"],
                source_type_counts=redistributed["sourceCounts"],
                source_sha256=redistributed["source"]["sha256"],
            )
            self.assertFalse(redistributed_report["valid"])
            self.assertTrue(
                any(
                    "objectCountDigest" in error
                    for error in redistributed_report["errors"]
                )
            )
            with self.assertRaisesRegex(rt.RoundTripError, "classStats are invalid"):
                rt.diagram_read_records_from_document(redistributed)

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_slice_packed_read_model_limits_unique_object_class_owners(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, _ = write_packed_backup(root, diagram_read_fixture_records())
            output = root / "diagram-read.json"
            with mock.patch.object(rio, "MAX_OBJECT_CLASS_UUIDS", 1):
                with self.assertRaisesRegex(
                    rio.BackupIOError,
                    "unique object classUuid limit",
                ):
                    rio.slice_packed_diagram_read_model(backup, output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_slice_packed_read_model_cli_writes_metadata_without_restore_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, _ = write_packed_backup(root, diagram_read_fixture_records())
            output = root / "diagram-read.json"
            metadata = root / "diagram-read.metadata.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    rt.main(
                        [
                            "slice-packed-read-model",
                            "--input",
                            str(backup),
                            "--output",
                            str(output),
                            "--metadata-output",
                            str(metadata),
                        ]
                    ),
                    0,
                )
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["profile"], rio.DIAGRAM_READ_PROFILE)
            self.assertFalse(summary["restorePayload"])
            self.assertTrue(summary["liveRestoreBlocked"])
            self.assertFalse((root / "run-manifest.json").exists())
            self.assertTrue(json.loads(metadata.read_text(encoding="utf-8"))["valid"])
            validation_stdout = io.StringIO()
            with contextlib.redirect_stdout(validation_stdout):
                self.assertEqual(
                    rt.main(["validate", "--input", str(output)]),
                    0,
                )
            self.assertTrue(json.loads(validation_stdout.getvalue())["valid"])

    def test_diagram_read_model_requires_immutable_read_only_flags(self) -> None:
        value = {
            "format": rio.DIAGRAM_READ_FORMAT,
            "formatVersion": rio.FORMAT_VERSION,
            "profile": rio.DIAGRAM_READ_PROFILE,
            "readOnly": True,
            "restorePayload": False,
            "liveRestoreBlocked": False,
            "records": [],
        }
        with self.assertRaisesRegex(rt.RoundTripError, "liveRestoreBlocked"):
            rt.diagram_read_records_from_document(value)

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_slice_packed_streams_exact_frame_and_preserves_structural_closure(
        self,
    ) -> None:
        records = relation_fixture_records()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, tail = write_packed_backup(root, records)
            output = root / "structural.json"
            report = rio.slice_packed_backup(backup, output)
            value = json.loads(output.read_text(encoding="utf-8"))
            selected = value["records"]

            self.assertEqual(report["mode"], "packed-stream")
            self.assertEqual(report["recordCount"], len(records))
            self.assertEqual(report["metadataTailBytes"], len(tail))
            self.assertEqual(report["selectedRecordCount"], len(records) - 1)
            self.assertNotIn("dataset/data", [
                f"{item.get('Group')}/{item.get('Type')}" for item in selected
            ])
            self.assertEqual(
                selected[0]["Data"]["unknownStructuralField"],
                {"must": "survive"},
            )
            self.assertTrue(rio.validate_structural_slice(selected) == [])
            self.assertEqual(
                value["source"]["sha256"], report["hashes"]["backupSha256"]
            )

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_slice_packed_cli_records_manifest_without_unpacked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, _ = write_packed_backup(root, relation_fixture_records())
            output = root / "structural.json"
            metadata = root / "source-metadata.json"
            manifest = root / "run-manifest.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = rt.main(
                    [
                        "slice-packed",
                        "--input",
                        str(backup),
                        "--output",
                        str(output),
                        "--metadata-output",
                        str(metadata),
                        "--manifest",
                        str(manifest),
                    ]
                )

            self.assertEqual(exit_code, 0, stdout.getvalue())
            manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest_value["artifacts"]),
                {"sourceBackup", "sourceMetadata", "structuralSource"},
            )
            self.assertNotIn("unpackedSource", manifest_value["artifacts"])
            self.assertEqual(
                manifest_value["state"]["sourceAcquisition"], "packed-stream"
            )
            self.assertTrue(
                json.loads(metadata.read_text(encoding="utf-8"))["valid"]
            )
            diagram = root / "baseline.diagram.json"
            bridge = root / "baseline.bridge.json"
            baseline = root / "baseline.normalized.json"
            validation = root / "baseline.bundle-validation.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    rt.main(
                        [
                            "from-ks",
                            "--input",
                            str(output),
                            "--diagram",
                            str(diagram),
                            "--bridge",
                            str(bridge),
                            "--baseline",
                            str(baseline),
                            "--manifest",
                            str(manifest),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    rt.main(
                        [
                            "validate-bundle",
                            "--manifest",
                            str(manifest),
                            "--report",
                            str(validation),
                        ]
                    ),
                    0,
                )
            validation_value = json.loads(validation.read_text(encoding="utf-8"))
            self.assertTrue(validation_value["valid"])
            self.assertTrue(
                validation_value["checks"]["packedStreamSource"][
                    "sourceLinkMatches"
                ]
            )

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_slice_packed_rejects_truncated_frame_without_replacing_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, tail = write_packed_backup(root, relation_fixture_records())
            packed = backup.read_bytes()
            frame = packed[: -len(tail)]
            backup.write_bytes(frame[:-8] + tail)
            output = root / "structural.json"
            output.write_text("preserve-me", encoding="utf-8")

            with self.assertRaises(rio.BackupIOError):
                rio.slice_packed_backup(backup, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve-me")

    def test_structural_slice_streams_only_the_profile_records(self) -> None:
        records = [
            {"UUID": "p", "Group": "project", "Type": "project", "Data": {"uuid": "p"}},
            {
                "UUID": "c",
                "Group": "class",
                "Type": "class",
                "Data": {"uuid": "c", "relatedSourceUuid": None, "relatedDestinationUuid": None},
            },
            {
                "UUID": "t",
                "Group": "class",
                "Type": "tree",
                "Data": {"uuid": "t", "type": "class", "referenceUuid": "c", "parentUuid": None},
            },
            {
                "UUID": "l",
                "Group": "class",
                "Type": "classL10n",
                "Data": {"uuid": "l", "classUuid": "c", "name": "C"},
            },
            {
                "UUID": "i",
                "Group": "class",
                "Type": "indicator",
                "Data": {},
            },
            {"UUID": "d", "Group": "dataset", "Type": "data", "Data": {}},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "full.json"
            output = Path(temp_dir) / "structural.json"
            source.write_text(json.dumps(records), encoding="utf-8")
            report = rio.slice_structural_records(source, output)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["sourceRecordCount"], 6)
            self.assertEqual(report["selectedRecordCount"], 4)
            self.assertEqual([item["UUID"] for item in value["records"]], ["p", "c", "t", "l"])

    def test_streaming_decoder_rejects_trailing_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "broken.json"
            source.write_text('[{"x": 1}] trailing', encoding="utf-8")
            with self.assertRaisesRegex(rio.BackupIOError, "Unexpected content"):
                list(rio.iter_json_array(source, chunk_size=4))

    def test_streaming_decoder_enforces_array_separators_with_tiny_chunks(self) -> None:
        invalid_values = ("[1 2]", "[1,,2]", "[,1]", "[1,]")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "array.json"
            for value in invalid_values:
                source.write_text(value, encoding="utf-8")
                with self.assertRaises(rio.BackupIOError, msg=value):
                    list(rio.iter_json_array(source, chunk_size=1))
            source.write_text('[{"one":1},{"two":2}]', encoding="utf-8")
            self.assertEqual(
                list(rio.iter_json_array(source, chunk_size=1)),
                [{"one": 1}, {"two": 2}],
            )
            for value, expected in (("[12]", [12]), ("[1.25]", [1.25]), ("[1e10]", [1e10])):
                source.write_text(value, encoding="utf-8")
                self.assertEqual(list(rio.iter_json_array(source, chunk_size=1)), expected)
            source.write_text('[{"n":NaN}]', encoding="utf-8")
            with self.assertRaisesRegex(rio.BackupIOError, "Non-standard"):
                list(rio.iter_json_array(source, chunk_size=1))

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_raw_tail_is_split_and_zstd_frame_is_unpacked(self) -> None:
        project_uuid = "10000000-0000-4000-8000-000000000001"
        records = [
            {
                "UUID": project_uuid,
                "Group": "project",
                "Type": "project",
                "Data": {"uuid": project_uuid},
            }
        ]
        metadata = {"projectUuid": rio.ZERO_UUID, "isFileCompressed": True}
        encoded = base64.b64encode(
            json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        )
        tail = f"%backup_metadata_size={len(encoded)}%".encode("ascii") + encoded
        with tempfile.TemporaryDirectory() as temp_dir:
            clean = Path(temp_dir) / "clean.json"
            compressed = Path(temp_dir) / "payload.zst"
            backup = Path(temp_dir) / "backup.json"
            unpacked = Path(temp_dir) / "unpacked.json"
            clean.write_text(json.dumps(records), encoding="utf-8")
            subprocess.run(
                [shutil.which("zstd"), "-q", "-f", str(clean), "-o", str(compressed)],
                check=True,
            )
            backup.write_bytes(compressed.read_bytes() + tail)
            parts = rio.split_backup_tail(backup)
            report = rio.unpack_backup(backup, unpacked)
            self.assertEqual(parts.metadata, metadata)
            self.assertEqual(parts.metadata_tail_bytes, len(tail))
            self.assertEqual(json.loads(unpacked.read_text(encoding="utf-8")), records)
            self.assertEqual(report["metadata"], metadata)
            self.assertEqual(report["recordCount"], 1)

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_unpack_rejects_collision_and_non_json_before_replacing_output(self) -> None:
        metadata = {"projectUuid": rio.ZERO_UUID, "isFileCompressed": True}
        encoded = base64.b64encode(
            json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        )
        tail = f"%backup_metadata_size={len(encoded)}%".encode("ascii") + encoded
        with tempfile.TemporaryDirectory() as temp_dir:
            clean = Path(temp_dir) / "not-json.txt"
            compressed = Path(temp_dir) / "payload.zst"
            backup = Path(temp_dir) / "backup.json"
            output = Path(temp_dir) / "output.json"
            clean.write_text("not-json", encoding="utf-8")
            subprocess.run(
                [shutil.which("zstd"), "-q", "-f", str(clean), "-o", str(compressed)],
                check=True,
            )
            backup.write_bytes(compressed.read_bytes() + tail)
            original = backup.read_bytes()
            with self.assertRaisesRegex(rio.BackupIOError, "overwrite"):
                rio.unpack_backup(backup, backup)
            self.assertEqual(backup.read_bytes(), original)
            output.write_text("preserve-me", encoding="utf-8")
            with self.assertRaises(rio.BackupIOError):
                rio.unpack_backup(backup, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve-me")

    @unittest.skipUnless(shutil.which("zstd"), "zstd is not installed")
    def test_unpack_requires_real_project_wrapper_and_matching_data_uuid(self) -> None:
        metadata = {"projectUuid": rio.ZERO_UUID, "isFileCompressed": True}
        encoded = base64.b64encode(
            json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        )
        tail = f"%backup_metadata_size={len(encoded)}%".encode("ascii") + encoded
        project_uuid = "10000000-0000-4000-8000-000000000001"
        cases = [
            [
                {
                    "UUID": project_uuid,
                    "Group": "class",
                    "Type": "project",
                    "Data": {"uuid": project_uuid},
                }
            ],
            [
                {
                    "UUID": project_uuid,
                    "Group": "project",
                    "Type": "project",
                    "Data": {"uuid": "10000000-0000-4000-8000-000000000099"},
                }
            ],
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, records in enumerate(cases):
                clean = root / f"clean-{index}.json"
                compressed = root / f"payload-{index}.zst"
                backup = root / f"backup-{index}.json"
                output = root / f"output-{index}.json"
                clean.write_text(json.dumps(records), encoding="utf-8")
                subprocess.run(
                    [shutil.which("zstd"), "-q", "-f", str(clean), "-o", str(compressed)],
                    check=True,
                )
                backup.write_bytes(compressed.read_bytes() + tail)
                with self.assertRaises(rio.BackupIOError):
                    rio.unpack_backup(backup, output)
                self.assertFalse(output.exists())

    def test_slice_rejects_collision_without_touching_source(self) -> None:
        project_uuid = "10000000-0000-4000-8000-000000000001"
        records = [
            {
                "UUID": project_uuid,
                "Group": "project",
                "Type": "project",
                "Data": {"uuid": project_uuid},
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "full.json"
            source.write_text(json.dumps(records), encoding="utf-8")
            original = source.read_bytes()
            with self.assertRaisesRegex(rio.BackupIOError, "overwrite"):
                rio.slice_structural_records(source, source)
            self.assertEqual(source.read_bytes(), original)

    def test_slice_rejects_broken_visible_entity_closure(self) -> None:
        project_uuid = "10000000-0000-4000-8000-000000000001"
        class_uuid = "10000000-0000-4000-8000-000000000002"
        records = [
            {
                "UUID": project_uuid,
                "Group": "project",
                "Type": "project",
                "Data": {"uuid": project_uuid},
            },
            {
                "UUID": class_uuid,
                "Group": "class",
                "Type": "class",
                "Data": {
                    "uuid": class_uuid,
                    "relatedSourceUuid": None,
                    "relatedDestinationUuid": None,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "full.json"
            output = Path(temp_dir) / "slice.json"
            source.write_text(json.dumps(records), encoding="utf-8")
            with self.assertRaisesRegex(rio.BackupIOError, "Structural slice validation"):
                rio.slice_structural_records(source, output)
            self.assertFalse(output.exists())

    def test_manifest_uses_relative_paths_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            artifact = run_dir / "artifacts" / "fixture.json"
            artifact.parent.mkdir()
            artifact.write_text('{"value": 1}\n', encoding="utf-8")
            manifest_path = run_dir / "run-manifest.json"
            manifest = rio.update_manifest(
                manifest_path,
                command="fixture",
                artifacts=[("fixture", artifact)],
            )
            self.assertEqual(manifest["format"], "teamvalue.ks-diagram-run-manifest")
            self.assertEqual(manifest["toolVersion"], "0.3.0")
            self.assertTrue(manifest["liveRestoreBlocked"])
            self.assertTrue(manifest["runId"])
            self.assertEqual(manifest["artifacts"]["fixture"]["path"], "artifacts/fixture.json")
            manifest_bytes = manifest_path.read_bytes()
            rio.update_manifest(
                manifest_path,
                command="fixture",
                artifacts=[("fixture", artifact)],
            )
            self.assertEqual(manifest_path.read_bytes(), manifest_bytes)
            _, errors = rio.verify_manifest_hashes(manifest_path)
            self.assertEqual(errors, [])
            artifact.write_text('{"value": 2}\n', encoding="utf-8")
            _, errors = rio.verify_manifest_hashes(manifest_path)
            self.assertTrue(any("SHA-256 mismatch" in item for item in errors))
            with self.assertRaisesRegex(rio.BackupIOError, "drifted|conflicting content"):
                rio.update_manifest(
                    manifest_path,
                    command="fixture-rerun",
                    artifacts=[("fixture", artifact)],
                )

    def test_manifest_rejects_invalid_existing_identity_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            artifact = run_dir / "fixture.json"
            artifact.write_text("{}\n", encoding="utf-8")
            manifest_path = run_dir / "run-manifest.json"
            rio.update_manifest(
                manifest_path,
                command="fixture",
                artifacts=[("fixture", artifact)],
            )
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["toolVersion"] = "99"
            value["runId"] = "not-a-uuid"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            original = manifest_path.read_bytes()
            with self.assertRaises(rio.BackupIOError):
                rio.update_manifest(
                    manifest_path,
                    command="fixture",
                    artifacts=[("fixture", artifact)],
                )
            self.assertEqual(manifest_path.read_bytes(), original)

    def test_manifest_rejects_self_duplicate_roles_drift_extension_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            artifact = run_dir / "artifact.json"
            second = run_dir / "second.json"
            artifact.write_text("{}\n", encoding="utf-8")
            second.write_text("[]\n", encoding="utf-8")
            manifest_path = run_dir / "run-manifest.json"
            with self.assertRaisesRegex(rio.BackupIOError, "duplicate"):
                rio.update_manifest(
                    manifest_path,
                    command="fixture",
                    artifacts=[("same", artifact), ("same", artifact)],
                )
            rio.update_manifest(
                manifest_path,
                command="fixture",
                artifacts=[("artifact", artifact)],
            )
            with self.assertRaisesRegex(rio.BackupIOError, "record itself"):
                rio.update_manifest(
                    manifest_path,
                    command="self",
                    artifacts=[("manifest", manifest_path)],
                )
            artifact.write_text('{"drift":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(rio.BackupIOError, "drifted"):
                rio.update_manifest(
                    manifest_path,
                    command="extend",
                    artifacts=[("second", second)],
                )
            outside = Path(temp_dir) / "outside-manifest.json"
            outside.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
            link = run_dir / "linked-manifest.json"
            link.symlink_to(outside)
            with self.assertRaisesRegex(rio.BackupIOError, "symlink"):
                rio.verify_manifest_hashes(link)

    def test_pathological_metadata_length_is_controlled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup = Path(temp_dir) / "backup.json"
            backup.write_bytes(
                b"frame%backup_metadata_size=" + (b"9" * 5000) + b"%payload"
            )
            with self.assertRaisesRegex(rio.BackupIOError, "unreasonably large"):
                rio.split_backup_tail(backup)

    def test_manifest_rejects_artifacts_outside_the_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            run_dir.mkdir()
            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(rio.BackupIOError, "inside the manifest"):
                rio.update_manifest(
                    run_dir / "run-manifest.json",
                    command="fixture",
                    artifacts=[("outside", outside)],
                )


if __name__ == "__main__":
    unittest.main()
