#!/usr/bin/env python3
"""Offline, source-bound enrichment of structural Diagramm models.

The tool accepts only the sanitized ``diagram-read-v0.2`` envelope produced by
``ks_roundtrip_io``.  It never calls KS, never performs a restore, and never
retains object records or object values.  A separate sanitized sidecar carries
formula and dependency evidence that is too detailed for the browser model.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import ks_diagram_roundtrip as rt
import ks_roundtrip_io as rio


FORMAT_VERSION = "0.1"
OUTPUT_SCHEMA = "1.2"
MAPPING_PROFILE = "diagram-read-v0.2/enrichment-v0.1"
SIDECAR_FORMAT = "teamvalue.ks-diagram-enrichment-sidecar"
REPORT_FORMAT = "teamvalue.ks-diagram-enrichment-report"
STRUCTURAL_EDIT_REPORT_FORMAT = "teamvalue.ks-diagram-structural-edit-projection"

KS_PROPERTY_LABELS = {
    "uuid": "KS UUID",
    "storageType": "Storage type",
    "backupEntityCategory": "Backup entity category",
    "objectEntityCategory": "Object entity category",
    "restrictionLevelType": "Restriction level",
    "objectsLimitInModel": "Objects limited in model",
    "objectsContainDiagrams": "Objects contain diagrams",
    "diagramTemplateUuid": "Diagram template UUID",
    "relatedSourceUuid": "Relationship source UUID",
    "relatedDestinationUuid": "Relationship destination UUID",
    "sourceObjectsLimit": "Source object limit",
    "destinationObjectsLimit": "Destination object limit",
    "strictRelation": "Strict relationship",
    "replaceOldRelationsType": "Relationship replacement policy",
    "showWarning": "Show warning",
    "storageStructureAppliedAt": "Storage structure applied at",
    "createdAt": "Created in KS",
    "updatedAt": "Updated in KS",
}

SIDECAR_RECORD_TYPES = {
    "indicators": ("class", "indicator"),
    "indicatorL10n": ("class", "indicatorL10n"),
    "indicatorUnitL10n": ("class", "indicatorUnitL10n"),
    "indicatorDimensions": ("class", "indicatorDimension"),
    "formulas": ("class", "formula"),
    "formulaElements": ("class", "formulaElement"),
    "classTree": ("class", "tree"),
}

FORBIDDEN_SIDECAR_KEYS = {
    "apikey",
    "auth",
    "authorization",
    "baseurl",
    "body",
    "certificate",
    "connectionparam",
    "cookie",
    "customquery",
    "headers",
    "host",
    "login",
    "password",
    "privatekey",
    "querypath",
    "secret",
    "token",
}

RELATIONSHIP_TYPES = {
    "association",
    "dependency",
    "aggregation",
    "composition",
    "inheritance",
}
RELATIONSHIP_DIRECTIONS = {
    "none",
    "source_to_target",
    "target_to_source",
    "bidirectional",
}
INDICATOR_KINDS = {"input", "loaded", "calculated"}


class EnrichmentError(RuntimeError):
    """Controlled fail-closed input or integrity error."""


def _reject_json_constant(value: str) -> None:
    raise EnrichmentError(f"Non-standard JSON constant is forbidden: {value}")


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_json_constant)
    except EnrichmentError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnrichmentError(f"Cannot read JSON {path.name}: {exc}") from exc


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _data(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    value = record.get("Data")
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _normalized_key(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _normalized_get(value: dict[str, Any], *names: str) -> Any:
    expected = {_normalized_key(name) for name in names}
    for key, item in value.items():
        if isinstance(key, str) and _normalized_key(key) in expected:
            return item
    return None


def _require_valid(report: dict[str, Any], label: str) -> None:
    if report.get("valid"):
        return
    errors = report.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            message = str(first.get("message") or first)
        else:
            message = str(first)
    else:
        message = "unknown validation error"
    raise EnrichmentError(f"{label} validation failed: {message}")


def _read_model_view(document: Any, label: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise EnrichmentError(f"{label} must be a JSON object")
    if document.get("format") != rio.DIAGRAM_READ_FORMAT:
        raise EnrichmentError(f"{label} format is not {rio.DIAGRAM_READ_FORMAT}")
    if document.get("formatVersion") != FORMAT_VERSION:
        raise EnrichmentError(f"{label} formatVersion is not supported")
    if document.get("profile") != rio.DIAGRAM_READ_PROFILE:
        raise EnrichmentError(f"{label} profile is not {rio.DIAGRAM_READ_PROFILE}")
    if document.get("readOnly") is not True:
        raise EnrichmentError(f"{label} must keep readOnly=true")
    if document.get("restorePayload") is not False:
        raise EnrichmentError(f"{label} must keep restorePayload=false")
    if document.get("liveRestoreBlocked") is not True:
        raise EnrichmentError(f"{label} must keep liveRestoreBlocked=true")

    source = document.get("source")
    if not isinstance(source, dict) or not _is_sha256(source.get("sha256")):
        raise EnrichmentError(f"{label} requires source.sha256")
    records = document.get("records")
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise EnrichmentError(f"{label}.records must be an object array")
    if document.get("selectedRecordCount") not in (None, len(records)):
        raise EnrichmentError(f"{label}.selectedRecordCount differs from records")

    validation = rio.validate_diagram_read_records(
        records,
        class_stats=document.get("classStats"),
        source_type_counts=document.get("sourceCounts"),
        source_sha256=source.get("sha256"),
    )
    _require_valid(validation, label)
    embedded_validation = document.get("validation")
    if isinstance(embedded_validation, dict) and embedded_validation.get("valid") is False:
        raise EnrichmentError(f"{label} embeds an invalid validation report")
    return {
        "document": document,
        "records": records,
        "sourceSha256": source["sha256"],
        "recordsSemanticSha256": rt.semantic_sha256(records),
        "validation": validation,
    }


def _project_uuid(records: list[dict[str, Any]]) -> str:
    projects = [
        record
        for record in records
        if record.get("Group") == "project" and record.get("Type") == "project"
    ]
    if len(projects) != 1:
        raise EnrichmentError(
            f"Read model must contain exactly one project record; found {len(projects)}"
        )
    project_uuid = _data(projects[0]).get("uuid")
    if not isinstance(project_uuid, str) or project_uuid != projects[0].get("UUID"):
        raise EnrichmentError("Project UUID/Data.uuid binding is invalid")
    return project_uuid


def _by_type(
    records: Iterable[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        result[(str(record.get("Group")), str(record.get("Type")))].append(record)
    return result


def _index_by_uuid(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        record_uuid = record.get("UUID")
        if not isinstance(record_uuid, str) or not record_uuid:
            raise EnrichmentError("Every indexed record requires a UUID")
        if record_uuid in result:
            raise EnrichmentError(f"Duplicate record UUID {record_uuid}")
        result[record_uuid] = record
    return result


def _entity_map_entries(bridge: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entity_map = bridge.get("entityMap")
    values = entity_map.get(key) if isinstance(entity_map, dict) else None
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise EnrichmentError(f"bridge.entityMap.{key} must be an object array")
    return values


def _prepare_inputs(
    source_path: Path,
    stats_source_path: Path,
    layout_path: Path,
    bridge_path: Path,
) -> dict[str, Any]:
    source_document = read_json(source_path)
    stats_document = (
        source_document
        if stats_source_path == source_path
        else read_json(stats_source_path)
    )
    source_view = _read_model_view(source_document, "source read model")
    stats_view = _read_model_view(stats_document, "stats read model")
    if source_view["sourceSha256"] != stats_view["sourceSha256"]:
        raise EnrichmentError("Source mismatch: read models bind different backup SHA-256 values")
    if source_view["recordsSemanticSha256"] != stats_view["recordsSemanticSha256"]:
        raise EnrichmentError("Source mismatch: read models contain different record selections")

    class_stats = stats_document.get("classStats")
    if not isinstance(class_stats, dict):
        raise EnrichmentError(
            "A classStats aggregate is required in source or --stats-source"
        )
    stats_by_uuid = class_stats.get("byKsEntityUuid")
    if not isinstance(stats_by_uuid, dict):
        raise EnrichmentError("classStats.byKsEntityUuid must be an object")

    layout = read_json(layout_path)
    bridge = read_json(bridge_path)
    _require_valid(rt.validate_diagram(layout), "layout")
    _require_valid(rt.validate_bridge(bridge), "bridge")
    if not isinstance(layout, dict) or layout.get("schemaVersion") not in {"1.1", "1.2"}:
        raise EnrichmentError("Layout must use Diagramm schema 1.1 or 1.2")
    diagram_binding = bridge.get("diagram")
    if not isinstance(diagram_binding, dict) or diagram_binding.get("modelId") != layout.get("id"):
        raise EnrichmentError("Bridge modelId does not match layout id")

    records = source_view["records"]
    project_uuid = _project_uuid(records)
    bridge_source = bridge.get("source")
    if not isinstance(bridge_source, dict):
        raise EnrichmentError("Bridge source binding is missing")
    for key in ("projectUuid", "backupProjectUuid"):
        value = bridge_source.get(key)
        if value is not None and value != project_uuid:
            raise EnrichmentError(f"Bridge {key} does not match source project UUID")
    structural_records = [record for record in records if rio.is_structural_record(record)]
    structural_sha256 = rt.semantic_sha256(structural_records)
    if bridge_source.get("semanticSha256") != structural_sha256:
        raise EnrichmentError(
            "Bridge structural semantic SHA-256 does not match the read model"
        )

    types = _by_type(records)
    class_records = _index_by_uuid(types[("class", "class")])
    class_entries = _entity_map_entries(bridge, "classes")
    relationship_entries = _entity_map_entries(bridge, "relationships")
    layout_classes = {
        str(item.get("id")): item
        for item in layout.get("classes", [])
        if isinstance(item, dict)
    }
    layout_relationships = {
        str(item.get("id")): item
        for item in layout.get("relationships", [])
        if isinstance(item, dict)
    }

    class_diagram_ids = [str(entry.get("diagramId")) for entry in class_entries]
    relationship_diagram_ids = [
        str(entry.get("diagramId")) for entry in relationship_entries
    ]
    if len(set(class_diagram_ids)) != len(class_diagram_ids):
        raise EnrichmentError("Bridge class diagram IDs are not unique")
    if len(set(relationship_diagram_ids)) != len(relationship_diagram_ids):
        raise EnrichmentError("Bridge relationship diagram IDs are not unique")
    if set(class_diagram_ids) != set(layout_classes):
        raise EnrichmentError("Bridge class IDs differ from layout class IDs")
    if set(relationship_diagram_ids) != set(layout_relationships):
        raise EnrichmentError("Bridge relationship IDs differ from layout relationship IDs")

    class_by_ks_uuid: dict[str, tuple[str, str]] = {}
    owner_by_ks_uuid: dict[str, tuple[str, str, str]] = {}
    for entry in class_entries:
        ks_uuid = entry.get("ksEntityUuid")
        diagram_id = entry.get("diagramId")
        if not isinstance(ks_uuid, str) or ks_uuid not in class_records:
            raise EnrichmentError(f"Bridge class {ks_uuid} is absent from the read model")
        if ks_uuid in owner_by_ks_uuid:
            raise EnrichmentError(f"Bridge owner UUID {ks_uuid} is duplicated")
        class_by_ks_uuid[ks_uuid] = ("class", str(diagram_id))
        owner_by_ks_uuid[ks_uuid] = ("class", str(diagram_id), "class")

    for entry in relationship_entries:
        ks_uuid = entry.get("ksEntityUuid")
        diagram_id = str(entry.get("diagramId"))
        if not isinstance(ks_uuid, str) or ks_uuid not in class_records:
            raise EnrichmentError(
                f"Bridge relationship {ks_uuid} is absent from the read model"
            )
        for key, role in (
            ("ksEntityUuid", "relationship"),
            ("sourceHelperUuid", "sourceHelper"),
            ("targetHelperUuid", "targetHelper"),
        ):
            owner_uuid = entry.get(key)
            if not isinstance(owner_uuid, str) or owner_uuid not in class_records:
                raise EnrichmentError(
                    f"Bridge relationship {diagram_id} has invalid {key}"
                )
            if owner_uuid in owner_by_ks_uuid:
                raise EnrichmentError(f"Bridge owner UUID {owner_uuid} is duplicated")
            owner_by_ks_uuid[owner_uuid] = ("relationship", diagram_id, role)

        relation_data = _data(class_records[ks_uuid])
        source_ks_uuid = entry.get("sourceKsEntityUuid")
        target_ks_uuid = entry.get("targetKsEntityUuid")
        if source_ks_uuid != relation_data.get("relatedSourceUuid"):
            raise EnrichmentError(f"Relationship {diagram_id} source binding is invalid")
        if target_ks_uuid != relation_data.get("relatedDestinationUuid"):
            raise EnrichmentError(f"Relationship {diagram_id} target binding is invalid")
        source_owner = class_by_ks_uuid.get(str(source_ks_uuid))
        target_owner = class_by_ks_uuid.get(str(target_ks_uuid))
        layout_relation = layout_relationships[diagram_id]
        if source_owner is None or layout_relation.get("sourceClassId") != source_owner[1]:
            raise EnrichmentError(f"Relationship {diagram_id} layout source is invalid")
        if target_owner is None or layout_relation.get("targetClassId") != target_owner[1]:
            raise EnrichmentError(f"Relationship {diagram_id} layout target is invalid")

    return {
        "sourcePath": source_path,
        "statsSourcePath": stats_source_path,
        "layoutPath": layout_path,
        "bridgePath": bridge_path,
        "sourceDocument": source_document,
        "statsDocument": stats_document,
        "sourceView": source_view,
        "statsView": stats_view,
        "records": records,
        "types": types,
        "classRecords": class_records,
        "classStats": class_stats,
        "statsByUuid": stats_by_uuid,
        "layout": layout,
        "bridge": bridge,
        "projectUuid": project_uuid,
        "structuralSemanticSha256": structural_sha256,
        "classEntries": class_entries,
        "relationshipEntries": relationship_entries,
        "ownerByKsUuid": owner_by_ks_uuid,
    }


def _choose_l10n(
    records: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    items = list(records)
    if not items:
        return None, True
    preferred = next(
        (item for item in items if _data(item).get("code") == "ru_RU"),
        items[0],
    )
    return preferred, _data(preferred).get("code") != "ru_RU"


def _regular_formulas(
    formulas: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [formula for formula in formulas if _data(formula).get("type") == "regular"]


def _active_regular_formulas(
    formulas: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        formula
        for formula in _regular_formulas(formulas)
        if _data(formula).get("enabled") is True
        and _data(formula).get("isVersion") is not True
    ]


def _formula_evidence(
    formulas: Iterable[dict[str, Any]],
    elements_by_formula: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], list[str], int]:
    dependency_uuids: set[str] = set()
    element_uuids: set[str] = set()
    element_count = 0
    for formula in formulas:
        formula_uuid = str(formula.get("UUID"))
        embedded = _data(formula).get("elements")
        candidates: list[dict[str, Any]] = [
            item for item in embedded or [] if isinstance(item, dict)
        ] if isinstance(embedded, list) else []
        candidates.extend(_data(record) for record in elements_by_formula[formula_uuid])
        for item in candidates:
            element_count += 1
            indicator_uuid = item.get("indicatorUuid")
            if isinstance(indicator_uuid, str) and indicator_uuid:
                dependency_uuids.add(indicator_uuid)
        for record in elements_by_formula[formula_uuid]:
            record_uuid = record.get("UUID")
            if isinstance(record_uuid, str):
                element_uuids.add(record_uuid)
    return sorted(dependency_uuids), sorted(element_uuids), element_count


def _indicator_tree_paths(
    tree_records: list[dict[str, Any]],
) -> dict[str, list[str]]:
    tree_by_uuid = {
        str(record.get("UUID")): record
        for record in tree_records
        if isinstance(record.get("UUID"), str)
    }
    indicator_tree_by_reference = {
        str(_data(record).get("referenceUuid")): record
        for record in tree_records
        if _data(record).get("type") == "indicator"
        and isinstance(_data(record).get("referenceUuid"), str)
    }
    result: dict[str, list[str]] = {}
    for indicator_uuid, initial in indicator_tree_by_reference.items():
        current: dict[str, Any] | None = initial
        path: list[str] = []
        seen: set[str] = set()
        while current is not None:
            current_uuid = str(current.get("UUID"))
            if current_uuid in seen:
                raise EnrichmentError(f"Tree cycle while mapping indicator {indicator_uuid}")
            seen.add(current_uuid)
            current_data = _data(current)
            if current_data.get("type") == "folder":
                name = _text(current_data.get("name")).strip()
                if name:
                    path.append(name)
            if current_data.get("type") == "class":
                break
            parent_uuid = current_data.get("parentUuid")
            current = tree_by_uuid.get(str(parent_uuid))
        result[indicator_uuid] = list(reversed(path))
    return result


def _project_ks_properties(
    record: dict[str, Any] | None,
    category: str,
) -> list[dict[str, Any]]:
    if record is None:
        return []
    data = _data(record)
    result: list[dict[str, Any]] = []
    for key, label in KS_PROPERTY_LABELS.items():
        value = data.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, (str, int, float, bool, list, dict)):
            continue
        result.append(
            {
                "key": key,
                "label": label,
                "value": copy.deepcopy(value),
                "sourcePath": f"class/class.Data.{key}",
                "category": category,
                "readOnly": True,
            }
        )
    return result


def _inbound_integration_evidence(
    types: dict[tuple[str, str], list[dict[str, Any]]],
    indicator_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    integrations = {
        str(record.get("UUID")): record
        for record in types[("integrator", "integration")]
    }
    operations = {
        str(record.get("UUID")): record
        for record in types[("integrator", "integrationOperation")]
    }
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relation in types[("integrator", "integrationRelation")]:
        data = _data(relation)
        indicator_uuid = _normalized_get(data, "internalField")
        if (
            _normalized_get(data, "isIndicator") is not True
            or _normalized_get(data, "isActive") is not True
            or not isinstance(indicator_uuid, str)
            or indicator_uuid not in indicator_ids
        ):
            continue
        operation_uuid = _normalized_get(data, "operationUuid")
        operation = operations.get(str(operation_uuid))
        operation_data = _data(operation)
        if operation is None or _normalized_get(operation_data, "disabled") is True:
            continue
        integration_uuid = _normalized_get(operation_data, "integrationUuid")
        integration = integrations.get(str(integration_uuid))
        integration_data = _data(integration)
        direction = _text(_normalized_get(integration_data, "direction")).casefold()
        if integration is None or direction not in {"input", "import", "inbound"}:
            continue
        result[indicator_uuid].append(
            {
                "integrationRelationUuid": relation.get("UUID"),
                "operationUuid": operation_uuid,
                "integrationUuid": integration_uuid,
                "integrationName": _text(_normalized_get(integration_data, "name")),
                "direction": direction,
            }
        )
    return result


def _construct_projection(
    prepared: dict[str, Any],
    generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise EnrichmentError("generatedAt must be a non-empty string")
    model = copy.deepcopy(prepared["layout"])
    model["schemaVersion"] = OUTPUT_SCHEMA
    model["updatedAt"] = generated_at
    types = prepared["types"]
    indicators = types[("class", "indicator")]
    indicator_ids = {str(record.get("UUID")) for record in indicators}
    if len(indicator_ids) != len(indicators):
        raise EnrichmentError("Indicator UUIDs are not unique")

    class_by_id = {
        str(item.get("id")): item
        for item in model.get("classes", [])
        if isinstance(item, dict)
    }
    relationship_by_id = {
        str(item.get("id")): item
        for item in model.get("relationships", [])
        if isinstance(item, dict)
    }
    for item in class_by_id.values():
        item["indicators"] = []
        item["ksProperties"] = []
        item.pop("objectCount", None)
    for item in relationship_by_id.values():
        item["indicators"] = []
        item["ksProperties"] = []

    for entry in prepared["classEntries"]:
        diagram_id = str(entry["diagramId"])
        ks_uuid = str(entry["ksEntityUuid"])
        stats = prepared["statsByUuid"].get(ks_uuid)
        if not isinstance(stats, dict):
            raise EnrichmentError(f"Missing classStats for KS class {ks_uuid}")
        object_count = stats.get("objectCount")
        if (
            not isinstance(object_count, int)
            or isinstance(object_count, bool)
            or object_count < 0
        ):
            raise EnrichmentError(f"Invalid objectCount for KS class {ks_uuid}")
        class_by_id[diagram_id]["objectCount"] = object_count
        class_by_id[diagram_id]["ksProperties"] = _project_ks_properties(
            prepared["classRecords"].get(ks_uuid), "class_configuration"
        )
    for entry in prepared["relationshipEntries"]:
        diagram_id = str(entry["diagramId"])
        ks_uuid = str(entry["ksEntityUuid"])
        relationship_by_id[diagram_id]["ksProperties"] = _project_ks_properties(
            prepared["classRecords"].get(ks_uuid),
            "relationship_configuration",
        )

    l10n_by_indicator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in types[("class", "indicatorL10n")]:
        indicator_uuid = _data(record).get("indicatorUuid")
        if isinstance(indicator_uuid, str):
            l10n_by_indicator[indicator_uuid].append(record)
    unit_by_indicator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in types[("class", "indicatorUnitL10n")]:
        indicator_uuid = _data(record).get("indicatorUuid")
        if isinstance(indicator_uuid, str):
            unit_by_indicator[indicator_uuid].append(record)
    dimensions_by_indicator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in types[("class", "indicatorDimension")]:
        indicator_uuid = _data(record).get("indicatorUuid")
        if isinstance(indicator_uuid, str):
            dimensions_by_indicator[indicator_uuid].append(record)
    formulas_by_indicator: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in types[("class", "formula")]:
        indicator_uuid = _data(record).get("indicatorUuid")
        if isinstance(indicator_uuid, str):
            formulas_by_indicator[indicator_uuid].append(record)
    elements_by_formula: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in types[("class", "formulaElement")]:
        formula_uuid = _data(record).get("formulaUuid")
        if isinstance(formula_uuid, str):
            elements_by_formula[formula_uuid].append(record)
    tree_paths = _indicator_tree_paths(types[("class", "tree")])
    inbound_evidence = _inbound_integration_evidence(types, indicator_ids)

    mapped_ids: set[str] = set()
    kind_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()
    missing_l10n = 0
    for record in sorted(indicators, key=lambda item: str(item.get("UUID"))):
        indicator_uuid = str(record.get("UUID"))
        data = _data(record)
        ks_owner_uuid = data.get("classUuid")
        owner = prepared["ownerByKsUuid"].get(str(ks_owner_uuid))
        if owner is None:
            raise EnrichmentError(
                f"Cannot resolve owner {ks_owner_uuid} for indicator {indicator_uuid}"
            )
        owner_type, owner_id, owner_role = owner
        owner_item = (
            class_by_id.get(owner_id)
            if owner_type == "class"
            else relationship_by_id.get(owner_id)
        )
        if owner_item is None:
            raise EnrichmentError(f"Diagram owner {owner_id} is missing")

        l10n_record, used_fallback = _choose_l10n(
            l10n_by_indicator[indicator_uuid]
        )
        l10n_data = _data(l10n_record)
        name = (
            _text(l10n_data.get("name")).strip()
            or _text(data.get("name")).strip()
            or _text(record.get("Name")).strip()
            or f"KS indicator {indicator_uuid}"
        )
        if used_fallback:
            missing_l10n += 1
        unit_record, _ = _choose_l10n(unit_by_indicator[indicator_uuid])
        unit = _text(_data(unit_record).get("unit")) or _text(
            data.get("unitMeasurement")
        )

        all_formulas = formulas_by_indicator[indicator_uuid]
        active_formulas = _active_regular_formulas(all_formulas)
        integration_evidence = inbound_evidence[indicator_uuid]
        if active_formulas:
            kind = "calculated"
            classification = "active_regular_formula"
        elif integration_evidence:
            kind = "loaded"
            classification = "active_inbound_integration"
        else:
            kind = "input"
            classification = "ks_input_default"

        data_type = _text(data.get("dataType")) or "unknown"
        presentation_role = "indicator" if data_type == "number" else "attribute"
        dependency_uuids, formula_element_uuids, formula_element_count = (
            _formula_evidence(active_formulas, elements_by_formula)
        )
        unresolved = sorted(
            dependency_uuid
            for dependency_uuid in dependency_uuids
            if dependency_uuid not in indicator_ids
        )
        if unresolved:
            raise EnrichmentError(
                f"Indicator {indicator_uuid} has unresolved dependencies: "
                + ", ".join(unresolved[:5])
            )
        temporal_self_count = sum(
            dependency_uuid == indicator_uuid for dependency_uuid in dependency_uuids
        )
        dependencies = [
            f"ks-indicator:{dependency_uuid}"
            for dependency_uuid in dependency_uuids
            if dependency_uuid != indicator_uuid
        ]
        formula_uuids = sorted(
            str(formula.get("UUID"))
            for formula in active_formulas
            if isinstance(formula.get("UUID"), str)
        )

        source_config: dict[str, Any] = {
            "mappingProfile": MAPPING_PROFILE,
            "readOnly": True,
            "ownerRole": owner_role,
            "presentationRole": presentation_role,
            "classificationEvidence": classification,
        }
        ks_value_type = _text(data.get("valueType"))
        if ks_value_type:
            source_config["ksValueType"] = ks_value_type
        if kind == "input":
            source_config["provisionalKind"] = True
        if active_formulas:
            source_config.update(
                {
                    "formulaCount": len(active_formulas),
                    "formulaElementCount": formula_element_count,
                    "formulaElementUuids": formula_element_uuids,
                    "formulaRepresentation": "read_only_sidecar",
                    "formulaUuids": formula_uuids,
                    "dependencyKsIndicatorUuids": dependency_uuids,
                    "dependencySource": "active_regular_formula_elements",
                }
            )
        historical_formula_count = len(all_formulas) - len(active_formulas)
        if historical_formula_count:
            source_config["formulaHistoryCount"] = historical_formula_count
        if temporal_self_count:
            source_config["temporalSelfDependencyCount"] = temporal_self_count
        dimensions = dimensions_by_indicator[indicator_uuid]
        if dimensions:
            source_config["dimensionCount"] = len(dimensions)
            source_config["dimensionDictionaryUuids"] = sorted(
                {
                    str(_data(item).get("dictionaryUuid"))
                    for item in dimensions
                    if isinstance(_data(item).get("dictionaryUuid"), str)
                }
            )
        dictionary_uuid = data.get("dictionaryUuid")
        if isinstance(dictionary_uuid, str) and dictionary_uuid:
            source_config["dictionaryUuid"] = dictionary_uuid
        if used_fallback:
            source_config["l10nFallback"] = True
        if tree_paths.get(indicator_uuid):
            source_config["ksTreePath"] = tree_paths[indicator_uuid]
        if integration_evidence:
            source_config["integrationMappingCount"] = len(integration_evidence)
            source_config["integrationRelationUuids"] = sorted(
                str(item["integrationRelationUuid"])
                for item in integration_evidence
            )

        notes = "Read-only KS indicator evidence."
        if presentation_role == "attribute":
            notes += " Displayed as an attribute but retained as a KS indicator."
        if kind == "input":
            notes += " Input classification is provisional."
        if active_formulas:
            notes += " Full formula evidence is stored in the separate sidecar."

        mapped: dict[str, Any] = {
            "id": f"ks-indicator:{indicator_uuid}",
            "ownerType": owner_type,
            "ownerId": owner_id,
            "name": name,
            "kind": kind,
            "valueType": data_type,
            "unit": unit,
            "description": _text(data.get("description")),
            "dependencies": dependencies,
            "sourceConfig": source_config,
            "knowledgeSpaceNotes": notes,
        }
        if kind == "calculated":
            mapped["calculationSource"] = "knowledge_space"
            mapped["formula"] = f"KS_FORMULA_READ_ONLY({len(active_formulas)})"
        if mapped["id"] in mapped_ids:
            raise EnrichmentError(f"Duplicate mapped indicator {mapped['id']}")
        mapped_ids.add(mapped["id"])
        owner_item["indicators"].append(mapped)
        kind_counts[kind] += 1
        role_counts[presentation_role] += 1
        owner_counts[owner_type] += 1

    if len(mapped_ids) != len(indicators):
        raise EnrichmentError(
            f"Mapped {len(mapped_ids)} of {len(indicators)} source indicators"
        )
    role_order = {"attribute": 0, "indicator": 1}
    kind_order = {"calculated": 0, "loaded": 1, "input": 2}
    for owner_item in [*class_by_id.values(), *relationship_by_id.values()]:
        owner_item["indicators"].sort(
            key=lambda item: (
                role_order.get(
                    str((item.get("sourceConfig") or {}).get("presentationRole")), 9
                ),
                kind_order.get(str(item.get("kind")), 9),
                _text(item.get("name")).casefold(),
                str(item.get("id")),
            )
        )

    class_stats_rows: dict[str, dict[str, Any]] = {}
    for entry in prepared["classEntries"]:
        diagram_id = str(entry["diagramId"])
        ks_uuid = str(entry["ksEntityUuid"])
        stats = prepared["statsByUuid"][ks_uuid]
        owner_item = class_by_id[diagram_id]
        display_count = sum(
            (indicator.get("sourceConfig") or {}).get("presentationRole")
            != "attribute"
            for indicator in owner_item["indicators"]
        )
        if display_count != stats.get("displayIndicatorCount"):
            raise EnrichmentError(
                f"displayIndicatorCount mismatch for KS class {ks_uuid}"
            )
        if stats.get("derivedFormulaCount") != display_count:
            raise EnrichmentError(
                f"derivedFormulaCount mismatch for KS class {ks_uuid}"
            )
        class_stats_rows[diagram_id] = {
            "ksEntityUuid": ks_uuid,
            "objectCount": owner_item["objectCount"],
            "displayIndicatorCount": display_count,
            "derivedFormulaCount": stats.get("derivedFormulaCount"),
            "actualFormulaRecordCount": stats.get("actualFormulaRecordCount"),
            "activeRegularFormulaRecordCount": stats.get(
                "activeRegularFormulaRecordCount"
            ),
            "actualCalculatedIndicatorCount": stats.get(
                "actualCalculatedIndicatorCount"
            ),
        }

    sidecar = {
        "format": SIDECAR_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "profile": MAPPING_PROFILE,
        "createdAt": generated_at,
        "readOnly": True,
        "restorePayload": False,
        "liveRestoreBlocked": True,
        "containsCredentials": False,
        "containsObjectRecords": False,
        "containsObjectValues": False,
        "source": {
            "projectUuid": prepared["projectUuid"],
            "backupSha256": prepared["sourceView"]["sourceSha256"],
            "recordSemanticSha256": prepared["sourceView"][
                "recordsSemanticSha256"
            ],
            "structuralSemanticSha256": prepared["structuralSemanticSha256"],
            "readModelFileSha256": rio.sha256_file(prepared["sourcePath"]),
            "statsReadModelFileSha256": rio.sha256_file(
                prepared["statsSourcePath"]
            ),
        },
        "diagram": {
            "modelId": model.get("id"),
            "schemaVersion": OUTPUT_SCHEMA,
            "indicatorCount": len(mapped_ids),
        },
        "ownerMap": {
            "classes": copy.deepcopy(prepared["classEntries"]),
            "relationships": copy.deepcopy(prepared["relationshipEntries"]),
        },
        "records": {
            name: copy.deepcopy(types[key])
            for name, key in SIDECAR_RECORD_TYPES.items()
        },
        "inboundIntegrationEvidence": {
            key: copy.deepcopy(value)
            for key, value in sorted(inbound_evidence.items())
            if value
        },
    }
    forbidden = _forbidden_key_paths(sidecar)
    if forbidden:
        raise EnrichmentError(
            "Sanitized sidecar contains forbidden keys: " + ", ".join(forbidden[:5])
        )

    metrics = {
        "indicatorCount": len(mapped_ids),
        "kindCounts": dict(sorted(kind_counts.items())),
        "presentationRoleCounts": dict(sorted(role_counts.items())),
        "ownerTypeCounts": dict(sorted(owner_counts.items())),
        "missingPreferredL10n": missing_l10n,
        "classStatistics": class_stats_rows,
    }
    return model, sidecar, metrics


def _forbidden_key_paths(value: Any, path: str = "$") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _normalized_key(str(key)) in FORBIDDEN_SIDECAR_KEYS:
                result.append(child_path)
            result.extend(_forbidden_key_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_forbidden_key_paths(child, f"{path}[{index}]"))
    return result


def _first_difference(actual: Any, expected: Any, path: str = "$") -> str | None:
    if type(actual) is not type(expected):
        return path
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            suffix = missing[0] if missing else extra[0]
            return f"{path}.{suffix}"
        for key in expected:
            difference = _first_difference(actual[key], expected[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(actual) != len(expected):
            return path
        for index, expected_item in enumerate(expected):
            difference = _first_difference(
                actual[index], expected_item, f"{path}[{index}]"
            )
            if difference:
                return difference
        return None
    return None if actual == expected else path


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _diagram_schema_errors(model: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(model, dict):
        return ["diagram must be an object"]
    for key in (
        "id",
        "name",
        "description",
        "projectContext",
        "version",
        "schemaVersion",
        "createdAt",
        "updatedAt",
    ):
        if not isinstance(model.get(key), str):
            errors.append(f"diagram.{key} must be a string")
    if model.get("schemaVersion") != OUTPUT_SCHEMA:
        errors.append(f"diagram.schemaVersion must equal {OUTPUT_SCHEMA}")
    classes = model.get("classes")
    relationships = model.get("relationships")
    frames = model.get("frames")
    if not isinstance(classes, list):
        return errors + ["diagram.classes must be an array"]
    if not isinstance(relationships, list):
        return errors + ["diagram.relationships must be an array"]
    if not isinstance(frames, list):
        errors.append("diagram.frames must be an array")

    class_ids: set[str] = set()
    indicator_ids: set[str] = set()
    for index, item in enumerate(classes):
        path = f"diagram.classes[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        class_id = item.get("id")
        if not isinstance(class_id, str) or not class_id:
            errors.append(f"{path}.id is required")
            continue
        if class_id in class_ids:
            errors.append(f"duplicate class id {class_id}")
        class_ids.add(class_id)
        for key in ("name", "description", "stereotype", "notes"):
            if not isinstance(item.get(key), str):
                errors.append(f"{path}.{key} must be a string")
        for key in ("attributes", "indicators", "ksProperties"):
            if not isinstance(item.get(key), list):
                errors.append(f"{path}.{key} must be an array")
        object_count = item.get("objectCount")
        if (
            not isinstance(object_count, int)
            or isinstance(object_count, bool)
            or object_count < 0
        ):
            errors.append(f"{path}.objectCount must be a non-negative integer")
        errors.extend(_geometry_errors(item, path))
        errors.extend(
            _indicator_errors(item.get("indicators"), "class", class_id, path, indicator_ids)
        )
        errors.extend(_property_errors(item.get("ksProperties"), path))

    relationship_ids: set[str] = set()
    for index, item in enumerate(relationships):
        path = f"diagram.relationships[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        relation_id = item.get("id")
        if not isinstance(relation_id, str) or not relation_id:
            errors.append(f"{path}.id is required")
            continue
        if relation_id in relationship_ids:
            errors.append(f"duplicate relationship id {relation_id}")
        relationship_ids.add(relation_id)
        for key in ("name", "description", "cardinality", "notes"):
            if not isinstance(item.get(key), str):
                errors.append(f"{path}.{key} must be a string")
        if item.get("type") not in RELATIONSHIP_TYPES:
            errors.append(f"{path}.type is unsupported")
        if item.get("direction") not in RELATIONSHIP_DIRECTIONS:
            errors.append(f"{path}.direction is unsupported")
        for endpoint in ("sourceClassId", "targetClassId"):
            if item.get(endpoint) not in class_ids:
                errors.append(f"{path}.{endpoint} does not reference a class")
        errors.extend(
            _indicator_errors(
                item.get("indicators"),
                "relationship",
                relation_id,
                path,
                indicator_ids,
            )
        )
        errors.extend(_property_errors(item.get("ksProperties"), path))

    viewport = model.get("viewport")
    if not isinstance(viewport, dict):
        errors.append("diagram.viewport must be an object")
    elif not all(_is_finite_number(viewport.get(key)) for key in ("x", "y")) or not (
        _is_finite_number(viewport.get("zoom")) and viewport["zoom"] > 0
    ):
        errors.append("diagram.viewport is invalid")
    return errors


def _geometry_errors(item: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    position = item.get("position")
    size = item.get("size")
    if not isinstance(position, dict) or not all(
        _is_finite_number(position.get(key)) for key in ("x", "y")
    ):
        errors.append(f"{path}.position is invalid")
    if not isinstance(size, dict) or not all(
        _is_finite_number(size.get(key)) and size[key] > 0
        for key in ("width", "height")
    ):
        errors.append(f"{path}.size is invalid")
    return errors


def _indicator_errors(
    indicators: Any,
    owner_type: str,
    owner_id: str,
    path: str,
    seen: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(indicators, list):
        return [f"{path}.indicators must be an array"]
    for index, indicator in enumerate(indicators):
        item_path = f"{path}.indicators[{index}]"
        if not isinstance(indicator, dict):
            errors.append(f"{item_path} must be an object")
            continue
        indicator_id = indicator.get("id")
        if not isinstance(indicator_id, str) or not indicator_id:
            errors.append(f"{item_path}.id is required")
        elif indicator_id in seen:
            errors.append(f"duplicate indicator id {indicator_id}")
        else:
            seen.add(indicator_id)
        if indicator.get("ownerType") != owner_type or indicator.get("ownerId") != owner_id:
            errors.append(f"{item_path} owner is invalid")
        if indicator.get("kind") not in INDICATOR_KINDS:
            errors.append(f"{item_path}.kind is unsupported")
        for key in ("name", "valueType", "unit", "description", "knowledgeSpaceNotes"):
            if not isinstance(indicator.get(key), str):
                errors.append(f"{item_path}.{key} must be a string")
        if not isinstance(indicator.get("dependencies"), list) or not all(
            isinstance(value, str) for value in indicator.get("dependencies", [])
        ):
            errors.append(f"{item_path}.dependencies must be a string array")
        if indicator.get("kind") == "calculated":
            if indicator.get("calculationSource") != "knowledge_space":
                errors.append(f"{item_path}.calculationSource is invalid")
            if not isinstance(indicator.get("formula"), str) or not indicator["formula"].strip():
                errors.append(f"{item_path}.formula is required")
    return errors


def _property_errors(properties: Any, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(properties, list):
        return [f"{path}.ksProperties must be an array"]
    for index, item in enumerate(properties):
        item_path = f"{path}.ksProperties[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path} must be an object")
            continue
        if item.get("readOnly") is not True:
            errors.append(f"{item_path}.readOnly must be true")
        if item.get("category") not in {
            "class_configuration",
            "relationship_configuration",
            "card_field",
        }:
            errors.append(f"{item_path}.category is unsupported")
        for key in ("key", "label", "sourcePath"):
            if not isinstance(item.get(key), str) or not item[key]:
                errors.append(f"{item_path}.{key} is required")
    return errors


def _projection_validation_report(
    prepared: dict[str, Any],
    model: Any,
    sidecar: Any,
) -> dict[str, Any]:
    errors = _diagram_schema_errors(model)
    warnings = list(prepared["sourceView"]["validation"].get("warnings", []))
    if isinstance(model, dict):
        _require_valid_or_collect(rt.validate_diagram(model), "diagram", errors)
    generated_at = sidecar.get("createdAt") if isinstance(sidecar, dict) else None
    if not isinstance(generated_at, str) or not generated_at:
        errors.append("sidecar.createdAt is required")
        expected_model = None
        expected_sidecar = None
    else:
        try:
            expected_model, expected_sidecar, _ = _construct_projection(
                prepared, generated_at
            )
        except EnrichmentError as exc:
            errors.append(str(exc))
            expected_model = None
            expected_sidecar = None
    if expected_model is not None:
        difference = _first_difference(model, expected_model)
        if difference:
            errors.append(f"diagram differs from deterministic projection at {difference}")
    if expected_sidecar is not None:
        difference = _first_difference(sidecar, expected_sidecar)
        if difference:
            errors.append(f"sidecar differs from deterministic projection at {difference}")
    forbidden = _forbidden_key_paths(sidecar)
    if forbidden:
        errors.append("sidecar contains forbidden keys: " + ", ".join(forbidden[:5]))
    mapped = _mapped_indicators(model)
    object_counts = [
        item.get("objectCount")
        for item in model.get("classes", [])
        if isinstance(item, dict)
    ] if isinstance(model, dict) else []
    return {
        "format": REPORT_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "mode": "validate",
        "valid": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(str(item) for item in warnings)),
        "counts": {
            "classes": len(model.get("classes", [])) if isinstance(model, dict) else 0,
            "relationships": len(model.get("relationships", [])) if isinstance(model, dict) else 0,
            "indicators": len(mapped),
            "classObjects": sum(
                value
                for value in object_counts
                if isinstance(value, int) and not isinstance(value, bool)
            ),
            "presentationRoles": dict(
                sorted(
                    Counter(
                        str((item.get("sourceConfig") or {}).get("presentationRole"))
                        for item in mapped
                    ).items()
                )
            ),
        },
        "security": {
            "forbiddenSidecarKeyPaths": forbidden,
            "sidecarContainsCredentials": sidecar.get("containsCredentials")
            if isinstance(sidecar, dict)
            else None,
        },
    }


def _require_valid_or_collect(
    report: dict[str, Any], label: str, errors: list[str]
) -> None:
    if report.get("valid"):
        return
    for issue in report.get("errors", []):
        if isinstance(issue, dict):
            errors.append(f"{label}: {issue.get('message', issue)}")
        else:
            errors.append(f"{label}: {issue}")


def _mapped_indicators(model: Any) -> list[dict[str, Any]]:
    if not isinstance(model, dict):
        return []
    result: list[dict[str, Any]] = []
    for collection in ("classes", "relationships"):
        values = model.get(collection)
        if not isinstance(values, list):
            continue
        for owner in values:
            if isinstance(owner, dict) and isinstance(owner.get("indicators"), list):
                result.extend(
                    item for item in owner["indicators"] if isinstance(item, dict)
                )
    return result


def _resolve_paths(
    source: str | Path,
    stats_source: str | Path | None,
    layout: str | Path,
    bridge: str | Path,
) -> tuple[Path, Path, Path, Path]:
    source_path = Path(source).expanduser().resolve()
    stats_path = (
        Path(stats_source).expanduser().resolve() if stats_source else source_path
    )
    return (
        source_path,
        stats_path,
        Path(layout).expanduser().resolve(),
        Path(bridge).expanduser().resolve(),
    )


def _ensure_distinct_outputs(inputs: Iterable[Path], outputs: Iterable[Path]) -> None:
    input_set = {str(path) for path in inputs}
    output_values = [str(path) for path in outputs]
    if len(set(output_values)) != len(output_values):
        raise EnrichmentError("Output artifact paths must be distinct")
    if input_set.intersection(output_values):
        raise EnrichmentError("Output artifacts must not overwrite input artifacts")


def build_artifacts(
    *,
    source: str | Path,
    layout: str | Path,
    bridge: str | Path,
    output: str | Path,
    sidecar: str | Path,
    report: str | Path,
    stats_source: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_path, stats_path, layout_path, bridge_path = _resolve_paths(
        source, stats_source, layout, bridge
    )
    output_path = Path(output).expanduser().resolve()
    sidecar_path = Path(sidecar).expanduser().resolve()
    report_path = Path(report).expanduser().resolve()
    _ensure_distinct_outputs(
        {source_path, stats_path, layout_path, bridge_path},
        {output_path, sidecar_path, report_path},
    )
    prepared = _prepare_inputs(source_path, stats_path, layout_path, bridge_path)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    model, sidecar_value, metrics = _construct_projection(prepared, timestamp)
    validation = _projection_validation_report(prepared, model, sidecar_value)
    if not validation["valid"]:
        raise EnrichmentError(
            "Constructed enrichment failed validation: "
            + "; ".join(validation["errors"][:5])
        )

    rt.atomic_write_json(str(output_path), model)
    rt.atomic_write_json(str(sidecar_path), sidecar_value)
    class_rows = metrics["classStatistics"]
    build_report = {
        "format": REPORT_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "mode": "build",
        "valid": True,
        "profile": MAPPING_PROFILE,
        "warnings": validation["warnings"],
        "layoutPreserved": {
            "classes": len(model["classes"]),
            "relationships": len(model["relationships"]),
            "frames": len(model.get("frames", [])),
            "viewport": model.get("viewport"),
        },
        "mapped": {
            "ksIndicators": metrics["indicatorCount"],
            "diagramIndicators": metrics["indicatorCount"],
            "ownerTypes": metrics["ownerTypeCounts"],
            "kinds": metrics["kindCounts"],
            "presentationRoles": metrics["presentationRoleCounts"],
        },
        "classStatistics": {
            "classes": len(class_rows),
            "objects": sum(item["objectCount"] for item in class_rows.values()),
            "classesWithObjects": sum(
                item["objectCount"] > 0 for item in class_rows.values()
            ),
            "classesWithZeroObjects": sum(
                item["objectCount"] == 0 for item in class_rows.values()
            ),
            "displayIndicators": sum(
                item["displayIndicatorCount"] for item in class_rows.values()
            ),
            "derivedFormulas": sum(
                item["derivedFormulaCount"] for item in class_rows.values()
            ),
            "formulaRule": "derivedFormulaCount = displayIndicatorCount",
        },
        "sourceCoverage": {
            "missingPreferredL10n": metrics["missingPreferredL10n"],
            "records": len(prepared["records"]),
            "formulas": len(prepared["types"][("class", "formula")]),
            "formulaElements": len(
                prepared["types"][("class", "formulaElement")]
            ),
        },
        "security": {
            "offlineOnly": True,
            "restorePayload": False,
            "sourceObjectRecordsRetained": False,
            "sourceObjectValuesRetained": False,
            "sidecarContainsCredentials": False,
        },
        "hashes": {
            "sourceReadModelSha256": rio.sha256_file(source_path),
            "statsReadModelSha256": rio.sha256_file(stats_path),
            "layoutSha256": rio.sha256_file(layout_path),
            "bridgeSha256": rio.sha256_file(bridge_path),
            "diagramSha256": rio.sha256_file(output_path),
            "sidecarSha256": rio.sha256_file(sidecar_path),
        },
        "artifacts": {
            "diagram": output_path.name,
            "sidecar": sidecar_path.name,
            "report": report_path.name,
        },
    }
    rt.atomic_write_json(str(report_path), build_report)
    return build_report


def validate_artifacts(
    *,
    source: str | Path,
    layout: str | Path,
    bridge: str | Path,
    model: str | Path,
    sidecar: str | Path,
    stats_source: str | Path | None = None,
) -> dict[str, Any]:
    source_path, stats_path, layout_path, bridge_path = _resolve_paths(
        source, stats_source, layout, bridge
    )
    model_path = Path(model).expanduser().resolve()
    sidecar_path = Path(sidecar).expanduser().resolve()
    prepared = _prepare_inputs(source_path, stats_path, layout_path, bridge_path)
    model_value = read_json(model_path)
    sidecar_value = read_json(sidecar_path)
    report = _projection_validation_report(prepared, model_value, sidecar_value)
    report["hashes"] = {
        "sourceReadModelSha256": rio.sha256_file(source_path),
        "statsReadModelSha256": rio.sha256_file(stats_path),
        "layoutSha256": rio.sha256_file(layout_path),
        "bridgeSha256": rio.sha256_file(bridge_path),
        "diagramSha256": rio.sha256_file(model_path),
        "sidecarSha256": rio.sha256_file(sidecar_path),
    }
    return report


def _by_diagram_id(model: dict[str, Any], collection: str) -> dict[str, dict[str, Any]]:
    values = model.get(collection)
    if not isinstance(values, list):
        return {}
    return {
        str(item.get("id")): item
        for item in values
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def project_structural_edits(
    *,
    structural_baseline: str | Path,
    enriched_baseline: str | Path,
    edited: str | Path,
    bridge: str | Path,
    output: str | Path,
    report: str | Path,
) -> dict[str, Any]:
    structural_path = Path(structural_baseline).expanduser().resolve()
    enriched_path = Path(enriched_baseline).expanduser().resolve()
    edited_path = Path(edited).expanduser().resolve()
    bridge_path = Path(bridge).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    report_path = Path(report).expanduser().resolve()
    _ensure_distinct_outputs(
        {structural_path, enriched_path, edited_path, bridge_path},
        {output_path, report_path},
    )
    structural = read_json(structural_path)
    enriched = read_json(enriched_path)
    edited_value = read_json(edited_path)
    bridge_value = read_json(bridge_path)
    for label, value in (
        ("structural baseline", structural),
        ("enriched baseline", enriched),
        ("edited enriched model", edited_value),
    ):
        _require_valid(rt.validate_diagram(value), label)
        if not isinstance(value, dict):
            raise EnrichmentError(f"{label} must be an object")
    _require_valid(rt.validate_bridge(bridge_value), "bridge")
    if enriched.get("schemaVersion") != OUTPUT_SCHEMA or edited_value.get(
        "schemaVersion"
    ) != OUTPUT_SCHEMA:
        raise EnrichmentError("Enriched baseline and edited model must use schema 1.2")
    model_id = structural.get("id")
    if not model_id or enriched.get("id") != model_id or edited_value.get("id") != model_id:
        raise EnrichmentError("Structural/enriched/edited model IDs differ")
    diagram_binding = bridge_value.get("diagram")
    if not isinstance(diagram_binding, dict) or diagram_binding.get("modelId") != model_id:
        raise EnrichmentError("Bridge modelId differs from structural baseline")
    baseline_binding = diagram_binding.get("baselineSemanticSha256")
    if baseline_binding != rt.semantic_sha256(structural):
        raise EnrichmentError("Bridge does not bind the exact structural baseline")

    structural_classes = _by_diagram_id(structural, "classes")
    structural_relations = _by_diagram_id(structural, "relationships")
    enriched_classes = _by_diagram_id(enriched, "classes")
    enriched_relations = _by_diagram_id(enriched, "relationships")
    edited_classes = _by_diagram_id(edited_value, "classes")
    edited_relations = _by_diagram_id(edited_value, "relationships")
    bridge_class_ids = {
        str(entry.get("diagramId"))
        for entry in _entity_map_entries(bridge_value, "classes")
    }
    bridge_relation_ids = {
        str(entry.get("diagramId"))
        for entry in _entity_map_entries(bridge_value, "relationships")
    }
    if set(structural_classes) != bridge_class_ids or set(enriched_classes) != bridge_class_ids:
        raise EnrichmentError("Existing class identity set differs across baseline/bridge")
    if set(structural_relations) != bridge_relation_ids or set(enriched_relations) != bridge_relation_ids:
        raise EnrichmentError(
            "Existing relationship identity set differs across baseline/bridge"
        )

    readonly_checks = 0
    for entity_id in sorted(bridge_class_ids.intersection(edited_classes)):
        enriched_item = enriched_classes[entity_id]
        edited_item = edited_classes[entity_id]
        for key in ("indicators", "ksProperties", "objectCount"):
            if edited_item.get(key) != enriched_item.get(key):
                raise EnrichmentError(
                    f"Read-only enrichment changed at classes/{entity_id}/{key}"
                )
            readonly_checks += 1
    for entity_id in sorted(bridge_relation_ids.intersection(edited_relations)):
        enriched_item = enriched_relations[entity_id]
        edited_item = edited_relations[entity_id]
        for key in ("indicators", "ksProperties"):
            if edited_item.get(key) != enriched_item.get(key):
                raise EnrichmentError(
                    f"Read-only enrichment changed at relationships/{entity_id}/{key}"
                )
            readonly_checks += 1

    projected = copy.deepcopy(edited_value)
    projected["schemaVersion"] = OUTPUT_SCHEMA
    projected_classes = _by_diagram_id(projected, "classes")
    projected_relations = _by_diagram_id(projected, "relationships")
    for entity_id in bridge_class_ids.intersection(projected_classes):
        target = projected_classes[entity_id]
        baseline = structural_classes[entity_id]
        for key in ("indicators", "ksProperties", "objectCount"):
            if key in baseline:
                target[key] = copy.deepcopy(baseline[key])
            else:
                target.pop(key, None)
    for entity_id in bridge_relation_ids.intersection(projected_relations):
        target = projected_relations[entity_id]
        baseline = structural_relations[entity_id]
        for key in ("indicators", "ksProperties"):
            if key in baseline:
                target[key] = copy.deepcopy(baseline[key])
            else:
                target.pop(key, None)
    _require_valid(rt.validate_diagram(projected), "projected structural edits")

    new_class_ids = sorted(set(projected_classes) - bridge_class_ids)
    new_relation_ids = sorted(set(projected_relations) - bridge_relation_ids)
    deleted_class_ids = sorted(bridge_class_ids - set(projected_classes))
    deleted_relation_ids = sorted(bridge_relation_ids - set(projected_relations))
    endpoint_edits = sorted(
        entity_id
        for entity_id in bridge_relation_ids.intersection(projected_relations)
        if any(
            projected_relations[entity_id].get(key)
            != structural_relations[entity_id].get(key)
            for key in ("sourceClassId", "targetClassId")
        )
    )
    rt.atomic_write_json(str(output_path), projected)
    projection_report = {
        "format": STRUCTURAL_EDIT_REPORT_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "valid": True,
        "offlineOnly": True,
        "modelId": model_id,
        "schemaVersion": OUTPUT_SCHEMA,
        "readOnlyChecks": readonly_checks,
        "existing": {
            "classes": len(bridge_class_ids),
            "relationships": len(bridge_relation_ids),
        },
        "preservedForStructuralDiff": {
            "newClassIds": new_class_ids,
            "newRelationshipIds": new_relation_ids,
            "deletedClassIds": deleted_class_ids,
            "deletedRelationshipIds": deleted_relation_ids,
            "endpointEditedRelationshipIds": endpoint_edits,
        },
        "hashes": {
            "structuralBaselineSha256": rio.sha256_file(structural_path),
            "structuralBaselineSemanticSha256": rt.semantic_sha256(structural),
            "enrichedBaselineSha256": rio.sha256_file(enriched_path),
            "editedEnrichedSha256": rio.sha256_file(edited_path),
            "bridgeSha256": rio.sha256_file(bridge_path),
            "projectedStructuralSha256": rio.sha256_file(output_path),
        },
        "artifacts": {
            "projectedStructural": output_path.name,
            "report": report_path.name,
        },
    }
    rt.atomic_write_json(str(report_path), projection_report)
    return projection_report


def _add_read_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, help="sanitized diagram-read-v0.2 JSON")
    parser.add_argument(
        "--stats-source",
        help="optional source-bound diagram-read-v0.2 JSON containing classStats",
    )
    parser.add_argument("--layout", required=True, help="structural Diagramm layout JSON")
    parser.add_argument("--bridge", required=True, help="structural bridge JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline, sanitized KS read-model to Diagramm enrichment mapper"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser_value = subparsers.add_parser("build", help="build enriched model and sidecar")
    _add_read_inputs(build_parser_value)
    build_parser_value.add_argument("--output", required=True, help="Diagramm schema 1.2 output")
    build_parser_value.add_argument("--sidecar", required=True, help="sanitized evidence sidecar")
    build_parser_value.add_argument("--report", required=True, help="build report JSON")
    build_parser_value.add_argument(
        "--generated-at", help="deterministic timestamp override for reproducible builds"
    )

    validate_parser = subparsers.add_parser("validate", help="validate deterministic artifacts")
    _add_read_inputs(validate_parser)
    validate_parser.add_argument("--model", required=True, help="enriched Diagramm JSON")
    validate_parser.add_argument("--sidecar", required=True, help="sanitized evidence sidecar")
    validate_parser.add_argument("--output", help="optional validation report JSON")

    project_parser = subparsers.add_parser(
        "project-structural-edits",
        help="strip unchanged read-only enrichment before structural diff",
    )
    project_parser.add_argument("--structural-baseline", required=True)
    project_parser.add_argument("--enriched-baseline", required=True)
    project_parser.add_argument("--edited", required=True)
    project_parser.add_argument("--bridge", required=True)
    project_parser.add_argument("--output", required=True)
    project_parser.add_argument("--report", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_artifacts(
                source=args.source,
                stats_source=args.stats_source,
                layout=args.layout,
                bridge=args.bridge,
                output=args.output,
                sidecar=args.sidecar,
                report=args.report,
                generated_at=args.generated_at,
            )
            exit_code = 0
        elif args.command == "validate":
            result = validate_artifacts(
                source=args.source,
                stats_source=args.stats_source,
                layout=args.layout,
                bridge=args.bridge,
                model=args.model,
                sidecar=args.sidecar,
            )
            if args.output:
                output_path = Path(args.output).expanduser().resolve()
                _ensure_distinct_outputs(
                    {
                        Path(args.source).expanduser().resolve(),
                        Path(args.stats_source).expanduser().resolve()
                        if args.stats_source
                        else Path(args.source).expanduser().resolve(),
                        Path(args.layout).expanduser().resolve(),
                        Path(args.bridge).expanduser().resolve(),
                        Path(args.model).expanduser().resolve(),
                        Path(args.sidecar).expanduser().resolve(),
                    },
                    {output_path},
                )
                rt.atomic_write_json(str(output_path), result)
            exit_code = 0 if result["valid"] else 1
        else:
            result = project_structural_edits(
                structural_baseline=args.structural_baseline,
                enriched_baseline=args.enriched_baseline,
                edited=args.edited,
                bridge=args.bridge,
                output=args.output,
                report=args.report,
            )
            exit_code = 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code
    except EnrichmentError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
