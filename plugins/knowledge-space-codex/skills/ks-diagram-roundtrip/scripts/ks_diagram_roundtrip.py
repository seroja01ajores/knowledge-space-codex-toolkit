#!/usr/bin/env python3
"""Offline KS <-> Diagramm structural round-trip (profile v0.1).

The tool deliberately does not call KS or any network service.  It understands
only new classes (including their descriptions) and new relationships. All
other Diagramm fields are either local-only or must be explicitly acknowledged
as deferred.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import uuid

import ks_roundtrip_io as rio


PROFILE = "structural-v0.1"
MODE = "offline"
DIAGRAM_SCHEMA = "1.2"
SUPPORTED_DIAGRAM_SCHEMAS = {"1.1", DIAGRAM_SCHEMA}
FORMAT_VERSION = "0.1"
TOOL_VERSION = rio.TOOL_VERSION
NORMALIZED_FORMAT = "teamvalue.ks-normalized-structure"
BRIDGE_FORMAT = "teamvalue.ks-diagram-bridge-map"
PLAN_FORMAT = "teamvalue.ks-diagram-change-plan"
BUNDLE_VALIDATION_FORMAT = "teamvalue.ks-diagram-bundle-validation"
NIL_UUID = "00000000-0000-0000-0000-000000000000"
ZERO_UUID = NIL_UUID
DEFAULT_TIME = "1970-01-01T00:00:00Z"
HELPER_PREFIX = "[[_relation_]]_"


class RoundTripError(Exception):
    """A controlled input, policy or invariant failure."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def semantic_sha256(value: Any) -> str:
    """Hash JSON meaning, never a file path or JSON formatting."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise RoundTripError("cannot hash %s: %s" % (path, exc)) from exc
    return digest.hexdigest()


def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RoundTripError("cannot read JSON %s: %s" % (path, exc)) from exc


def atomic_write_json(path: str, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(destination.parent), delete=False
    )
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(handle.name, destination)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def records_from_document(document: Any) -> List[Dict[str, Any]]:
    if isinstance(document, dict) and document.get("format") == rio.DIAGRAM_READ_FORMAT:
        raise RoundTripError(
            "diagram-read-v0.2 is a read-only enrichment artifact, not a KS restore/build payload"
        )
    if isinstance(document, list):
        records = document
    elif isinstance(document, dict) and isinstance(document.get("records"), list):
        records = document["records"]
    else:
        raise RoundTripError("KS source must be a record array or an object.records array")
    if not all(isinstance(record, dict) for record in records):
        raise RoundTripError("every KS record must be an object")
    return records


def diagram_read_records_from_document(document: Any) -> List[Dict[str, Any]]:
    if not isinstance(document, dict) or document.get("format") != rio.DIAGRAM_READ_FORMAT:
        raise RoundTripError("Diagram read model format is not supported")
    if document.get("formatVersion") != FORMAT_VERSION:
        raise RoundTripError("Diagram read model formatVersion is not supported")
    if document.get("profile") != rio.DIAGRAM_READ_PROFILE:
        raise RoundTripError("Diagram read model profile is not supported")
    if document.get("readOnly") is not True:
        raise RoundTripError("Diagram read model must keep readOnly=true")
    if document.get("restorePayload") is not False:
        raise RoundTripError("Diagram read model must keep restorePayload=false")
    if document.get("liveRestoreBlocked") is not True:
        raise RoundTripError("Diagram read model must keep liveRestoreBlocked=true")
    records = document.get("records")
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise RoundTripError("Diagram read model records must be an object array")
    if document.get("classStats") is not None:
        source = document.get("source")
        source_sha256 = source.get("sha256") if isinstance(source, dict) else None
        aggregate_validation = rio.validate_diagram_read_records(
            records,
            class_stats=document.get("classStats"),
            source_type_counts=document.get("sourceCounts"),
            source_sha256=source_sha256,
        )
        if not aggregate_validation.get("valid"):
            raise RoundTripError(
                "Diagram read model classStats are invalid: "
                + "; ".join(aggregate_validation.get("errors", [])[:5])
            )
    return records


def _issue(code: str, message: str, path: str = "") -> Dict[str, str]:
    result = {"code": code, "message": message}
    if path:
        result["path"] = path
    return result


def _record_uuid(record: Dict[str, Any]) -> Optional[str]:
    value = record.get("UUID")
    return value if isinstance(value, str) and value else None


def _data(record: Dict[str, Any]) -> Dict[str, Any]:
    value = record.get("Data")
    return value if isinstance(value, dict) else {}


def _is_ordinary(record: Dict[str, Any]) -> bool:
    data = _data(record)
    return (
        record.get("Type") == "class"
        and data.get("relatedSourceUuid") is None
        and data.get("relatedDestinationUuid") is None
    )


def _is_helper(record: Dict[str, Any]) -> bool:
    data = _data(record)
    return record.get("Type") == "class" and (
        str(data.get("name", "")).startswith(HELPER_PREFIX)
        or data.get("objectEntityCategory") == "undefined"
    ) and data.get("relatedSourceUuid") is not None


def _is_semantic(record: Dict[str, Any], ordinary_ids: set) -> bool:
    data = _data(record)
    return (
        record.get("Type") == "class"
        and not _is_helper(record)
        and data.get("relatedSourceUuid") in ordinary_ids
        and data.get("relatedDestinationUuid") in ordinary_ids
    )


def _relation_ids(data: Dict[str, Any]) -> List[str]:
    result: List[str] = []
    relations = data.get("relations", [])
    if isinstance(relations, list):
        for item in relations:
            if isinstance(item, dict) and isinstance(item.get("uuid"), str):
                result.append(item["uuid"])
    return result


def without_relations(data: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    result.pop("relations", None)
    return result


def _resolve_relation_helpers(
    relation: Dict[str, Any], helper_records: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """Resolve helpers by endpoint side while accepting one legacy orientation.

    The returned helpers are always ordered by semantic endpoint side, not by
    the helper arrow: source-side helper first, target-side helper second.
    """

    relation_uuid = _record_uuid(relation)
    data = _data(relation)
    source_uuid = data.get("relatedSourceUuid")
    target_uuid = data.get("relatedDestinationUuid")
    if not all(isinstance(value, str) and value for value in (relation_uuid, source_uuid, target_uuid)):
        return None, None, None

    def matching(source: str, target: str) -> List[Dict[str, Any]]:
        return [
            helper
            for helper in helper_records
            if _data(helper).get("relatedSourceUuid") == source
            and _data(helper).get("relatedDestinationUuid") == target
        ]

    candidates: List[Tuple[Dict[str, Any], Dict[str, Any], str]] = []

    def add_candidate(
        source_helpers: List[Dict[str, Any]],
        target_helpers: List[Dict[str, Any]],
        orientation: str,
    ) -> None:
        if len(source_helpers) != 1 or len(target_helpers) != 1:
            return
        if _record_uuid(source_helpers[0]) == _record_uuid(target_helpers[0]):
            return
        candidates.append((source_helpers[0], target_helpers[0], orientation))

    add_candidate(
        matching(source_uuid, relation_uuid),
        matching(relation_uuid, target_uuid),
        "canonical",
    )
    # For self-relations the same complete pair also matches the reversed
    # pattern with its two endpoint-side labels swapped. Prefer canonical so a
    # real self-relation is warned about once and remains unambiguous.
    if source_uuid != target_uuid:
        add_candidate(
            matching(relation_uuid, source_uuid),
            matching(target_uuid, relation_uuid),
            "legacy_reversed",
        )

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        relation_members = set(_relation_ids(data))
        bound = [
            candidate
            for candidate in candidates
            if {
                _record_uuid(candidate[0]),
                _record_uuid(candidate[1]),
            }
            == relation_members
        ]
        if len(bound) == 1:
            return bound[0]
    return None, None, None


def _relation_variant_warnings(
    relation_uuid: str, source_uuid: str, target_uuid: str, orientation: str
) -> List[Dict[str, str]]:
    warnings: List[Dict[str, str]] = []
    if orientation == "legacy_reversed":
        warnings.append(_issue(
            "reversed_helper_orientation",
            "relationship %s uses a complete legacy reversed helper orientation; helpers are normalized by endpoint side" % relation_uuid,
        ))
    if source_uuid == target_uuid:
        warnings.append(_issue(
            "existing_self_relationship",
            "existing KS self relationship %s is read-compatible; creating a new self relationship remains forbidden" % relation_uuid,
        ))
    return warnings


def validate_ks_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    by_uuid: Dict[str, Dict[str, Any]] = {}
    duplicate_ids: List[str] = []

    for index, record in enumerate(records):
        record_uuid = _record_uuid(record)
        if record_uuid is None:
            errors.append(_issue("missing_record_uuid", "record UUID is required", "records[%d].UUID" % index))
            continue
        if record_uuid in by_uuid:
            duplicate_ids.append(record_uuid)
        else:
            by_uuid[record_uuid] = record
        data = record.get("Data")
        if not isinstance(data, dict):
            errors.append(_issue("missing_record_data", "record Data must be an object", "records[%d].Data" % index))
            continue
        data_uuid = data.get("uuid")
        if data_uuid is not None and data_uuid != record_uuid:
            errors.append(_issue("uuid_mismatch", "UUID and Data.uuid must match", "records[%d]" % index))
        if record.get("Type") in {"class", "tree", "classL10n", "project"} and not isinstance(data_uuid, str):
            errors.append(_issue("missing_data_uuid", "known structural record requires Data.uuid", "records[%d].Data.uuid" % index))
        if record.get("Type") == "class" and data.get("projectUuid") and record.get("ProjectUUID") != data.get("projectUuid"):
            errors.append(_issue("project_uuid_mismatch", "class wrapper/Data project UUID must match", "records[%d]" % index))

    for value in sorted(set(duplicate_ids)):
        errors.append(_issue("duplicate_record_uuid", "duplicate top-level UUID: %s" % value))

    project_records = [record for record in records if record.get("Type") == "project"]
    if len(project_records) != 1:
        errors.append(_issue("project_count", "expected exactly one project record, got %d" % len(project_records)))

    ordinary_records = [record for record in records if _is_ordinary(record)]
    ordinary_ids = {value for value in (_record_uuid(r) for r in ordinary_records) if value}
    semantic_records = [record for record in records if _is_semantic(record, ordinary_ids)]
    helper_records = [record for record in records if _is_helper(record)]

    tree_by_reference: Dict[str, List[Dict[str, Any]]] = {}
    l10n_by_class: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        data = _data(record)
        if record.get("Type") == "tree" and isinstance(data.get("referenceUuid"), str):
            tree_by_reference.setdefault(data["referenceUuid"], []).append(record)
        if record.get("Type") == "classL10n" and isinstance(data.get("classUuid"), str):
            l10n_by_class.setdefault(data["classUuid"], []).append(record)

    for record in ordinary_records + semantic_records:
        entity_uuid = _record_uuid(record)
        if entity_uuid is None:
            continue
        trees = tree_by_reference.get(entity_uuid, [])
        if len(trees) != 1:
            errors.append(_issue("tree_binding", "entity %s must have exactly one tree record" % entity_uuid))
        if not l10n_by_class.get(entity_uuid):
            errors.append(_issue("missing_class_l10n", "visible entity %s has no classL10n record" % entity_uuid))

    class_records = [record for record in records if record.get("Type") == "class"]
    class_by_uuid = {
        entity_uuid: record
        for record in class_records
        for entity_uuid in [_record_uuid(record)]
        if entity_uuid
    }
    helper_ids = {value for value in (_record_uuid(r) for r in helper_records) if value}

    for relation in semantic_records:
        relation_uuid = _record_uuid(relation)
        if relation_uuid is None:
            continue
        data = _data(relation)
        source_uuid = data.get("relatedSourceUuid")
        target_uuid = data.get("relatedDestinationUuid")
        source_helper, target_helper, helper_orientation = _resolve_relation_helpers(
            relation, helper_records
        )
        if source_helper is None or target_helper is None or helper_orientation is None:
            errors.append(_issue("helper_pair", "relationship %s must have exactly two directional helpers" % relation_uuid))
            continue
        warnings.extend(_relation_variant_warnings(
            relation_uuid, source_uuid, target_uuid, helper_orientation
        ))
        source_helper_uuid = _record_uuid(source_helper)
        target_helper_uuid = _record_uuid(target_helper)
        relation_members = set(_relation_ids(data))
        if relation_members != {source_helper_uuid, target_helper_uuid}:
            errors.append(_issue("relationship_members", "relationship %s must contain exactly its two helpers" % relation_uuid))
        source = class_by_uuid.get(source_uuid)
        target = class_by_uuid.get(target_uuid)
        if source is None or target is None:
            errors.append(_issue("relationship_endpoint", "relationship %s endpoint record is missing" % relation_uuid))
            continue
        source_members = set(_relation_ids(_data(source)))
        target_members = set(_relation_ids(_data(target)))
        if not {source_helper_uuid, relation_uuid}.issubset(source_members):
            errors.append(_issue("source_relation_members", "source of %s is missing helper or relation" % relation_uuid))
        if not {relation_uuid, target_helper_uuid}.issubset(target_members):
            errors.append(_issue("target_relation_members", "target of %s is missing relation or helper" % relation_uuid))
        wrapper_parent = relation.get("ParentRelationUUID")
        if wrapper_parent is not None and wrapper_parent not in {source_uuid, target_uuid}:
            errors.append(_issue("relation_parent", "semantic relation wrapper parent must be an ordinary endpoint or null"))
        elif wrapper_parent != target_uuid:
            warnings.append(_issue("relation_parent_convention", "relationship %s does not use the v0.1 generated target-wrapper convention" % relation_uuid))
        if source_helper.get("ParentRelationUUID") != source_uuid:
            errors.append(_issue("source_helper_parent", "source helper wrapper parent must be source class"))
        if target_helper.get("ParentRelationUUID") != target_uuid:
            errors.append(_issue("target_helper_parent", "target helper wrapper parent must be target class"))
        relation_trees = tree_by_reference.get(relation_uuid, [])
        source_trees = tree_by_reference.get(source_uuid, [])
        if len(relation_trees) == 1 and len(source_trees) == 1:
            if _data(relation_trees[0]).get("parentUuid") != _record_uuid(source_trees[0]):
                warnings.append(_issue("relation_tree_parent_convention", "relationship %s does not use the v0.1 generated source-tree convention" % relation_uuid))

    for record in class_records:
        for member_uuid in _relation_ids(_data(record)):
            if member_uuid not in class_by_uuid:
                errors.append(_issue("missing_relation_member", "Data.relations references missing class UUID %s" % member_uuid))

    tree_records = [record for record in records if record.get("Group") == "class" and record.get("Type") == "tree"]
    tree_ids = {value for value in (_record_uuid(record) for record in tree_records) if value}
    tree_parent: Dict[str, Optional[str]] = {}
    tree_reference_count: Dict[str, int] = {}
    for record in tree_records:
        tree_uuid = _record_uuid(record)
        if tree_uuid is None:
            continue
        data = _data(record)
        parent_uuid = data.get("parentUuid")
        reference_uuid = data.get("referenceUuid")
        tree_parent[tree_uuid] = parent_uuid if isinstance(parent_uuid, str) else None
        if parent_uuid is not None and parent_uuid not in tree_ids:
            errors.append(_issue("missing_tree_parent", "tree %s has missing parent %s" % (tree_uuid, parent_uuid)))
        if reference_uuid is not None:
            if reference_uuid not in by_uuid:
                errors.append(_issue("missing_tree_reference", "tree %s references missing entity %s" % (tree_uuid, reference_uuid)))
            if isinstance(reference_uuid, str):
                tree_reference_count[reference_uuid] = tree_reference_count.get(reference_uuid, 0) + 1
    for tree_uuid in tree_parent:
        cursor: Optional[str] = tree_uuid
        seen: set = set()
        while cursor is not None:
            if cursor in seen:
                errors.append(_issue("tree_parent_cycle", "tree parent cycle detected at %s" % cursor))
                break
            seen.add(cursor)
            cursor = tree_parent.get(cursor)

    visible_ids = ordinary_ids | {
        value for value in (_record_uuid(record) for record in semantic_records) if value
    }
    for entity_uuid in sorted(visible_ids):
        if tree_reference_count.get(entity_uuid, 0) != 1:
            errors.append(_issue("visible_tree_closure", "visible entity %s must have exactly one tree node" % entity_uuid))
        if not l10n_by_class.get(entity_uuid):
            errors.append(_issue("visible_l10n_closure", "visible entity %s must have classL10n" % entity_uuid))
    for helper_uuid in sorted(helper_ids):
        if tree_reference_count.get(helper_uuid, 0) or l10n_by_class.get(helper_uuid):
            errors.append(_issue("helper_visibility", "helper %s must not have tree or classL10n" % helper_uuid))
    for class_uuid, l10n_records in l10n_by_class.items():
        if class_uuid not in visible_ids:
            for l10n_record in l10n_records:
                errors.append(_issue("l10n_non_visible", "classL10n %s references non-visible class %s" % (_record_uuid(l10n_record), class_uuid)))

    indicators = [record for record in records if record.get("Group") == "class" and record.get("Type") == "indicator"]
    indicator_ids = {value for value in (_record_uuid(record) for record in indicators) if value}
    indicator_owner: Dict[str, str] = {}
    for indicator in indicators:
        indicator_uuid = _record_uuid(indicator)
        if indicator_uuid is None:
            continue
        owner_uuid = _data(indicator).get("classUuid")
        if isinstance(owner_uuid, str):
            indicator_owner[indicator_uuid] = owner_uuid
        if owner_uuid not in visible_ids:
            errors.append(_issue("indicator_owner", "indicator %s has missing visible owner %s" % (indicator_uuid, owner_uuid)))
        if tree_reference_count.get(indicator_uuid, 0) != 1:
            errors.append(_issue("indicator_tree_closure", "indicator %s must have exactly one tree node" % indicator_uuid))
    formulas = [record for record in records if record.get("Group") == "class" and record.get("Type") == "formula"]
    for formula in formulas:
        formula_uuid = _record_uuid(formula)
        data = _data(formula)
        indicator_uuid = data.get("indicatorUuid")
        owner_uuid = data.get("classUuid")
        if indicator_uuid not in indicator_ids:
            errors.append(_issue("formula_indicator", "formula %s has missing indicator %s" % (formula_uuid, indicator_uuid)))
        elif indicator_owner.get(indicator_uuid) != owner_uuid:
            errors.append(_issue("formula_owner", "formula %s owner differs from indicator owner" % formula_uuid))

    return {
        "kind": "ks_records",
        "profile": PROFILE,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "records": len(records),
            "ordinaryClasses": len(ordinary_records),
            "semanticRelationships": len(semantic_records),
            "helperRelationships": len(helper_ids),
            "indicators": len(indicators),
            "formulas": len(formulas),
        },
        "semanticCounts": {
            "ordinaryClasses": len(ordinary_records),
            "semanticRelationships": len(semantic_records),
            "helperRelationships": len(helper_ids),
            "indicators": len(indicators),
            "formulas": len(formulas),
        },
    }


def validate_diagram(model: Any) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    if not isinstance(model, dict):
        return {"kind": "diagram", "valid": False, "errors": [_issue("diagram_type", "diagram must be an object")], "warnings": []}
    if model.get("schemaVersion") not in SUPPORTED_DIAGRAM_SCHEMAS:
        errors.append(
            _issue(
                "unsupported_schema",
                "supported Diagramm schemaVersion values are %s"
                % ", ".join(sorted(SUPPORTED_DIAGRAM_SCHEMAS)),
                "schemaVersion",
            )
        )
    classes = model.get("classes")
    relationships = model.get("relationships")
    if not isinstance(classes, list):
        errors.append(_issue("classes_type", "classes must be an array", "classes"))
        classes = []
    if not isinstance(relationships, list):
        errors.append(_issue("relationships_type", "relationships must be an array", "relationships"))
        relationships = []
    class_ids: List[str] = []
    relationship_ids: List[str] = []
    for index, item in enumerate(classes):
        path = "classes[%d]" % index
        if not isinstance(item, dict):
            errors.append(_issue("class_type", "class must be an object", path))
            continue
        entity_id = item.get("id")
        if not isinstance(entity_id, str) or not entity_id:
            errors.append(_issue("missing_class_id", "class id is required", path + ".id"))
            continue
        class_ids.append(entity_id)
        if not isinstance(item.get("name"), str) or not item.get("name", "").strip():
            errors.append(_issue("missing_class_name", "class name is required", path + ".name"))
        for field in ("attributes", "indicators"):
            if not isinstance(item.get(field), list):
                errors.append(_issue("class_field_type", "%s must be an array" % field, path + "." + field))
        for indicator_index, indicator in enumerate(item.get("indicators", []) if isinstance(item.get("indicators"), list) else []):
            if not isinstance(indicator, dict) or indicator.get("ownerType") != "class" or indicator.get("ownerId") != entity_id:
                errors.append(_issue("indicator_owner", "class indicator owner must match its class", "%s.indicators[%d]" % (path, indicator_index)))
    for index, item in enumerate(relationships):
        path = "relationships[%d]" % index
        if not isinstance(item, dict):
            errors.append(_issue("relationship_type", "relationship must be an object", path))
            continue
        entity_id = item.get("id")
        if not isinstance(entity_id, str) or not entity_id:
            errors.append(_issue("missing_relationship_id", "relationship id is required", path + ".id"))
            continue
        relationship_ids.append(entity_id)
        if not isinstance(item.get("name"), str) or not item.get("name", "").strip():
            errors.append(_issue("missing_relationship_name", "relationship name is required", path + ".name"))
        for endpoint in ("sourceClassId", "targetClassId"):
            if item.get(endpoint) not in class_ids:
                errors.append(_issue("broken_relationship_endpoint", "%s does not name a class" % endpoint, path + "." + endpoint))
        indicators = item.get("indicators")
        if not isinstance(indicators, list):
            errors.append(_issue("relationship_indicators_type", "indicators must be an array", path + ".indicators"))
            indicators = []
        for indicator_index, indicator in enumerate(indicators):
            if not isinstance(indicator, dict) or indicator.get("ownerType") != "relationship" or indicator.get("ownerId") != entity_id:
                errors.append(_issue("indicator_owner", "relationship indicator owner must match its relationship", "%s.indicators[%d]" % (path, indicator_index)))
    for value in sorted({value for value in class_ids if class_ids.count(value) > 1}):
        errors.append(_issue("duplicate_class_id", "duplicate class id: %s" % value))
    for value in sorted({value for value in relationship_ids if relationship_ids.count(value) > 1}):
        errors.append(_issue("duplicate_relationship_id", "duplicate relationship id: %s" % value))
    for value in sorted(set(class_ids).intersection(relationship_ids)):
        errors.append(_issue("cross_type_id_collision", "id is shared by a class and relationship: %s" % value))
    return {
        "kind": "diagram",
        "profile": PROFILE,
        "schemaVersion": model.get("schemaVersion"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {"classes": len(classes), "relationships": len(relationships)},
    }


def _require_valid(report: Dict[str, Any], label: str) -> None:
    if not report.get("valid"):
        first = report.get("errors", [{}])[0]
        raise RoundTripError("%s validation failed: %s" % (label, first.get("message", "unknown error")))


def _index_structure(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    project_records = [record for record in records if record.get("Type") == "project"]
    if len(project_records) != 1:
        raise RoundTripError("KS source must contain exactly one project record")
    ordinary = [record for record in records if _is_ordinary(record)]
    ordinary_ids = {value for value in (_record_uuid(r) for r in ordinary) if value}
    semantic = [record for record in records if _is_semantic(record, ordinary_ids)]
    helpers = [record for record in records if _is_helper(record)]
    trees: Dict[str, Dict[str, Any]] = {}
    l10n: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        data = _data(record)
        if record.get("Type") == "tree" and isinstance(data.get("referenceUuid"), str):
            trees[data["referenceUuid"]] = record
        if record.get("Type") == "classL10n" and isinstance(data.get("classUuid"), str):
            l10n.setdefault(data["classUuid"], []).append(record)
    return {
        "project": project_records[0],
        "ordinary": ordinary,
        "semantic": semantic,
        "helpers": helpers,
        "trees": trees,
        "l10n": l10n,
    }


def _localized_name(record: Dict[str, Any], l10n: Dict[str, List[Dict[str, Any]]]) -> str:
    entity_uuid = _record_uuid(record)
    candidates = l10n.get(entity_uuid or "", [])
    candidates = sorted(candidates, key=lambda item: _data(item).get("code") != "ru_RU")
    for candidate in candidates:
        value = _data(candidate).get("name")
        if isinstance(value, str) and value:
            return value
    value = _data(record).get("name", record.get("Name", ""))
    return value if isinstance(value, str) else ""


def from_ks(records: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    report = validate_ks_records(records)
    _require_valid(report, "KS source")
    structure = _index_structure(records)
    project_data = _data(structure["project"])
    project_uuid = project_data.get("uuid")
    if not isinstance(project_uuid, str) or not project_uuid:
        raise RoundTripError("project Data.uuid is required")
    created_at = project_data.get("createdAt") if isinstance(project_data.get("createdAt"), str) else DEFAULT_TIME
    updated_at = project_data.get("updatedAt") if isinstance(project_data.get("updatedAt"), str) else created_at
    classes: List[Dict[str, Any]] = []
    normalized_classes: List[Dict[str, Any]] = []
    class_ids: Dict[str, str] = {}
    for index, record in enumerate(structure["ordinary"]):
        entity_uuid = _record_uuid(record)
        if entity_uuid is None:
            raise RoundTripError("ordinary class is missing UUID")
        diagram_id = "ks-class:" + entity_uuid
        class_ids[entity_uuid] = diagram_id
        data = _data(record)
        tree = structure["trees"].get(entity_uuid, {})
        tree_data = _data(tree)
        name = _localized_name(record, structure["l10n"])
        classes.append({
            "id": diagram_id,
            "name": name,
            "description": data.get("description", "") if isinstance(data.get("description", ""), str) else "",
            "stereotype": "KS class",
            "attributes": [],
            "indicators": [],
            "ksProperties": [],
            "position": {"x": 80 + (index % 4) * 340, "y": 80 + (index // 4) * 260},
            "size": {"width": 260, "height": 180},
            "notes": "Existing KS entity; updates are deferred in pilot.",
        })
        normalized_classes.append({
            "entityUuid": entity_uuid,
            "treeNodeUuid": _record_uuid(tree),
            "parentTreeNodeUuid": tree_data.get("parentUuid"),
            "name": name,
            "description": data.get("description", ""),
            "updatedAt": data.get("updatedAt"),
        })
    relationships: List[Dict[str, Any]] = []
    normalized_relationships: List[Dict[str, Any]] = []
    source_warnings: List[Dict[str, str]] = []
    for record in structure["semantic"]:
        entity_uuid = _record_uuid(record)
        if entity_uuid is None:
            raise RoundTripError("semantic relationship is missing UUID")
        data = _data(record)
        source_uuid = data.get("relatedSourceUuid")
        target_uuid = data.get("relatedDestinationUuid")
        if source_uuid not in class_ids or target_uuid not in class_ids:
            raise RoundTripError("relationship %s has an unknown endpoint" % entity_uuid)
        source_helper, target_helper, helper_orientation = _resolve_relation_helpers(
            record, structure["helpers"]
        )
        if source_helper is None or target_helper is None or helper_orientation is None:
            raise RoundTripError("relationship %s helper pair cannot be resolved" % entity_uuid)
        relation_warnings = _relation_variant_warnings(
            entity_uuid, source_uuid, target_uuid, helper_orientation
        )
        source_warnings.extend(relation_warnings)
        diagram_id = "ks-relation:" + entity_uuid
        name = _localized_name(record, structure["l10n"])
        relationship_notes = "Existing KS relation; type and cardinality are visual-only in pilot."
        if relation_warnings:
            relationship_notes += " Source warning: " + " ".join(
                item["message"] for item in relation_warnings
            )
        relationships.append({
            "id": diagram_id,
            "sourceClassId": class_ids[source_uuid],
            "targetClassId": class_ids[target_uuid],
            "type": "association",
            "name": name,
            "description": data.get("description", "") if isinstance(data.get("description", ""), str) else "",
            "direction": "source_to_target",
            "cardinality": "* → *",
            "indicators": [],
            "ksProperties": [],
            "notes": relationship_notes,
        })
        tree = structure["trees"].get(entity_uuid, {})
        normalized_relationships.append({
            "entityUuid": entity_uuid,
            "treeNodeUuid": _record_uuid(tree),
            "parentTreeNodeUuid": _data(tree).get("parentUuid"),
            "name": name,
            "description": data.get("description", ""),
            "updatedAt": data.get("updatedAt"),
            "sourceEntityUuid": source_uuid,
            "destinationEntityUuid": target_uuid,
            "sourceHelperUuid": _record_uuid(source_helper),
            "targetHelperUuid": _record_uuid(target_helper),
            "helperOrientation": helper_orientation,
            "sourceWarnings": relation_warnings,
            "sourceObjectsLimit": data.get("sourceObjectsLimit", 0),
            "destinationObjectsLimit": data.get("destinationObjectsLimit", 0),
            "strictRelation": data.get("strictRelation", False),
        })
    model = {
        "id": "ks-project:" + project_uuid,
        "name": "%s — Diagram" % project_data.get("name", structure["project"].get("Name", "KS project")),
        "description": project_data.get("description", ""),
        "projectContext": "Imported from an offline KS structural snapshot",
        "version": "0.1",
        "schemaVersion": DIAGRAM_SCHEMA,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "classes": classes,
        "frames": [],
        "relationships": relationships,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "sourceWarnings": source_warnings,
    }
    source_hash = semantic_sha256(records)
    normalized = {
        "format": NORMALIZED_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "profile": PROFILE,
        "source": {"projectUuid": project_uuid, "semanticSha256": source_hash},
        "project": {
            "entityUuid": project_uuid,
            "name": project_data.get("name", structure["project"].get("Name", "KS project")),
            "description": project_data.get("description", ""),
            "createdAt": created_at,
            "updatedAt": updated_at,
        },
        "classes": normalized_classes,
        "relationships": normalized_relationships,
        "sourceWarnings": source_warnings,
        "excludedHelperEntityUuids": sorted(filter(None, (_record_uuid(r) for r in structure["helpers"]))),
        "excluded": {
            "helperRelationEntityUuids": sorted(filter(None, (_record_uuid(r) for r in structure["helpers"]))),
            "semanticRelationships": [],
            "businessData": "out_of_scope",
        },
        "invariants": {
            "relationTriple": "S -> Hs -> R -> Ht -> T",
            "objectCount": "read_only_derived",
            "nameMatching": "forbidden",
        },
    }
    bridge = {
        "format": BRIDGE_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "status": "offline_unbound",
        "profile": PROFILE,
        "mappingProfile": PROFILE,
        "mode": MODE,
        "diagram": {
            "modelId": model["id"],
            "schemaVersion": DIAGRAM_SCHEMA,
            "baselineSemanticSha256": semantic_sha256(model),
        },
        "source": {
            "kind": "local_backup",
            "backupProjectUuid": project_uuid,
            "backupSha256": source_hash,
            "projectUuid": project_uuid,
            "semanticSha256": source_hash,
            "normalizedSemanticSha256": semantic_sha256(normalized),
        },
        "target": {
            "mode": "restore_to_new_project",
            "stand": None,
            "projectUuid": None,
            "projectName": None,
        },
        "entityMap": {
            "classes": [
                {
                    "diagramId": "ks-class:" + item["entityUuid"],
                    "ksEntityUuid": item["entityUuid"],
                    "ksTreeNodeUuid": item["treeNodeUuid"],
                    "baselineUpdatedAt": item["updatedAt"],
                }
                for item in normalized_classes
            ],
            "relationships": [
                {
                    "diagramId": "ks-relation:" + item["entityUuid"],
                    "ksEntityUuid": item["entityUuid"],
                    "ksTreeNodeUuid": item["treeNodeUuid"],
                    "sourceKsEntityUuid": item["sourceEntityUuid"],
                    "targetKsEntityUuid": item["destinationEntityUuid"],
                    "sourceHelperUuid": item["sourceHelperUuid"],
                    "targetHelperUuid": item["targetHelperUuid"],
                    "helperOrientation": item["helperOrientation"],
                    "sourceWarnings": item["sourceWarnings"],
                    "baselineUpdatedAt": item["updatedAt"],
                }
                for item in normalized_relationships
            ],
        },
        "sourceWarnings": source_warnings,
        "writePolicy": {
            "allowedIntents": ["create_class", "create_relationship"],
            "localOnlyFields": ["position", "size", "frames", "viewport", "updatedAt"],
            "deferredIntents": ["update_existing_class", "update_existing_relationship", "delete_existing_class", "delete_existing_relationship", "indicator_change", "formula_change"],
            "requiresBoundDisposableTarget": False,
            "stopOnFirstError": True,
            "readBackRequired": True,
            "supported": ["create_class", "create_relationship"],
            "deferred": ["attributes", "indicators", "objectCount", "relationship.type", "relationship.direction", "relationship.cardinality", "relationship.notes"],
            "forbidden": ["deletions", "relationship_endpoint_changes"],
        },
    }
    return model, bridge, normalized


def validate_bridge(bridge: Any) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    if not isinstance(bridge, dict):
        return {"kind": "bridge", "valid": False, "errors": [_issue("bridge_type", "bridge must be an object")], "warnings": []}
    if bridge.get("format") != BRIDGE_FORMAT:
        errors.append(_issue("bridge_format", "unknown bridge format", "format"))
    if bridge.get("formatVersion") != FORMAT_VERSION:
        errors.append(_issue("bridge_version", "unknown bridge formatVersion", "formatVersion"))
    if bridge.get("profile") not in (None, PROFILE):
        errors.append(_issue("unsupported_profile", "only profile %s is supported" % PROFILE, "profile"))
    if bridge.get("mappingProfile") not in (None, PROFILE):
        errors.append(_issue("unsupported_profile", "only mappingProfile %s is supported" % PROFILE, "mappingProfile"))
    if bridge.get("mode") not in (None, MODE):
        errors.append(_issue("unsupported_mode", "only mode %s is supported" % MODE, "mode"))
    if not isinstance(bridge.get("source"), dict) or not isinstance(bridge["source"].get("semanticSha256"), str):
        errors.append(_issue("bridge_source_binding", "bridge source semanticSha256 is required", "source.semanticSha256"))
    diagram = bridge.get("diagram")
    if not isinstance(diagram, dict):
        errors.append(_issue("bridge_diagram", "bridge diagram binding is required", "diagram"))
    else:
        if diagram.get("schemaVersion") not in SUPPORTED_DIAGRAM_SCHEMAS:
            errors.append(
                _issue(
                    "unsupported_schema",
                    "bridge must bind a supported Diagramm schemaVersion",
                    "diagram.schemaVersion",
                )
            )
        if diagram.get("baselineSemanticSha256") is not None and not isinstance(diagram.get("baselineSemanticSha256"), str):
            errors.append(_issue("bridge_baseline_binding", "baselineSemanticSha256 must be a string when present", "diagram.baselineSemanticSha256"))
    entity_map = bridge.get("entityMap")
    if not isinstance(entity_map, dict):
        errors.append(_issue("bridge_entity_map", "entityMap is required", "entityMap"))
    else:
        for collection in ("classes", "relationships"):
            entries = entity_map.get(collection)
            if not isinstance(entries, list):
                errors.append(_issue("bridge_entity_map", "entityMap.%s must be an array" % collection, "entityMap." + collection))
                continue
            seen: set = set()
            for index, entry in enumerate(entries):
                path = "entityMap.%s[%d]" % (collection, index)
                if not isinstance(entry, dict):
                    errors.append(_issue("bridge_map_entry", "map entry must be an object", path))
                    continue
                diagram_id = entry.get("diagramId")
                ks_uuid = entry.get("ksEntityUuid")
                if not isinstance(diagram_id, str) or not diagram_id:
                    errors.append(_issue("bridge_diagram_id", "diagramId is required", path + ".diagramId"))
                elif diagram_id in seen:
                    errors.append(_issue("bridge_duplicate_id", "duplicate bridge diagramId: %s" % diagram_id, path + ".diagramId"))
                else:
                    seen.add(diagram_id)
                if not isinstance(ks_uuid, str) or not ks_uuid:
                    errors.append(_issue("bridge_ks_id", "ksEntityUuid is required", path + ".ksEntityUuid"))
    return {"kind": "bridge", "profile": bridge.get("profile"), "mode": bridge.get("mode"), "valid": not errors, "errors": errors, "warnings": []}


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _deferred_path(collection: str, entity_id: str, field: str) -> str:
    return "/%s/%s/%s" % (collection, _escape_pointer(entity_id), field)


def _by_id(items: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result[item["id"]] = item
    return result


def _mapped_entries(bridge: Dict[str, Any], collection: str) -> List[Dict[str, Any]]:
    entity_map = bridge.get("entityMap", {})
    entries = entity_map.get(collection, []) if isinstance(entity_map, dict) else []
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def create_diff_plan(
    source_records: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    edited: Dict[str, Any],
    bridge: Dict[str, Any],
    artifact_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    ks_validation = validate_ks_records(source_records)
    baseline_validation = validate_diagram(baseline)
    edited_validation = validate_diagram(edited)
    bridge_validation = validate_bridge(bridge)
    errors: List[Dict[str, str]] = []
    for label, report in (
        ("source", ks_validation),
        ("baseline", baseline_validation),
        ("edited", edited_validation),
        ("bridge", bridge_validation),
    ):
        for issue in report.get("errors", []):
            copied = dict(issue)
            copied["scope"] = label
            errors.append(copied)

    binding = {
        "profile": PROFILE,
        "mode": MODE,
        "sourceSemanticSha256": semantic_sha256(source_records),
        "baselineSemanticSha256": semantic_sha256(baseline),
        "editedSemanticSha256": semantic_sha256(edited),
        "bridgeSemanticSha256": semantic_sha256(bridge),
    }
    source_binding = bridge.get("source", {}) if isinstance(bridge, dict) else {}
    diagram_binding = bridge.get("diagram", {}) if isinstance(bridge, dict) else {}
    if source_binding.get("semanticSha256") != binding["sourceSemanticSha256"]:
        errors.append(_issue("source_binding_mismatch", "source records do not match the bridge semantic hash", "binding.sourceSemanticSha256"))
    if diagram_binding.get("baselineSemanticSha256") is not None and diagram_binding.get("baselineSemanticSha256") != binding["baselineSemanticSha256"]:
        errors.append(_issue("baseline_binding_mismatch", "baseline diagram does not match the bridge semantic hash", "binding.baselineSemanticSha256"))
    if baseline.get("id") != edited.get("id"):
        errors.append(_issue("model_id_change", "edited model id must equal baseline model id", "edited.id"))
    if diagram_binding.get("modelId") != baseline.get("id"):
        errors.append(_issue("bridge_model_mismatch", "bridge modelId does not match baseline model id", "bridge.diagram.modelId"))
    if baseline.get("schemaVersion") != edited.get("schemaVersion"):
        errors.append(
            _issue(
                "diagram_schema_mismatch",
                "edited schemaVersion must equal baseline schemaVersion",
                "edited.schemaVersion",
            )
        )
    if diagram_binding.get("schemaVersion") != baseline.get("schemaVersion"):
        errors.append(
            _issue(
                "bridge_schema_mismatch",
                "bridge schemaVersion does not match baseline schemaVersion",
                "bridge.diagram.schemaVersion",
            )
        )
    target_binding = bridge.get("target", {}) if isinstance(bridge.get("target"), dict) else {}
    target_mode = target_binding.get("mode") or "restore_to_new_project"
    if target_mode != "restore_to_new_project":
        errors.append(_issue("target_mode", "structural-v0.1 only permits eventual restore_to_new_project", "bridge.target.mode"))

    baseline_classes = _by_id(baseline.get("classes"))
    edited_classes = _by_id(edited.get("classes"))
    baseline_relationships = _by_id(baseline.get("relationships"))
    edited_relationships = _by_id(edited.get("relationships"))
    mapped_classes = {
        entry.get("diagramId"): entry
        for entry in _mapped_entries(bridge, "classes")
        if isinstance(entry.get("diagramId"), str)
    }
    mapped_relationships = {
        entry.get("diagramId"): entry
        for entry in _mapped_entries(bridge, "relationships")
        if isinstance(entry.get("diagramId"), str)
    }
    for diagram_id in mapped_classes:
        if diagram_id not in baseline_classes:
            errors.append(_issue("mapped_class_missing_baseline", "mapped class is missing from baseline: %s" % diagram_id))
    for diagram_id in mapped_relationships:
        if diagram_id not in baseline_relationships:
            errors.append(_issue("mapped_relationship_missing_baseline", "mapped relationship is missing from baseline: %s" % diagram_id))
    for diagram_id in sorted(set(baseline_classes) - set(mapped_classes)):
        errors.append(_issue("baseline_class_missing_bridge", "baseline class is missing from bridge: %s" % diagram_id))
    for diagram_id in sorted(set(baseline_relationships) - set(mapped_relationships)):
        errors.append(_issue("baseline_relationship_missing_bridge", "baseline relationship is missing from bridge: %s" % diagram_id))
    for diagram_id, relationship in baseline_relationships.items():
        entry = mapped_relationships.get(diagram_id)
        if entry is None:
            continue
        source_entry = mapped_classes.get(relationship.get("sourceClassId"))
        target_entry = mapped_classes.get(relationship.get("targetClassId"))
        if source_entry and entry.get("sourceKsEntityUuid") != source_entry.get("ksEntityUuid"):
            errors.append(_issue("bridge_relationship_source", "bridge relationship source mapping is inconsistent: %s" % diagram_id))
        if target_entry and entry.get("targetKsEntityUuid") != target_entry.get("ksEntityUuid"):
            errors.append(_issue("bridge_relationship_target", "bridge relationship target mapping is inconsistent: %s" % diagram_id))

    operations: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    local_only: List[Dict[str, Any]] = []
    forbidden: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []

    for diagram_id, entry in mapped_classes.items():
        before = baseline_classes.get(diagram_id)
        after = edited_classes.get(diagram_id)
        if before is None:
            continue
        if after is None:
            forbidden.append({"path": "/classes/%s" % _escape_pointer(diagram_id), "code": "delete_existing_class", "diagramId": diagram_id})
            continue
        if before.get("name") != after.get("name"):
            unsupported.append({"path": _deferred_path("classes", diagram_id, "name"), "code": "rename_existing_class", "diagramId": diagram_id})
        for field in ("description", "stereotype", "attributes", "indicators", "objectCount", "notes"):
            if before.get(field) != after.get(field):
                deferred.append({
                    "path": _deferred_path("classes", diagram_id, field),
                    "entityType": "class",
                    "diagramId": diagram_id,
                    "field": field,
                    "before": before.get(field),
                    "after": after.get(field),
                    "reason": "field is not mapped by structural-v0.1",
                })
        for field in ("position", "size"):
            if before.get(field) != after.get(field):
                local_only.append({"path": _deferred_path("classes", diagram_id, field), "entityType": "class", "diagramId": diagram_id, "field": field})

    for diagram_id, item in edited_classes.items():
        if diagram_id in mapped_classes:
            continue
        operations.append({
            "intent": "create_class",
            "diagramId": diagram_id,
            "name": item.get("name"),
            "description": item.get("description", ""),
        })
        if "stereotype" in item:
            deferred.append({"path": _deferred_path("classes", diagram_id, "stereotype"), "entityType": "class", "diagramId": diagram_id, "field": "stereotype", "after": item.get("stereotype"), "reason": "stereotype has no KS mapping in v0.1"})
        for field in ("attributes", "indicators"):
            value = item.get(field, [])
            if value:
                deferred.append({"path": _deferred_path("classes", diagram_id, field), "entityType": "class", "diagramId": diagram_id, "field": field, "after": value, "reason": "field is not mapped by structural-v0.1"})
        if "objectCount" in item:
            deferred.append({"path": _deferred_path("classes", diagram_id, "objectCount"), "entityType": "class", "diagramId": diagram_id, "field": "objectCount", "after": item.get("objectCount"), "reason": "display metadata must never create KS objects"})
        if item.get("notes"):
            deferred.append({"path": _deferred_path("classes", diagram_id, "notes"), "entityType": "class", "diagramId": diagram_id, "field": "notes", "after": item.get("notes"), "reason": "class notes are Diagramm-only in structural-v0.1"})

    for diagram_id, entry in mapped_relationships.items():
        before = baseline_relationships.get(diagram_id)
        after = edited_relationships.get(diagram_id)
        if before is None:
            continue
        if after is None:
            forbidden.append({"path": "/relationships/%s" % _escape_pointer(diagram_id), "code": "delete_existing_relationship", "diagramId": diagram_id})
            continue
        if before.get("sourceClassId") != after.get("sourceClassId") or before.get("targetClassId") != after.get("targetClassId"):
            forbidden.append({"path": "/relationships/%s/endpoints" % _escape_pointer(diagram_id), "code": "change_relationship_endpoints", "diagramId": diagram_id})
        for field in ("name", "description"):
            if before.get(field) != after.get(field):
                unsupported.append({"path": _deferred_path("relationships", diagram_id, field), "code": "update_existing_relationship_%s" % field, "diagramId": diagram_id})
        for field in ("type", "direction", "cardinality", "indicators", "notes"):
            if before.get(field) != after.get(field):
                deferred.append({"path": _deferred_path("relationships", diagram_id, field), "entityType": "relationship", "diagramId": diagram_id, "field": field, "before": before.get(field), "after": after.get(field), "reason": "field is not mapped by structural-v0.1"})

    known_class_ids = set(edited_classes)
    for diagram_id, item in edited_relationships.items():
        if diagram_id in mapped_relationships:
            continue
        source_id = item.get("sourceClassId")
        target_id = item.get("targetClassId")
        if source_id == target_id:
            forbidden.append({"path": "/relationships/%s/endpoints" % _escape_pointer(diagram_id), "code": "self_relationship_unsupported", "diagramId": diagram_id})
        if source_id not in known_class_ids or target_id not in known_class_ids:
            errors.append(_issue("new_relationship_endpoint", "new relationship %s has an unknown endpoint" % diagram_id))
        operations.append({
            "intent": "create_relationship",
            "diagramId": diagram_id,
            "name": item.get("name"),
            "sourceClassId": source_id,
            "targetClassId": target_id,
            "description": item.get("description", ""),
        })
        for field in ("type", "direction", "cardinality"):
            deferred.append({"path": _deferred_path("relationships", diagram_id, field), "entityType": "relationship", "diagramId": diagram_id, "field": field, "after": item.get(field), "reason": "visual relationship metadata is deferred in v0.1"})
        for field in ("indicators", "notes"):
            value = item.get(field, [] if field == "indicators" else "")
            if value:
                deferred.append({"path": _deferred_path("relationships", diagram_id, field), "entityType": "relationship", "diagramId": diagram_id, "field": field, "after": value, "reason": "field is not mapped by structural-v0.1"})

    model_local_fields = ("name", "description", "projectContext", "version", "updatedAt", "frames", "viewport")
    changed_model_fields = [field for field in model_local_fields if baseline.get(field) != edited.get(field)]
    if changed_model_fields:
        local_only.append({"path": "/model", "entityType": "model", "fields": changed_model_fields})

    operations.sort(key=lambda item: (0 if item["intent"] == "create_class" else 1, item.get("diagramId", "")))
    deferred.sort(key=lambda item: item["path"])
    forbidden.sort(key=lambda item: item["path"])
    unsupported.sort(key=lambda item: item["path"])
    write_policy = bridge.get("writePolicy", {}) if isinstance(bridge, dict) else {}
    allowed_values = write_policy.get("allowedIntents", write_policy.get("supported", [])) if isinstance(write_policy, dict) else []
    allowed_intents = set(allowed_values) if isinstance(allowed_values, list) else set()
    for operation in operations:
        if operation.get("intent") not in allowed_intents:
            errors.append(_issue("write_policy", "intent %s is outside bridge writePolicy.allowedIntents" % operation.get("intent")))
    required_acceptances = [item["path"] for item in deferred]
    if artifact_hashes is None:
        artifact_hashes = {
            "sourceSha256": binding["sourceSemanticSha256"],
            "baselineSha256": binding["baselineSemanticSha256"],
            "editedSha256": binding["editedSemanticSha256"],
            "bridgeSha256": binding["bridgeSemanticSha256"],
        }
        artifact_hash_mode = "semantic_fallback"
    else:
        required_hashes = {"sourceSha256", "baselineSha256", "editedSha256", "bridgeSha256"}
        missing_hashes = sorted(required_hashes - set(artifact_hashes))
        invalid_hashes = sorted(key for key in required_hashes if not isinstance(artifact_hashes.get(key), str) or len(artifact_hashes.get(key, "")) != 64)
        if missing_hashes or invalid_hashes:
            errors.append(_issue("artifact_hash_binding", "four valid byte SHA-256 artifact hashes are required"))
        artifact_hashes = {key: artifact_hashes.get(key) for key in sorted(required_hashes)}
        artifact_hash_mode = "byte_sha256"
    apply_blocked_reasons: List[str] = []
    if errors:
        apply_blocked_reasons.append("validation_errors")
    if forbidden:
        apply_blocked_reasons.append("forbidden_changes")
    if unsupported:
        apply_blocked_reasons.append("unsupported_changes")
    return {
        "format": PLAN_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "profile": PROFILE,
        "mappingProfile": PROFILE,
        "mode": MODE,
        "binding": binding,
        "artifactHashes": artifact_hashes,
        "artifactHashMode": artifact_hash_mode,
        "modelId": baseline.get("id"),
        "bridgeFormat": bridge.get("format"),
        "targetMode": target_mode,
        "offlineBuildBlocked": bool(apply_blocked_reasons),
        "liveRestoreBlocked": True,
        "requiredLiveRestorePreflight": "approved_destructive safe-restore-readback preflight",
        "validation": {
            "valid": not errors,
            "errors": errors,
            "source": ks_validation,
            "baseline": baseline_validation,
            "edited": edited_validation,
            "bridge": bridge_validation,
        },
        "summary": {
            "supportedOperations": len(operations),
            "createClasses": sum(item["intent"] == "create_class" for item in operations),
            "createRelationships": sum(item["intent"] == "create_relationship" for item in operations),
            "updateClassDescriptions": 0,
            "deferredChanges": len(deferred),
            "localOnlyChanges": len(local_only),
            "forbiddenChanges": len(forbidden),
            "unsupportedChanges": len(unsupported),
            "applyBlocked": bool(apply_blocked_reasons),
        },
        "operations": operations,
        "deferredChanges": deferred,
        "requiredDeferredAcceptances": required_acceptances,
        "localOnlyChanges": local_only,
        "forbiddenChanges": forbidden,
        "unsupportedChanges": unsupported,
        "applyBlockedReasons": apply_blocked_reasons,
        "hardErrors": [item.get("message", item.get("code", "error")) for item in errors],
    }


class BuildBlocked(RoundTripError):
    def __init__(self, message: str, report: Dict[str, Any]):
        super().__init__(message)
        self.report = report


def verify_reviewed_plan(
    persisted_plan: Any,
    recomputed_plan: Dict[str, Any],
    accepted_paths: Sequence[str],
) -> Dict[str, Any]:
    persisted_hash = semantic_sha256(persisted_plan)
    recomputed_hash = semantic_sha256(recomputed_plan)
    plan_matches = isinstance(persisted_plan, dict) and canonical_bytes(persisted_plan) == canonical_bytes(recomputed_plan)
    required = set(recomputed_plan.get("requiredDeferredAcceptances", []))
    accepted_list = list(accepted_paths)
    accepted = set(accepted_list)
    duplicate_acceptances = sorted({path for path in accepted_list if accepted_list.count(path) > 1})
    missing = sorted(required - accepted)
    unknown = sorted(accepted - required)
    report = {
        "planBinding": {
            "persistedPlanSemanticSha256": persisted_hash,
            "recomputedPlanSemanticSha256": recomputed_hash,
            "matches": plan_matches,
            "sourceSemanticSha256": recomputed_plan.get("binding", {}).get("sourceSemanticSha256"),
            "baselineSemanticSha256": recomputed_plan.get("binding", {}).get("baselineSemanticSha256"),
            "editedSemanticSha256": recomputed_plan.get("binding", {}).get("editedSemanticSha256"),
            "bridgeSemanticSha256": recomputed_plan.get("binding", {}).get("bridgeSemanticSha256"),
            "artifactHashMode": recomputed_plan.get("artifactHashMode"),
            "artifactHashes": recomputed_plan.get("artifactHashes"),
        },
        "deferredAcceptance": {
            "required": sorted(required),
            "accepted": sorted(accepted),
            "missing": missing,
            "unknown": unknown,
            "duplicates": duplicate_acceptances,
            "complete": not missing and not unknown and not duplicate_acceptances,
        },
        "planApplyBlockedReasons": recomputed_plan.get("applyBlockedReasons", []),
        "acceptedDeferredPaths": sorted(accepted_list),
        "offlineBuildBlocked": not (plan_matches and not missing and not unknown and not duplicate_acceptances and not recomputed_plan.get("applyBlockedReasons")),
        "liveRestoreBlocked": True,
        "requiredLiveRestorePreflight": "approved_destructive safe-restore-readback preflight",
        "ready": plan_matches and not missing and not unknown and not duplicate_acceptances and not recomputed_plan.get("applyBlockedReasons"),
    }
    return report


def _uuid_namespace(project_uuid: str) -> uuid.UUID:
    try:
        return uuid.UUID(project_uuid)
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_URL, "ks-project:" + str(project_uuid))


def _generated_uuid(namespace: uuid.UUID, kind: str, diagram_id: str, existing: set) -> str:
    if kind in ("class", "relationship"):
        try:
            candidate = str(uuid.UUID(diagram_id))
        except (ValueError, AttributeError):
            candidate = ""
        if candidate and candidate not in existing and candidate != NIL_UUID:
            existing.add(candidate)
            return candidate
    counter = 0
    while True:
        suffix = "%s:%s" % (kind, diagram_id)
        if counter:
            suffix += ":%d" % counter
        candidate = str(uuid.uuid5(namespace, suffix))
        if candidate not in existing and candidate != NIL_UUID:
            existing.add(candidate)
            return candidate
        counter += 1


def _base_class_data(
    entity_uuid: str,
    name: str,
    description: str,
    project_uuid: str,
    actor_uuid: str,
    timestamp: str,
    object_category: str,
    storage_type: str,
    source_uuid: Optional[str] = None,
    target_uuid: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "uuid": entity_uuid,
        "name": name,
        "description": description,
        "projectUuid": project_uuid,
        "descriptionStatus": "empty",
        "backupEntityCategory": "prod",
        "objectEntityCategory": object_category,
        "createdBy": actor_uuid,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "updatedBy": NIL_UUID,
        "objectsContainDiagrams": False,
        "diagramTemplateUuid": None,
        "storageType": storage_type,
        "storageStructureAppliedAt": None,
        "relatedSourceUuid": source_uuid,
        "relatedDestinationUuid": target_uuid,
        "sourceObjectsLimit": 0,
        "destinationObjectsLimit": 0,
        "strictRelation": False,
        "objectsLimitInModel": False,
        "replaceOldRelationsType": "undefined",
        "restrictionLevelType": "undefined",
        "showWarning": False,
    }


def _class_wrapper(
    data: Dict[str, Any], project_uuid: str, parent_relation_uuid: Optional[str]
) -> Dict[str, Any]:
    return {
        "UUID": data["uuid"],
        "ProjectUUID": project_uuid,
        "Name": data["name"],
        "ParentRelationUUID": parent_relation_uuid,
        "Group": "class",
        "Type": "class",
        "Data": data,
    }


def _tree_record(
    tree_uuid: str,
    reference_uuid: str,
    project_uuid: str,
    parent_tree_uuid: Optional[str],
    timestamp: str,
    num: Optional[int] = None,
    childs: Optional[int] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "uuid": tree_uuid,
        "type": "class",
        "parentUuid": parent_tree_uuid,
        "projectUuid": project_uuid,
        "referenceUuid": reference_uuid,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }
    if num is not None:
        data["num"] = num
    if childs is not None:
        data["childs"] = childs
    return {
        "UUID": tree_uuid,
        "ProjectUUID": NIL_UUID,
        "ParentRelationUUID": None,
        "Group": "class",
        "Type": "tree",
        "Data": data,
    }


def _l10n_record(l10n_uuid: str, entity_uuid: str, name: str) -> Dict[str, Any]:
    return {
        "UUID": l10n_uuid,
        "ProjectUUID": NIL_UUID,
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


def _append_grouped_records(
    original: List[Dict[str, Any]], additions: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    last_index: Dict[str, int] = {}
    for index, record in enumerate(original):
        record_type = record.get("Type")
        if isinstance(record_type, str):
            last_index[record_type] = index
    result: List[Dict[str, Any]] = []
    inserted: set = set()
    for index, record in enumerate(original):
        result.append(record)
        record_type = record.get("Type")
        if isinstance(record_type, str) and last_index.get(record_type) == index:
            result.extend(additions.get(record_type, []))
            inserted.add(record_type)
    for record_type in ("class", "tree", "classL10n"):
        if record_type not in inserted:
            result.extend(additions.get(record_type, []))
    return result


def build_backup(
    source_records: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    edited: Dict[str, Any],
    bridge: Dict[str, Any],
    persisted_plan: Dict[str, Any],
    accepted_paths: Sequence[str],
    timestamp: Optional[str] = None,
    actor_uuid: Optional[str] = None,
    artifact_hashes: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    recomputed_plan = create_diff_plan(source_records, baseline, edited, bridge, artifact_hashes)
    review = verify_reviewed_plan(persisted_plan, recomputed_plan, accepted_paths)
    if not review["ready"]:
        reasons: List[str] = []
        if not review["planBinding"]["matches"]:
            reasons.append("reviewed_plan_mismatch")
        if review["deferredAcceptance"]["missing"]:
            reasons.append("missing_deferred_acceptance")
        if review["deferredAcceptance"]["unknown"]:
            reasons.append("unknown_deferred_acceptance")
        if review["deferredAcceptance"]["duplicates"]:
            reasons.append("duplicate_deferred_acceptance")
        reasons.extend(review["planApplyBlockedReasons"])
        review["status"] = "blocked"
        review["blockedReasons"] = reasons
        raise BuildBlocked("build is blocked: %s" % ", ".join(reasons), review)

    output = copy.deepcopy(source_records)
    structure = _index_structure(output)
    project_uuid = _data(structure["project"]).get("uuid")
    if not isinstance(project_uuid, str) or not project_uuid:
        raise RoundTripError("project Data.uuid is required")
    timestamp = timestamp or edited.get("updatedAt") or DEFAULT_TIME
    if not isinstance(timestamp, str) or not timestamp:
        raise RoundTripError("build timestamp must be a non-empty string")
    if actor_uuid is None:
        actor_uuid = NIL_UUID
        for record in structure["ordinary"]:
            candidate = _data(record).get("createdBy")
            if isinstance(candidate, str) and candidate:
                actor_uuid = candidate
                break
    if not isinstance(actor_uuid, str) or not actor_uuid:
        raise RoundTripError("actor UUID must be a non-empty string")
    try:
        uuid.UUID(actor_uuid)
    except ValueError as exc:
        raise RoundTripError("actor UUID is invalid") from exc

    existing_ids = {value for value in (_record_uuid(record) for record in output) if value}
    namespace = _uuid_namespace(project_uuid)
    class_records: Dict[str, Dict[str, Any]] = {
        _record_uuid(record): record
        for record in structure["ordinary"]
        if _record_uuid(record)
    }
    tree_records: Dict[str, Dict[str, Any]] = dict(structure["trees"])
    class_resolution: Dict[str, str] = {
        entry["diagramId"]: entry["ksEntityUuid"]
        for entry in _mapped_entries(bridge, "classes")
        if isinstance(entry.get("diagramId"), str) and isinstance(entry.get("ksEntityUuid"), str)
    }
    additions: Dict[str, List[Dict[str, Any]]] = {"class": [], "tree": [], "classL10n": []}
    generated_classes: List[Dict[str, str]] = []
    generated_relationships: List[Dict[str, str]] = []
    max_num = max(
        [
            _data(record).get("num", 0)
            for record in output
            if record.get("Type") == "tree" and isinstance(_data(record).get("num", 0), int)
        ]
        or [0]
    )

    operations = recomputed_plan["operations"]
    for operation in operations:
        if operation["intent"] != "create_class":
            continue
        diagram_id = operation["diagramId"]
        entity_uuid = _generated_uuid(namespace, "class", diagram_id, existing_ids)
        tree_uuid = _generated_uuid(namespace, "class-tree", diagram_id, existing_ids)
        l10n_uuid = _generated_uuid(namespace, "class-l10n:ru_RU", diagram_id, existing_ids)
        data = _base_class_data(
            entity_uuid,
            operation["name"],
            operation.get("description", ""),
            project_uuid,
            actor_uuid,
            timestamp,
            "prod",
            "regular",
        )
        data["relations"] = []
        data["indicators"] = None
        data["dimensions"] = None
        data["usages"] = None
        wrapper = _class_wrapper(data, project_uuid, None)
        max_num += 1
        tree = _tree_record(tree_uuid, entity_uuid, project_uuid, None, timestamp, max_num, 0)
        additions["class"].append(wrapper)
        additions["tree"].append(tree)
        additions["classL10n"].append(_l10n_record(l10n_uuid, entity_uuid, operation["name"]))
        class_records[entity_uuid] = wrapper
        tree_records[entity_uuid] = tree
        class_resolution[diagram_id] = entity_uuid
        generated_classes.append({"diagramId": diagram_id, "ksEntityUuid": entity_uuid, "ksTreeNodeUuid": tree_uuid, "ksL10nUuid": l10n_uuid})

    for operation in operations:
        if operation["intent"] != "create_relationship":
            continue
        diagram_id = operation["diagramId"]
        source_uuid = class_resolution.get(operation.get("sourceClassId"))
        target_uuid = class_resolution.get(operation.get("targetClassId"))
        if source_uuid is None or target_uuid is None:
            raise RoundTripError("cannot resolve new relationship endpoints: %s" % diagram_id)
        if source_uuid == target_uuid:
            raise RoundTripError("self relationships are unsupported in structural-v0.1")
        relation_uuid = _generated_uuid(namespace, "relationship", diagram_id, existing_ids)
        source_helper_uuid = _generated_uuid(namespace, "source-helper", diagram_id, existing_ids)
        target_helper_uuid = _generated_uuid(namespace, "target-helper", diagram_id, existing_ids)
        tree_uuid = _generated_uuid(namespace, "relationship-tree", diagram_id, existing_ids)
        l10n_uuid = _generated_uuid(namespace, "relationship-l10n:ru_RU", diagram_id, existing_ids)
        name = operation["name"]
        source_name = _data(class_records[source_uuid]).get("name", source_uuid)
        target_name = _data(class_records[target_uuid]).get("name", target_uuid)
        source_helper_name = "%s%s_to_%s" % (HELPER_PREFIX, source_name, name)
        target_helper_name = "%s%s_to_%s" % (HELPER_PREFIX, name, target_name)
        relation_data = _base_class_data(
            relation_uuid, name, operation.get("description", ""), project_uuid, actor_uuid, timestamp,
            "prod", "regular", source_uuid, target_uuid,
        )
        source_helper_data = _base_class_data(
            source_helper_uuid, source_helper_name, "", project_uuid, actor_uuid, timestamp,
            "undefined", "regular", source_uuid, relation_uuid,
        )
        target_helper_data = _base_class_data(
            target_helper_uuid, target_helper_name, "", project_uuid, actor_uuid, timestamp,
            "undefined", "regular", relation_uuid, target_uuid,
        )
        for data in (source_helper_data, target_helper_data):
            data["indicators"] = None
            data["dimensions"] = None
            data["usages"] = None
        relation_data["indicators"] = None
        relation_data["dimensions"] = None
        relation_data["usages"] = None
        relation_data["relations"] = [copy.deepcopy(source_helper_data), copy.deepcopy(target_helper_data)]
        relation_wrapper = _class_wrapper(relation_data, project_uuid, target_uuid)
        source_helper_wrapper = _class_wrapper(source_helper_data, project_uuid, source_uuid)
        target_helper_wrapper = _class_wrapper(target_helper_data, project_uuid, target_uuid)
        additions["class"].extend([source_helper_wrapper, relation_wrapper, target_helper_wrapper])
        source_data = _data(class_records[source_uuid])
        target_data = _data(class_records[target_uuid])
        if not isinstance(source_data.get("relations"), list):
            source_data["relations"] = []
        if not isinstance(target_data.get("relations"), list):
            target_data["relations"] = []
        source_data["relations"].extend([copy.deepcopy(source_helper_data), without_relations(relation_data)])
        target_data["relations"].extend([without_relations(relation_data), copy.deepcopy(target_helper_data)])
        source_tree = tree_records.get(source_uuid)
        target_tree = tree_records.get(target_uuid)
        if source_tree is None or target_tree is None:
            raise RoundTripError("endpoint tree record is missing for relationship %s" % diagram_id)
        source_tree_data = _data(source_tree)
        old_childs = source_tree_data.get("childs", 0)
        source_tree_data["childs"] = (old_childs if isinstance(old_childs, int) else 0) + 2
        source_tree_data["updatedAt"] = timestamp
        additions["tree"].append(
            _tree_record(tree_uuid, relation_uuid, project_uuid, _record_uuid(source_tree), timestamp)
        )
        additions["classL10n"].append(_l10n_record(l10n_uuid, relation_uuid, name))
        generated_relationships.append({
            "diagramId": diagram_id,
            "ksEntityUuid": relation_uuid,
            "sourceHelperUuid": source_helper_uuid,
            "targetHelperUuid": target_helper_uuid,
            "ksTreeNodeUuid": tree_uuid,
            "ksL10nUuid": l10n_uuid,
            "sourceKsEntityUuid": source_uuid,
            "targetKsEntityUuid": target_uuid,
        })

    output = _append_grouped_records(output, additions)
    validation = validate_ks_records(output)
    _require_valid(validation, "built backup")
    expected_delta = len(generated_classes) * 3 + len(generated_relationships) * 5
    actual_delta = len(output) - len(source_records)
    if actual_delta != expected_delta:
        raise RoundTripError("record delta invariant failed: expected %d, got %d" % (expected_delta, actual_delta))
    source_by_uuid = {_record_uuid(record): record for record in source_records if _record_uuid(record)}
    output_by_uuid = {_record_uuid(record): record for record in output if _record_uuid(record)}
    mutated_existing = [
        {
            "uuid": entity_uuid,
            "type": source_by_uuid[entity_uuid].get("Type"),
            "beforeSemanticSha256": semantic_sha256(source_by_uuid[entity_uuid]),
            "afterSemanticSha256": semantic_sha256(output_by_uuid[entity_uuid]),
        }
        for entity_uuid in sorted(source_by_uuid)
        if entity_uuid in output_by_uuid
        and canonical_bytes(source_by_uuid[entity_uuid]) != canonical_bytes(output_by_uuid[entity_uuid])
    ]
    review.update({
        "format": "teamvalue.ks-diagram-build-report",
        "formatVersion": FORMAT_VERSION,
        "status": "built",
        "blockedReasons": [],
        "sourceRecordCount": len(source_records),
        "outputRecordCount": len(output),
        "addedTopLevelRecords": actual_delta,
        "expectedTopLevelRecords": expected_delta,
        "sourceSemanticSha256": semantic_sha256(source_records),
        "outputSemanticSha256": semantic_sha256(output),
        "generatedClasses": generated_classes,
        "generatedRelationships": generated_relationships,
        "mutatedExistingRecords": mutated_existing,
        "valid": validation["valid"],
        "validation": validation,
    })
    return output, review


def pack_records(records: List[Dict[str, Any]], output_path: str) -> Dict[str, Any]:
    validation = validate_ks_records(records)
    _require_valid(validation, "pack input")
    zstd = shutil.which("zstd")
    if not zstd:
        raise RoundTripError("local zstd executable was not found")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="ks-diagram-pack-", dir=str(destination.parent))
    try:
        clean_path = os.path.join(work_dir, "clean.json")
        compressed_path = os.path.join(work_dir, "compressed.zst")
        with open(clean_path, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, separators=(",", ":"))
        process = subprocess.run(
            [zstd, "-q", "-f", clean_path, "-o", compressed_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            raise RoundTripError("zstd failed: %s" % process.stderr.decode("utf-8", "replace").strip())
        metadata = ("{\"projectUuid\":\"%s\",\"isFileCompressed\":true}" % NIL_UUID).encode("utf-8")
        encoded = base64.b64encode(metadata)
        marker = ("%%backup_metadata_size=%d%%" % len(encoded)).encode("ascii")
        if len(encoded) != 104:
            raise RoundTripError("backup metadata invariant failed: expected base64 length 104")
        temp_output = os.path.join(work_dir, "backup.tmp")
        with open(compressed_path, "rb") as source, open(temp_output, "wb") as target:
            shutil.copyfileobj(source, target)
            target.write(marker)
            target.write(encoded)
        with open(temp_output, "rb") as handle:
            packed_payload = handle.read()
        expected_tail = marker + encoded
        if not packed_payload.endswith(expected_tail):
            raise RoundTripError("packed backup read-back did not find the exact metadata tail")
        readback = subprocess.run(
            [zstd, "-q", "-d", "-c", compressed_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if readback.returncode != 0:
            raise RoundTripError("zstd read-back failed: %s" % readback.stderr.decode("utf-8", "replace").strip())
        try:
            decoded = json.loads(readback.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoundTripError("packed backup read-back JSON failed: %s" % exc) from exc
        decoded_records = records_from_document(decoded)
        if canonical_bytes(decoded_records) != canonical_bytes(records):
            raise RoundTripError("packed backup read-back differs from clean input")
        readback_validation = validate_ks_records(decoded_records)
        _require_valid(readback_validation, "packed backup read-back")
        packed_sha = hashlib.sha256(packed_payload).hexdigest()
        os.replace(temp_output, destination)
        return {
            "format": "teamvalue.ks-diagram-pack-report",
            "formatVersion": FORMAT_VERSION,
            "status": "packed",
            "recordCount": len(records),
            "semanticSha256": semantic_sha256(records),
            "packedSha256": packed_sha,
            "packedBytes": len(packed_payload),
            "zstdFrameBytes": len(packed_payload) - len(expected_tail),
            "metadataTailBytes": len(marker) + len(encoded),
            "metadataBase64Bytes": len(encoded),
            "validation": validation,
            "readBack": {
                "tailMatches": True,
                "semanticMatchesInput": True,
                "recordCount": len(decoded_records),
                "validation": readback_validation,
            },
            "liveRestoreBlocked": True,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# Public compatibility names used by the first offline pilot.  Mutating legacy
# calls still go through the reviewed-plan gate; the old blanket acceptance is
# intentionally not reintroduced.
canonical_sha256 = semantic_sha256
validate_records = validate_ks_records


def normalize_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    return from_ks(records)[2]


def diagram_from_normalized(normalized: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(normalized, dict) or normalized.get("format") != NORMALIZED_FORMAT:
        raise RoundTripError("unknown normalized structure format")
    project = normalized.get("project", {})
    classes: List[Dict[str, Any]] = []
    class_ids: Dict[str, str] = {}
    for index, item in enumerate(normalized.get("classes", [])):
        entity_uuid = item.get("entityUuid")
        if not isinstance(entity_uuid, str):
            raise RoundTripError("normalized class entityUuid is required")
        diagram_id = "ks-class:" + entity_uuid
        class_ids[entity_uuid] = diagram_id
        classes.append({
            "id": diagram_id,
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "stereotype": "KS class",
            "attributes": [],
            "indicators": [],
            "position": {"x": 80 + (index % 4) * 340, "y": 80 + (index // 4) * 260},
            "size": {"width": 260, "height": 180},
            "notes": "Existing KS entity; updates are deferred in pilot.",
        })
    relationships: List[Dict[str, Any]] = []
    for item in normalized.get("relationships", []):
        entity_uuid = item.get("entityUuid")
        source_uuid = item.get("sourceEntityUuid")
        target_uuid = item.get("destinationEntityUuid")
        if not all(isinstance(value, str) for value in (entity_uuid, source_uuid, target_uuid)):
            raise RoundTripError("normalized relationship ids are required")
        relation_warnings = item.get("sourceWarnings", [])
        if not isinstance(relation_warnings, list):
            relation_warnings = []
        relationship_notes = "Existing KS relation; type and cardinality are visual-only in pilot."
        if relation_warnings:
            relationship_notes += " Source warning: " + " ".join(
                warning.get("message", "")
                for warning in relation_warnings
                if isinstance(warning, dict) and warning.get("message")
            )
        relationships.append({
            "id": "ks-relation:" + entity_uuid,
            "sourceClassId": class_ids[source_uuid],
            "targetClassId": class_ids[target_uuid],
            "type": "association",
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "direction": "source_to_target",
            "cardinality": "* → *",
            "indicators": [],
            "notes": relationship_notes,
        })
    project_uuid = project.get("entityUuid")
    if not isinstance(project_uuid, str):
        raise RoundTripError("normalized project entityUuid is required")
    return {
        "id": "ks-project:" + project_uuid,
        "name": "%s — Diagram" % project.get("name", "KS project"),
        "description": project.get("description", ""),
        "projectContext": "Imported from an offline KS structural snapshot",
        "version": "0.1",
        "schemaVersion": DIAGRAM_SCHEMA,
        "createdAt": project.get("createdAt") or DEFAULT_TIME,
        "updatedAt": project.get("updatedAt") or project.get("createdAt") or DEFAULT_TIME,
        "classes": classes,
        "frames": [],
        "relationships": relationships,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "sourceWarnings": normalized.get("sourceWarnings", []),
    }


def bridge_from_normalized(
    normalized: Dict[str, Any], diagram: Dict[str, Any], source_sha256: Optional[str] = None
) -> Dict[str, Any]:
    source = normalized.get("source", {})
    project = normalized.get("project", {})
    source_hash = source_sha256 or source.get("semanticSha256")
    if not isinstance(source_hash, str):
        raise RoundTripError("normalized source semantic hash is required")
    return {
        "format": BRIDGE_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "status": "offline_unbound",
        "profile": PROFILE,
        "mappingProfile": PROFILE,
        "mode": MODE,
        "diagram": {"modelId": diagram.get("id"), "schemaVersion": DIAGRAM_SCHEMA, "baselineSemanticSha256": semantic_sha256(diagram)},
        "source": {"kind": "local_backup", "backupProjectUuid": project.get("entityUuid"), "backupSha256": source_hash, "projectUuid": project.get("entityUuid"), "semanticSha256": source_hash, "normalizedSemanticSha256": semantic_sha256(normalized)},
        "target": {"mode": "restore_to_new_project", "stand": None, "projectUuid": None, "projectName": None},
        "entityMap": {
            "classes": [{"diagramId": "ks-class:" + item["entityUuid"], "ksEntityUuid": item["entityUuid"], "ksTreeNodeUuid": item.get("treeNodeUuid"), "baselineUpdatedAt": item.get("updatedAt")} for item in normalized.get("classes", [])],
            "relationships": [{"diagramId": "ks-relation:" + item["entityUuid"], "ksEntityUuid": item["entityUuid"], "ksTreeNodeUuid": item.get("treeNodeUuid"), "sourceKsEntityUuid": item.get("sourceEntityUuid"), "targetKsEntityUuid": item.get("destinationEntityUuid"), "sourceHelperUuid": item.get("sourceHelperUuid"), "targetHelperUuid": item.get("targetHelperUuid"), "helperOrientation": item.get("helperOrientation", "canonical"), "sourceWarnings": item.get("sourceWarnings", []), "baselineUpdatedAt": item.get("updatedAt")} for item in normalized.get("relationships", [])],
        },
        "sourceWarnings": normalized.get("sourceWarnings", []),
        "writePolicy": {"allowedIntents": ["create_class", "create_relationship"], "localOnlyFields": ["position", "size", "frames", "viewport", "updatedAt"], "deferredIntents": ["update_existing_class", "update_existing_relationship", "delete_existing_class", "delete_existing_relationship", "indicator_change", "formula_change"], "requiresBoundDisposableTarget": False, "stopOnFirstError": True, "readBackRequired": True, "supported": ["create_class", "create_relationship"], "deferred": ["attributes", "indicators", "objectCount", "relationship.type", "relationship.direction", "relationship.cardinality", "relationship.notes"], "forbidden": ["deletions", "relationship_endpoint_changes"]},
    }


def plan_changes(
    baseline: Dict[str, Any],
    edited: Dict[str, Any],
    bridge: Dict[str, Any],
    source_records: Optional[List[Dict[str, Any]]] = None,
    artifact_hashes: Optional[Dict[str, str]] = None,
    **_: Any,
) -> Dict[str, Any]:
    if source_records is None:
        raise RoundTripError("plan_changes now requires source_records for reviewed-plan binding")
    return create_diff_plan(source_records, baseline, edited, bridge, artifact_hashes)


def build_records(
    source_records: List[Dict[str, Any]],
    source_sha256: str,
    baseline: Dict[str, Any],
    edited: Dict[str, Any],
    bridge: Dict[str, Any],
    *,
    reviewed_plan: Optional[Dict[str, Any]] = None,
    accepted_deferred_paths: Sequence[str] = (),
    timestamp: Optional[str] = None,
    actor_uuid: Optional[str] = None,
    artifact_hashes: Optional[Dict[str, str]] = None,
    **legacy: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if legacy.get("accept_deferred") is not None:
        raise RoundTripError("blanket accept_deferred is removed; pass reviewed_plan and exact accepted_deferred_paths")
    if semantic_sha256(source_records) != source_sha256:
        raise RoundTripError("source semantic SHA-256 mismatch")
    if reviewed_plan is None:
        raise RoundTripError("reviewed_plan is required")
    return build_backup(source_records, baseline, edited, bridge, reviewed_plan, accepted_deferred_paths, timestamp, actor_uuid, artifact_hashes)


def pack_backup(input_path: Path, output_path: Path) -> Dict[str, Any]:
    if input_path.resolve() == output_path.resolve():
        raise RoundTripError("refusing to overwrite pack input")
    report = pack_records(records_from_document(load_json(str(input_path))), str(output_path))
    report["cleanInputByteSha256"] = sha256_file(str(input_path))
    return report


def ensure_distinct_paths(inputs: Iterable[Path], outputs: Iterable[Path]) -> None:
    input_paths = {path.resolve() for path in inputs}
    output_paths = [path.resolve() for path in outputs]
    if len(set(output_paths)) != len(output_paths) or input_paths.intersection(output_paths):
        raise RoundTripError("refusing to overwrite or collide with an input/output artifact")


def _check_profile_mode(args: argparse.Namespace) -> None:
    if args.profile != PROFILE:
        raise RoundTripError("unsupported profile: %s" % args.profile)
    if args.mode != MODE:
        raise RoundTripError("unsupported mode: %s" % args.mode)


def _manifest_output_paths(args: argparse.Namespace) -> List[Path]:
    value = getattr(args, "manifest", None)
    return [Path(value)] if value else []


def _update_run_manifest(
    manifest: Optional[str],
    command: str,
    artifacts: Iterable[Tuple[str, Path]],
    state: Optional[Dict[str, Any]] = None,
) -> None:
    if manifest:
        rio.update_manifest(
            Path(manifest), command=command, artifacts=artifacts, state=state
        )


def _manifest_artifact_path(
    manifest_path: Path,
    manifest: Dict[str, Any],
    role: str,
    errors: List[str],
) -> Optional[Path]:
    artifacts = manifest.get("artifacts")
    entry = artifacts.get(role) if isinstance(artifacts, dict) else None
    if not isinstance(entry, dict):
        errors.append("required manifest artifact is missing: %s" % role)
        return None
    try:
        return rio.resolve_manifest_artifact(manifest_path, entry)
    except rio.BackupIOError as exc:
        errors.append("manifest artifact %s is invalid: %s" % (role, exc))
        return None


def _load_bundle_json(path: Optional[Path], role: str, errors: List[str]) -> Any:
    if path is None:
        return None
    try:
        return load_json(str(path))
    except RoundTripError as exc:
        errors.append("cannot load %s: %s" % (role, exc))
        return None


def _expected_mutated_existing(
    source_records: List[Dict[str, Any]], output_records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    source_by_uuid = {
        _record_uuid(record): record
        for record in source_records
        if _record_uuid(record)
    }
    output_by_uuid = {
        _record_uuid(record): record
        for record in output_records
        if _record_uuid(record)
    }
    return [
        {
            "uuid": entity_uuid,
            "type": source_by_uuid[entity_uuid].get("Type"),
            "beforeSemanticSha256": semantic_sha256(source_by_uuid[entity_uuid]),
            "afterSemanticSha256": semantic_sha256(output_by_uuid[entity_uuid]),
        }
        for entity_uuid in sorted(source_by_uuid)
        if entity_uuid in output_by_uuid
        and canonical_bytes(source_by_uuid[entity_uuid])
        != canonical_bytes(output_by_uuid[entity_uuid])
    ]


def validate_bundle_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Validate the immutable artifact graph at baseline or final stage."""

    errors: List[str] = []
    checks: Dict[str, Any] = {}
    try:
        manifest, manifest_errors = rio.verify_manifest_hashes(manifest_path)
    except rio.BackupIOError as exc:
        return {
            "format": BUNDLE_VALIDATION_FORMAT,
            "formatVersion": FORMAT_VERSION,
            "profile": PROFILE,
            "stage": "unknown",
            "valid": False,
            "errors": [str(exc)],
            "checks": {},
            "liveRestoreBlocked": True,
        }
    errors.extend(manifest_errors)
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    final_roles = {
        "editedDiagram",
        "changePlan",
        "cleanOutput",
        "buildReport",
        "structuralValidation",
        "packedOutput",
        "packReport",
    }
    stage = "final" if final_roles.intersection(artifacts) else "baseline"

    baseline_roles = ("structuralSource", "normalizedBaseline", "baselineDiagram", "bridge")
    paths = {
        role: _manifest_artifact_path(manifest_path, manifest, role, errors)
        for role in baseline_roles
    }
    source_document = _load_bundle_json(paths["structuralSource"], "structuralSource", errors)
    normalized = _load_bundle_json(paths["normalizedBaseline"], "normalizedBaseline", errors)
    baseline = _load_bundle_json(paths["baselineDiagram"], "baselineDiagram", errors)
    bridge = _load_bundle_json(paths["bridge"], "bridge", errors)
    source_records: Optional[List[Dict[str, Any]]] = None
    if source_document is not None:
        try:
            source_records = records_from_document(source_document)
        except RoundTripError as exc:
            errors.append("structuralSource is invalid: %s" % exc)

    run_state = manifest.get("state") if isinstance(manifest.get("state"), dict) else {}
    if run_state.get("sourceAcquisition") == "packed-stream":
        source_backup_path = _manifest_artifact_path(
            manifest_path, manifest, "sourceBackup", errors
        )
        source_metadata_path = _manifest_artifact_path(
            manifest_path, manifest, "sourceMetadata", errors
        )
        source_metadata = _load_bundle_json(
            source_metadata_path, "sourceMetadata", errors
        )
        packed_checks: Dict[str, Any] = {
            "sourceBackupPresent": source_backup_path is not None,
            "sourceMetadataPresent": isinstance(source_metadata, dict),
        }
        if (
            source_backup_path is not None
            and isinstance(source_metadata, dict)
            and paths["structuralSource"] is not None
            and isinstance(source_document, dict)
            and source_records is not None
        ):
            try:
                packed_parts = rio.split_backup_tail(source_backup_path)
                backup_sha256 = sha256_file(str(source_backup_path))
                structural_sha256 = sha256_file(str(paths["structuralSource"]))
                source_link = (
                    source_document.get("source")
                    if isinstance(source_document.get("source"), dict)
                    else {}
                )
                metadata_hashes = (
                    source_metadata.get("hashes")
                    if isinstance(source_metadata.get("hashes"), dict)
                    else {}
                )
                packed_checks.update(
                    {
                        "metadataTailValid": True,
                        "backupHashMatches": metadata_hashes.get("backupSha256")
                        == backup_sha256,
                        "structuralHashMatches": metadata_hashes.get("outputSha256")
                        == structural_sha256,
                        "sourceLinkMatches": source_link.get("kind")
                        == "packed-backup-stream"
                        and source_link.get("sha256") == backup_sha256,
                        "recordCountsMatch": source_metadata.get("recordCount")
                        == source_link.get("recordCount")
                        and source_metadata.get("selectedRecordCount")
                        == len(source_records)
                        == source_document.get("selectedRecordCount"),
                        "byteCountsMatch": source_metadata.get("backupBytes")
                        == source_backup_path.stat().st_size
                        and source_metadata.get("compressedBytes")
                        == packed_parts.compressed_bytes
                        and source_metadata.get("metadataTailBytes")
                        == packed_parts.metadata_tail_bytes,
                        "manifestStateMatches": run_state.get(
                            "sourceBackupSha256"
                        )
                        == backup_sha256
                        and run_state.get("sourceRecordCount")
                        == source_metadata.get("recordCount")
                        and run_state.get("sliceProfile") == PROFILE,
                        "reportPolicyMatches": source_metadata.get("valid") is True
                        and source_metadata.get("mode") == "packed-stream"
                        and source_metadata.get("liveRestoreBlocked") is True,
                    }
                )
            except (rio.BackupIOError, RoundTripError, OSError) as exc:
                packed_checks["metadataTailValid"] = False
                errors.append("packed-stream source validation failed: %s" % exc)
        checks["packedStreamSource"] = packed_checks
        for key, value in packed_checks.items():
            if (
                key.endswith("Match")
                or key.endswith("Matches")
                or key.endswith("Present")
                or key == "metadataTailValid"
            ):
                if value is not True:
                    errors.append("packed-stream source check failed: %s" % key)

    if source_records is not None:
        source_validation = validate_ks_records(source_records)
        checks["sourceValidation"] = source_validation
        if not source_validation.get("valid"):
            errors.append("structuralSource graph validation failed")
        try:
            expected_diagram, expected_bridge, expected_normalized = from_ks(source_records)
            if paths["structuralSource"] is not None:
                expected_bridge["source"]["backupSha256"] = sha256_file(
                    str(paths["structuralSource"])
                )
            checks["normalizedMatchesSource"] = (
                normalized is not None
                and canonical_bytes(normalized) == canonical_bytes(expected_normalized)
            )
            checks["baselineDiagramMatchesSource"] = (
                baseline is not None
                and canonical_bytes(baseline) == canonical_bytes(expected_diagram)
            )
            checks["bridgeMatchesSource"] = (
                bridge is not None
                and canonical_bytes(bridge) == canonical_bytes(expected_bridge)
            )
            for key in (
                "normalizedMatchesSource",
                "baselineDiagramMatchesSource",
                "bridgeMatchesSource",
            ):
                if not checks[key]:
                    errors.append(key + " is false")
        except RoundTripError as exc:
            errors.append("cannot regenerate baseline artifacts: %s" % exc)

    if isinstance(baseline, dict):
        diagram_validation = validate_diagram(baseline)
        checks["baselineDiagramValidation"] = diagram_validation
        if not diagram_validation.get("valid"):
            errors.append("baseline Diagramm validation failed")
    if isinstance(bridge, dict):
        bridge_validation = validate_bridge(bridge)
        checks["bridgeValidation"] = bridge_validation
        if not bridge_validation.get("valid"):
            errors.append("bridge validation failed")

    if (
        source_records is not None
        and isinstance(baseline, dict)
        and isinstance(bridge, dict)
        and paths["structuralSource"] is not None
        and paths["baselineDiagram"] is not None
        and paths["bridge"] is not None
    ):
        preview_hashes = {
            "sourceSha256": sha256_file(str(paths["structuralSource"])),
            "baselineSha256": sha256_file(str(paths["baselineDiagram"])),
            "editedSha256": sha256_file(str(paths["baselineDiagram"])),
            "bridgeSha256": sha256_file(str(paths["bridge"])),
        }
        preview = create_diff_plan(
            source_records, baseline, baseline, bridge, preview_hashes
        )
        checks["baselineMappingPlan"] = {
            "hardErrors": preview.get("hardErrors", []),
            "offlineBuildBlocked": preview.get("offlineBuildBlocked"),
            "liveRestoreBlocked": preview.get("liveRestoreBlocked"),
        }
        if preview.get("hardErrors") or preview.get("offlineBuildBlocked"):
            errors.append("baseline mapping preview is blocked")
        if preview.get("liveRestoreBlocked") is not True:
            errors.append("baseline mapping preview cleared the live restore block")

    if stage == "final":
        required_final = (
            "baselineBundleValidation",
            "editedDiagram",
            "changePlan",
            "cleanOutput",
            "buildReport",
            "structuralValidation",
            "packedOutput",
            "packReport",
        )
        final_paths = {
            role: _manifest_artifact_path(manifest_path, manifest, role, errors)
            for role in required_final
        }
        edited = _load_bundle_json(final_paths["editedDiagram"], "editedDiagram", errors)
        plan = _load_bundle_json(final_paths["changePlan"], "changePlan", errors)
        clean_document = _load_bundle_json(final_paths["cleanOutput"], "cleanOutput", errors)
        build_report = _load_bundle_json(final_paths["buildReport"], "buildReport", errors)
        structural_report = _load_bundle_json(
            final_paths["structuralValidation"], "structuralValidation", errors
        )
        pack_report = _load_bundle_json(final_paths["packReport"], "packReport", errors)
        output_records: Optional[List[Dict[str, Any]]] = None
        if clean_document is not None:
            try:
                output_records = records_from_document(clean_document)
            except RoundTripError as exc:
                errors.append("cleanOutput is invalid: %s" % exc)

        if (
            source_records is not None
            and isinstance(baseline, dict)
            and isinstance(edited, dict)
            and isinstance(bridge, dict)
            and isinstance(plan, dict)
            and all(paths[role] is not None for role in ("structuralSource", "baselineDiagram", "bridge"))
            and final_paths["editedDiagram"] is not None
        ):
            final_hashes = {
                "sourceSha256": sha256_file(str(paths["structuralSource"])),
                "baselineSha256": sha256_file(str(paths["baselineDiagram"])),
                "editedSha256": sha256_file(str(final_paths["editedDiagram"])),
                "bridgeSha256": sha256_file(str(paths["bridge"])),
            }
            recomputed_plan = create_diff_plan(
                source_records, baseline, edited, bridge, final_hashes
            )
            checks["reviewedPlanMatches"] = canonical_bytes(plan) == canonical_bytes(
                recomputed_plan
            )
            if not checks["reviewedPlanMatches"]:
                errors.append("changePlan does not match the bound inputs")
            if plan.get("liveRestoreBlocked") is not True:
                errors.append("changePlan cleared the live restore block")

        if output_records is not None:
            output_validation = validate_ks_records(output_records)
            checks["cleanOutputValidation"] = output_validation
            if not output_validation.get("valid"):
                errors.append("cleanOutput graph validation failed")
            if structural_report is None or canonical_bytes(structural_report) != canonical_bytes(output_validation):
                errors.append("structuralValidation report does not match cleanOutput")
            if isinstance(build_report, dict):
                expected_delta = len(output_records) - len(source_records or [])
                if build_report.get("addedTopLevelRecords") != expected_delta:
                    errors.append("buildReport addedTopLevelRecords mismatch")
                expected_mutations = _expected_mutated_existing(
                    source_records or [], output_records
                )
                if canonical_bytes(build_report.get("mutatedExistingRecords")) != canonical_bytes(expected_mutations):
                    errors.append("buildReport mutatedExistingRecords mismatch")
                if build_report.get("outputSemanticSha256") != semantic_sha256(output_records):
                    errors.append("buildReport output semantic hash mismatch")
                if final_paths["changePlan"] is not None:
                    recorded_plan_hash = build_report.get("planBinding", {}).get(
                        "persistedPlanByteSha256"
                    )
                    if recorded_plan_hash != sha256_file(str(final_paths["changePlan"])):
                        errors.append("buildReport reviewed plan byte hash mismatch")
                state = manifest.get("state") if isinstance(manifest.get("state"), dict) else {}
                accepted = build_report.get("deferredAcceptance", {}).get("accepted")
                if state.get("acceptedDeferredPaths") != accepted:
                    errors.append("manifest acceptedDeferredPaths differs from buildReport")
                if build_report.get("liveRestoreBlocked") is not True:
                    errors.append("buildReport cleared the live restore block")
            else:
                errors.append("buildReport must be an object")

        packed_path = final_paths.get("packedOutput")
        if packed_path is not None and output_records is not None:
            if not isinstance(pack_report, dict):
                errors.append("packReport must be an object")
            else:
                if pack_report.get("packedSha256") != sha256_file(str(packed_path)):
                    errors.append("packReport packed SHA-256 mismatch")
                if final_paths["cleanOutput"] is not None and pack_report.get(
                    "cleanInputByteSha256"
                ) != sha256_file(str(final_paths["cleanOutput"])):
                    errors.append("packReport clean input SHA-256 mismatch")
                if not pack_report.get("readBack", {}).get("semanticMatchesInput"):
                    errors.append("packReport read-back did not match its input")
            try:
                with tempfile.TemporaryDirectory(prefix="ks-bundle-readback-") as temp_dir:
                    unpacked = Path(temp_dir) / "readback.json"
                    readback_report = rio.unpack_backup(packed_path, unpacked)
                    readback_records = records_from_document(load_json(str(unpacked)))
                    checks["packedReadBack"] = readback_report
                    if canonical_bytes(readback_records) != canonical_bytes(output_records):
                        errors.append("packedOutput read-back differs from cleanOutput")
                    if not validate_ks_records(readback_records).get("valid"):
                        errors.append("packedOutput read-back graph validation failed")
            except (rio.BackupIOError, RoundTripError) as exc:
                errors.append("packedOutput read-back failed: %s" % exc)

    return {
        "format": BUNDLE_VALIDATION_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "profile": PROFILE,
        "stage": stage,
        "valid": not errors,
        "errors": sorted(set(errors)),
        "checks": checks,
        "artifactCount": len(artifacts),
        "liveRestoreBlocked": True,
        "requiredLiveRestorePreflight": "approved_destructive safe-restore-readback preflight",
    }


def _command_unpack(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    outputs = [Path(args.output), Path(args.metadata_output)] + _manifest_output_paths(args)
    ensure_distinct_paths([Path(args.input)], outputs)
    report = rio.unpack_backup(Path(args.input), Path(args.output))
    atomic_write_json(args.metadata_output, report)
    _update_run_manifest(
        args.manifest,
        "unpack",
        (
            ("sourceBackup", Path(args.input)),
            ("unpackedSource", Path(args.output)),
            ("sourceMetadata", Path(args.metadata_output)),
        ),
        {"sourceBackupSha256": report["hashes"]["backupSha256"]},
    )
    print(json.dumps(report, ensure_ascii=False))


def _command_slice_packed(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    input_path = Path(args.input)
    output_path = Path(args.output)
    metadata_path = Path(args.metadata_output)
    manifest_path = Path(args.manifest)
    outputs = [output_path, metadata_path, manifest_path]
    ensure_distinct_paths([input_path], outputs)
    rio.ensure_manifest_artifact_paths(
        manifest_path, (input_path, output_path, metadata_path)
    )
    report = rio.slice_packed_backup(input_path, output_path)
    atomic_write_json(args.metadata_output, report)
    _update_run_manifest(
        args.manifest,
        "slice-packed",
        (
            ("sourceBackup", input_path),
            ("sourceMetadata", metadata_path),
            ("structuralSource", output_path),
        ),
        {
            "sourceAcquisition": "packed-stream",
            "sourceBackupSha256": report["hashes"]["backupSha256"],
            "sourceRecordCount": report["recordCount"],
            "sliceProfile": PROFILE,
        },
    )
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "records": report["recordCount"],
                "selectedRecords": report["selectedRecordCount"],
                "backupSha256": report["hashes"]["backupSha256"],
                "structuralSha256": report["hashes"]["outputSha256"],
            },
            ensure_ascii=False,
        )
    )


def _command_slice_packed_read_model(args: argparse.Namespace) -> None:
    if args.profile != rio.DIAGRAM_READ_PROFILE:
        raise RoundTripError("unsupported diagram read profile: %s" % args.profile)
    input_path = Path(args.input)
    output_path = Path(args.output)
    metadata_path = Path(args.metadata_output)
    ensure_distinct_paths([input_path], [output_path, metadata_path])
    report = rio.slice_packed_diagram_read_model(input_path, output_path)
    atomic_write_json(args.metadata_output, report)
    counts = report["validation"]["counts"]
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "profile": report["profile"],
                "records": report["recordCount"],
                "selectedRecords": report["selectedRecordCount"],
                "indicators": counts["indicators"],
                "formulas": counts["formulas"],
                "formulaElements": counts["formulaElements"],
                "objectRecordsAggregated": counts.get(
                    "objectRecordsAggregated", 0
                ),
                "classStats": counts.get("classStats", 0),
                "integrationProvenance": counts["integrationProvenance"],
                "backupSha256": report["hashes"]["backupSha256"],
                "readModelSha256": report["hashes"]["outputSha256"],
                "readOnly": True,
                "restorePayload": False,
                "liveRestoreBlocked": True,
            },
            ensure_ascii=False,
        )
    )


def _command_slice(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    outputs = [Path(args.output)] + _manifest_output_paths(args)
    ensure_distinct_paths([Path(args.input)], outputs)
    report = rio.slice_structural_records(Path(args.input), Path(args.output))
    _update_run_manifest(
        args.manifest,
        "slice",
        (
            ("unpackedSource", Path(args.input)),
            ("structuralSource", Path(args.output)),
        ),
        {"sliceProfile": PROFILE},
    )
    print(json.dumps(report, ensure_ascii=False))


def _command_from_ks(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    outputs = [Path(args.diagram), Path(args.bridge), Path(args.baseline)] + _manifest_output_paths(args)
    ensure_distinct_paths([Path(args.input)], outputs)
    records = records_from_document(load_json(args.input))
    diagram, bridge, normalized = from_ks(records)
    bridge["source"]["backupSha256"] = sha256_file(args.input)
    atomic_write_json(args.diagram, diagram)
    atomic_write_json(args.bridge, bridge)
    atomic_write_json(args.baseline, normalized)
    _update_run_manifest(
        args.manifest,
        "from-ks",
        (
            ("structuralSource", Path(args.input)),
            ("baselineDiagram", Path(args.diagram)),
            ("bridge", Path(args.bridge)),
            ("normalizedBaseline", Path(args.baseline)),
        ),
        {
            "modelId": diagram["id"],
            "sourceSemanticSha256": semantic_sha256(records),
        },
    )
    print(json.dumps({"classes": len(diagram["classes"]), "relationships": len(diagram["relationships"]), "sourceSemanticSha256": semantic_sha256(records)}, ensure_ascii=False))


def _command_diff(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    outputs = [Path(args.output)] + _manifest_output_paths(args)
    ensure_distinct_paths([Path(args.source), Path(args.baseline), Path(args.edited), Path(args.bridge)], outputs)
    records = records_from_document(load_json(args.source))
    baseline = load_json(args.baseline)
    edited = load_json(args.edited)
    bridge = load_json(args.bridge)
    byte_hashes = {
        "sourceSha256": sha256_file(args.source),
        "baselineSha256": sha256_file(args.baseline),
        "editedSha256": sha256_file(args.edited),
        "bridgeSha256": sha256_file(args.bridge),
    }
    plan = create_diff_plan(records, baseline, edited, bridge, byte_hashes)
    atomic_write_json(args.output, plan)
    _update_run_manifest(
        args.manifest,
        "diff",
        (
            ("structuralSource", Path(args.source)),
            ("baselineDiagram", Path(args.baseline)),
            ("editedDiagram", Path(args.edited)),
            ("bridge", Path(args.bridge)),
            ("changePlan", Path(args.output)),
        ),
        {"changePlanByteSha256": sha256_file(args.output)},
    )
    print(json.dumps({"planSemanticSha256": semantic_sha256(plan), **plan["summary"]}, ensure_ascii=False))


def _command_build(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    if args.manifest and not args.report:
        raise RoundTripError("build --manifest requires --report")
    outputs = [Path(args.output)] + ([Path(args.report)] if args.report else []) + _manifest_output_paths(args)
    ensure_distinct_paths([Path(args.input), Path(args.baseline), Path(args.edited), Path(args.bridge), Path(args.plan)], outputs)
    records = records_from_document(load_json(args.input))
    baseline = load_json(args.baseline)
    edited = load_json(args.edited)
    bridge = load_json(args.bridge)
    persisted_plan = load_json(args.plan)
    plan_byte_sha256 = sha256_file(args.plan)
    byte_hashes = {
        "sourceSha256": sha256_file(args.input),
        "baselineSha256": sha256_file(args.baseline),
        "editedSha256": sha256_file(args.edited),
        "bridgeSha256": sha256_file(args.bridge),
    }
    try:
        output, report = build_backup(records, baseline, edited, bridge, persisted_plan, args.accept_deferred_path, args.timestamp, args.actor_uuid, byte_hashes)
    except BuildBlocked as exc:
        exc.report["planBinding"]["persistedPlanByteSha256"] = plan_byte_sha256
        if args.report:
            atomic_write_json(args.report, exc.report)
        raise
    report["planBinding"]["persistedPlanByteSha256"] = plan_byte_sha256
    atomic_write_json(args.output, output)
    if args.report:
        atomic_write_json(args.report, report)
    build_artifacts: List[Tuple[str, Path]] = [
        ("structuralSource", Path(args.input)),
        ("baselineDiagram", Path(args.baseline)),
        ("editedDiagram", Path(args.edited)),
        ("bridge", Path(args.bridge)),
        ("changePlan", Path(args.plan)),
        ("cleanOutput", Path(args.output)),
    ]
    if args.report:
        build_artifacts.append(("buildReport", Path(args.report)))
    _update_run_manifest(
        args.manifest,
        "build",
        build_artifacts,
        {
            "reviewedPlanByteSha256": plan_byte_sha256,
            "acceptedDeferredPaths": report["deferredAcceptance"]["accepted"],
        },
    )
    print(json.dumps({"records": len(output), "addedTopLevelRecords": report["addedTopLevelRecords"], "outputSemanticSha256": report["outputSemanticSha256"]}, ensure_ascii=False))


def _command_validate(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    if args.manifest and not args.output:
        raise RoundTripError("validate --manifest requires --output")
    outputs = ([Path(args.output)] if args.output else []) + _manifest_output_paths(args)
    if outputs:
        ensure_distinct_paths([Path(args.input)], outputs)
    value = load_json(args.input)
    kind = args.kind
    if kind == "auto":
        if isinstance(value, dict) and value.get("format") == rio.DIAGRAM_READ_FORMAT:
            kind = "read-model"
        elif isinstance(value, list) or (isinstance(value, dict) and isinstance(value.get("records"), list)):
            kind = "ks"
        elif isinstance(value, dict) and value.get("format") == BRIDGE_FORMAT:
            kind = "bridge"
        elif isinstance(value, dict) and value.get("format") == PLAN_FORMAT:
            kind = "plan"
        else:
            kind = "diagram"
    if kind == "ks":
        report = validate_ks_records(records_from_document(value))
    elif kind == "read-model":
        if args.manifest:
            raise RoundTripError("read-only diagram models cannot extend a structural restore manifest")
        records = diagram_read_records_from_document(value)
        report = rio.validate_diagram_read_records(
            records,
            class_stats=value.get("classStats"),
            source_type_counts=value.get("sourceCounts"),
            source_sha256=(
                value.get("source", {}).get("sha256")
                if isinstance(value.get("source"), dict)
                else None
            ),
        )
        embedded = value.get("validation")
        if embedded != report:
            report = dict(report)
            report["valid"] = False
            report["errors"] = sorted(
                set(report["errors"] + ["embedded read-model validation report does not match"])
            )
    elif kind == "diagram":
        report = validate_diagram(value)
    elif kind == "bridge":
        report = validate_bridge(value)
    elif kind == "plan":
        errors = []
        if not isinstance(value, dict) or value.get("format") != PLAN_FORMAT:
            errors.append(_issue("plan_format", "unknown reviewed plan format"))
        if isinstance(value, dict) and value.get("formatVersion") != FORMAT_VERSION:
            errors.append(_issue("plan_version", "unknown plan formatVersion"))
        if isinstance(value, dict) and value.get("profile") != PROFILE:
            errors.append(_issue("unsupported_profile", "unknown plan profile"))
        if isinstance(value, dict) and value.get("mode") != MODE:
            errors.append(_issue("unsupported_mode", "unknown plan mode"))
        report = {"kind": "plan", "valid": not errors, "errors": errors, "warnings": []}
    else:
        raise RoundTripError("unsupported validation kind: %s" % kind)
    if args.output:
        atomic_write_json(args.output, report)
    if args.manifest:
        _update_run_manifest(
            args.manifest,
            "validate",
            (
                ("cleanOutput", Path(args.input)),
                ("structuralValidation", Path(args.output)),
            ),
        )
    print(json.dumps(report, ensure_ascii=False))
    _require_valid(report, kind)


def _command_pack(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    if args.manifest and not args.report:
        raise RoundTripError("pack --manifest requires --report")
    outputs = [Path(args.output)] + ([Path(args.report)] if args.report else []) + _manifest_output_paths(args)
    ensure_distinct_paths([Path(args.input)], outputs)
    report = pack_backup(Path(args.input), Path(args.output))
    if args.report:
        atomic_write_json(args.report, report)
    pack_artifacts: List[Tuple[str, Path]] = [
        ("cleanOutput", Path(args.input)),
        ("packedOutput", Path(args.output)),
    ]
    if args.report:
        pack_artifacts.append(("packReport", Path(args.report)))
    _update_run_manifest(args.manifest, "pack", pack_artifacts)
    print(json.dumps(report, ensure_ascii=False))


def _command_validate_bundle(args: argparse.Namespace) -> None:
    _check_profile_mode(args)
    ensure_distinct_paths([Path(args.manifest)], [Path(args.report)])
    report = validate_bundle_manifest(Path(args.manifest))
    atomic_write_json(args.report, report)
    if report["valid"]:
        role = "%sBundleValidation" % report["stage"]
        _update_run_manifest(
            args.manifest,
            "validate-bundle-%s" % report["stage"],
            ((role, Path(args.report)),),
        )
    print(json.dumps(report, ensure_ascii=False))
    if not report["valid"]:
        raise RoundTripError(
            "bundle validation failed: %s" % "; ".join(report["errors"][:5])
        )


def _add_profile_mode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--mode", default=MODE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline KS/Diagramm structural round-trip")
    parser.add_argument("--version", action="version", version="%(prog)s " + TOOL_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    unpack_parser = commands.add_parser("unpack")
    _add_profile_mode(unpack_parser)
    unpack_parser.add_argument("--input", required=True)
    unpack_parser.add_argument("--output", required=True)
    unpack_parser.add_argument("--metadata-output", required=True)
    unpack_parser.add_argument("--manifest", required=True)
    unpack_parser.set_defaults(handler=_command_unpack)
    packed_slice_parser = commands.add_parser("slice-packed")
    _add_profile_mode(packed_slice_parser)
    packed_slice_parser.add_argument("--input", required=True)
    packed_slice_parser.add_argument("--output", required=True)
    packed_slice_parser.add_argument("--metadata-output", required=True)
    packed_slice_parser.add_argument("--manifest", required=True)
    packed_slice_parser.set_defaults(handler=_command_slice_packed)
    packed_read_parser = commands.add_parser("slice-packed-read-model")
    packed_read_parser.add_argument("--profile", default=rio.DIAGRAM_READ_PROFILE)
    packed_read_parser.add_argument("--input", required=True)
    packed_read_parser.add_argument("--output", required=True)
    packed_read_parser.add_argument("--metadata-output", required=True)
    packed_read_parser.set_defaults(handler=_command_slice_packed_read_model)
    slice_parser = commands.add_parser("slice")
    _add_profile_mode(slice_parser)
    slice_parser.add_argument("--input", required=True)
    slice_parser.add_argument("--output", required=True)
    slice_parser.add_argument("--manifest", required=True)
    slice_parser.set_defaults(handler=_command_slice)
    from_parser = commands.add_parser("from-ks")
    _add_profile_mode(from_parser)
    from_parser.add_argument("--input", required=True)
    from_parser.add_argument("--diagram", required=True)
    from_parser.add_argument("--bridge", required=True)
    from_parser.add_argument("--baseline", required=True)
    from_parser.add_argument("--manifest")
    from_parser.set_defaults(handler=_command_from_ks)
    diff_parser = commands.add_parser("diff")
    _add_profile_mode(diff_parser)
    diff_parser.add_argument("--source", required=True)
    diff_parser.add_argument("--baseline", required=True)
    diff_parser.add_argument("--edited", required=True)
    diff_parser.add_argument("--bridge", required=True)
    diff_parser.add_argument("--output", required=True)
    diff_parser.add_argument("--manifest")
    diff_parser.set_defaults(handler=_command_diff)
    build_parser_command = commands.add_parser("build")
    _add_profile_mode(build_parser_command)
    build_parser_command.add_argument("--input", "--source", dest="input", required=True)
    build_parser_command.add_argument("--baseline", required=True)
    build_parser_command.add_argument("--edited", required=True)
    build_parser_command.add_argument("--bridge", required=True)
    build_parser_command.add_argument("--plan", required=True)
    build_parser_command.add_argument("--output", required=True)
    build_parser_command.add_argument("--report")
    build_parser_command.add_argument("--manifest")
    build_parser_command.add_argument("--accept-deferred-path", action="append", default=[])
    build_parser_command.add_argument("--timestamp")
    build_parser_command.add_argument("--actor-uuid")
    build_parser_command.set_defaults(handler=_command_build)
    validate_parser = commands.add_parser("validate")
    _add_profile_mode(validate_parser)
    validate_parser.add_argument("--input", required=True)
    validate_parser.add_argument("--kind", choices=("auto", "ks", "read-model", "diagram", "bridge", "plan"), default="auto")
    validate_parser.add_argument("--output")
    validate_parser.add_argument("--manifest")
    validate_parser.set_defaults(handler=_command_validate)
    pack_parser = commands.add_parser("pack")
    _add_profile_mode(pack_parser)
    pack_parser.add_argument("--input", required=True)
    pack_parser.add_argument("--output", required=True)
    pack_parser.add_argument("--report")
    pack_parser.add_argument("--manifest")
    pack_parser.set_defaults(handler=_command_pack)
    bundle_parser = commands.add_parser("validate-bundle")
    _add_profile_mode(bundle_parser)
    bundle_parser.add_argument("--manifest", required=True)
    bundle_parser.add_argument("--report", required=True)
    bundle_parser.set_defaults(handler=_command_validate_bundle)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
        return 0
    except (RoundTripError, rio.BackupIOError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
