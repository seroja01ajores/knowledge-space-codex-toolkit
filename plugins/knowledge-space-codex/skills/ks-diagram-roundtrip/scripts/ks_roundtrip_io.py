#!/usr/bin/env python3
"""Streaming backup and run-manifest helpers for ks_diagram_roundtrip.py."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO


TAIL_MARKER = b"%backup_metadata_size="
MANIFEST_FORMAT = "teamvalue.ks-diagram-run-manifest"
FORMAT_VERSION = "0.1"
TOOL_VERSION = "0.3.0"
PROFILE = "structural-v0.1"
DIAGRAM_READ_PROFILE = "diagram-read-v0.2"
DIAGRAM_READ_FORMAT = "teamvalue.ks-diagram-read-model"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
STREAM_CHUNK_BYTES = 1024 * 1024
MAX_JSON_VALUE_CHARS = 64 * 1024 * 1024
ZSTD_MEMORY_LIMIT_MIB = 256
MAX_SELECTED_RECORDS = 1_000_000
MAX_SELECTED_JSON_CHARS = 512 * 1024 * 1024
MAX_SOURCE_TYPE_KEYS = 4096
MAX_OBJECT_CLASS_UUIDS = 100_000
OBJECT_COUNT_DIGEST_CANONICALIZATION = (
    "teamvalue.object-count-distribution-v1"
)
STRUCTURAL_RECORD_TYPES = [
    "project/project",
    "class/class",
    "class/classL10n",
    "class/folderL10n",
    "class/tree:type=folder|class",
]
STRUCTURAL_EXCLUSION = (
    "top-level business data, objects, dashboards, integrations, BPMS, "
    "indicator, and formula records"
)
DIAGRAM_READ_CLASS_TYPES = {
    "indicator",
    "indicatorL10n",
    "indicatorUnitL10n",
    "indicatorDimension",
    "formula",
    "formulaElement",
}
DIAGRAM_READ_INTEGRATION_TYPES = {
    "integration",
    "integrationOperation",
    "integrationRelation",
}
DIAGRAM_READ_RECORD_TYPES = [
    *STRUCTURAL_RECORD_TYPES,
    "class/tree:type=indicator",
    *(f"class/{record_type}" for record_type in sorted(DIAGRAM_READ_CLASS_TYPES)),
    *(
        f"integrator/{record_type}:sanitized-provenance-only"
        for record_type in sorted(DIAGRAM_READ_INTEGRATION_TYPES)
    ),
]
DIAGRAM_READ_DERIVED_AGGREGATES = [
    "object/object -> objectCount by Data.classUuid (records and values excluded)",
    "source-bound SHA-256 of sorted per-class objectCount distribution",
    "class/indicator -> displayIndicatorCount and derivedFormulaCount by Data.classUuid",
    "class/formula -> actual formula record counts by Data.classUuid",
]
DIAGRAM_READ_EXCLUSION = (
    "object records and values (only per-class counts retained), measurements, "
    "datasets, dashboards, BPMS, publications, files, "
    "integration sources/tables/variables/schemas, connection parameters, API "
    "settings/templates, authentication, credentials, queries, request bodies, "
    "and every other top-level record type"
)

# Integration records are not copied wholesale. These normalized field names
# are the complete allowlist for their Data object. Values must also have the
# expected scalar/list/container shape below. In particular, customQuery,
# options, settings, auth, password, body, headers, variables, and connection
# material can never enter the diagram read model merely by appearing in a KS
# backup record.
INTEGRATION_SAFE_SCALAR_FIELDS = {
    "uuid",
    "name",
    "type",
    "kind",
    "status",
    "direction",
    "enabled",
    "disabled",
    "active",
    "isactive",
    "isgeneratesdata",
    "isindicator",
    "isdimension",
    "isparameter",
    "isconstant",
    "useapi",
    "usedefaultdata",
    "version",
    "index",
    "idx",
    "createdat",
    "updatedat",
    "updatedby",
    "integrationuuid",
    "operationuuid",
    "classuuid",
    "classrelationuuid",
    "relationuuid",
    "indicatoruuid",
    "sourceuuid",
    "destinationuuid",
    "targetuuid",
    "owneruuid",
    "referenceuuid",
    "parentuuid",
    "modeluuid",
    "projectuuid",
    "internalfield",
    "sourcetype",
    "sourceoperationtype",
    "taskname",
    "routename",
    "actionwithobjects",
    "actionwithobjectsbeforecreate",
}
INTEGRATION_SAFE_LIST_FIELDS = {
    "sourcesuuids",
    "previousuuids",
    "sourceoperationuuids",
    "classrelations",
    "objectstolink",
}
INTEGRATION_SAFE_CONTAINER_FIELDS = {
    "source",
    "destination",
    "target",
    "owner",
    "input",
    "output",
    "relation",
    "integration",
    "operation",
    "bindings",
    "mapping",
}
INTEGRATION_SAFE_WRAPPER_FIELDS = {
    "UUID",
    "ParentRelationUUID",
    "ProjectUUID",
    "Group",
    "Type",
}


class BackupIOError(RuntimeError):
    """Expected backup/manifest failure that callers can present without a traceback."""


@dataclass(frozen=True)
class BackupParts:
    compressed_bytes: int
    metadata_tail_bytes: int
    metadata: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_distinct_io(input_path: Path, output_path: Path) -> None:
    source = input_path.expanduser().resolve()
    destination = output_path.expanduser().resolve()
    if source == destination:
        raise BackupIOError("Refusing to overwrite the input artifact")
    try:
        if input_path.exists() and output_path.exists() and os.path.samefile(input_path, output_path):
            raise BackupIOError("Refusing to overwrite the input artifact")
    except OSError as exc:
        raise BackupIOError(f"Cannot compare input/output paths: {exc}") from exc


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def split_backup_tail(path: Path) -> BackupParts:
    """Locate and validate the raw KS metadata tail outside the zstd frame."""

    try:
        file_size = path.stat().st_size
        window_size = min(file_size, 1024 * 1024)
        with path.open("rb") as source:
            source.seek(file_size - window_size)
            window = source.read(window_size)
    except OSError as exc:
        raise BackupIOError(f"Cannot inspect backup {path}: {exc}") from exc

    marker_offset = window.rfind(TAIL_MARKER)
    if marker_offset < 0:
        raise BackupIOError("KS backup metadata tail marker was not found")
    absolute_marker = file_size - window_size + marker_offset
    length_start = marker_offset + len(TAIL_MARKER)
    length_end = window.find(b"%", length_start)
    if length_end < 0:
        raise BackupIOError("KS backup metadata tail length delimiter is missing")
    raw_length = window[length_start:length_end]
    if not raw_length.isdigit():
        raise BackupIOError("KS backup metadata tail length is not numeric")
    if len(raw_length) > 10:
        raise BackupIOError("KS backup metadata tail length is unreasonably large")
    try:
        metadata_size = int(raw_length)
    except ValueError as exc:
        raise BackupIOError("KS backup metadata tail length is invalid") from exc
    if metadata_size > 1024 * 1024:
        raise BackupIOError("KS backup metadata tail exceeds the supported limit")
    metadata_start = length_end + 1
    metadata_end = metadata_start + metadata_size
    if metadata_end != len(window):
        raise BackupIOError(
            "KS backup metadata tail length does not match the file boundary"
        )
    encoded = window[metadata_start:metadata_end]
    try:
        decoded = base64.b64decode(encoded, validate=True)
        metadata = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupIOError(f"KS backup metadata is invalid: {exc}") from exc
    if not isinstance(metadata, dict):
        raise BackupIOError("KS backup metadata must decode to a JSON object")
    if metadata.get("isFileCompressed") is not True:
        raise BackupIOError("KS backup metadata does not declare a compressed file")
    project_uuid = metadata.get("projectUuid")
    if not isinstance(project_uuid, str):
        raise BackupIOError("KS backup metadata projectUuid must be a string")
    try:
        uuid.UUID(project_uuid)
    except ValueError as exc:
        raise BackupIOError("KS backup metadata projectUuid is not a UUID") from exc
    return BackupParts(
        compressed_bytes=absolute_marker,
        metadata_tail_bytes=file_size - absolute_marker,
        metadata=metadata,
    )


def _validate_clean_record(
    value: Any, record_number: int, project_uuids: list[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BackupIOError(
            f"Clean KS backup item {record_number} is not a JSON object"
        )
    wrapper_uuid = value.get("UUID")
    data = value.get("Data")
    data_uuid = data.get("uuid") if isinstance(data, dict) else None
    if not isinstance(wrapper_uuid, str) or not wrapper_uuid:
        raise BackupIOError(
            f"Clean KS backup item {record_number} has no wrapper UUID"
        )
    if data_uuid is not None and wrapper_uuid != data_uuid:
        raise BackupIOError(
            f"Clean KS backup item {record_number} has mismatched UUID/Data.uuid"
        )
    if value.get("Group") == "project" and value.get("Type") == "project":
        project_uuid = data.get("uuid") if isinstance(data, dict) else None
        if not isinstance(project_uuid, str) or project_uuid != wrapper_uuid:
            raise BackupIOError("Clean KS backup project UUID must match Data.uuid")
        if project_uuids:
            raise BackupIOError(
                "Clean KS backup must contain exactly one project record"
            )
        project_uuids.append(project_uuid)
    return value


def _validate_clean_stream_summary(
    record_count: int, project_uuids: list[str], metadata_project: str
) -> None:
    if record_count == 0:
        raise BackupIOError("Clean KS backup record array is empty")
    if len(project_uuids) != 1:
        raise BackupIOError(
            "Clean KS backup must contain exactly one project record; "
            f"found {len(project_uuids)}"
        )
    if metadata_project not in {ZERO_UUID, project_uuids[0]}:
        raise BackupIOError(
            "KS backup metadata projectUuid does not match the project record"
        )


def unpack_backup(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Split the raw tail, decompress only the zstd frame, and atomically write JSON."""

    ensure_distinct_io(input_path, output_path)
    parts = split_backup_tail(input_path)
    zstd = shutil.which("zstd")
    if not zstd:
        raise BackupIOError("zstd executable is required for unpack")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="ks-diagram-unpack-") as temp_dir:
            compressed = Path(temp_dir) / "payload.zst"
            with input_path.open("rb") as source, compressed.open("wb") as target:
                remaining = parts.compressed_bytes
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BackupIOError("KS backup ended before the zstd frame boundary")
                    target.write(chunk)
                    remaining -= len(chunk)

            fd, temp_name = tempfile.mkstemp(
                prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
            )
            os.close(fd)
            temp_output = Path(temp_name)
            with temp_output.open("wb") as target:
                completed = subprocess.run(
                    [zstd, "-q", "-d", "-c", str(compressed)],
                    check=False,
                    stdout=target,
                    stderr=subprocess.PIPE,
                )
            if completed.returncode != 0:
                message = completed.stderr.decode("utf-8", errors="replace").strip()
                raise BackupIOError(f"zstd decompression failed: {message}")
            if temp_output.stat().st_size == 0:
                raise BackupIOError("zstd decompression produced an empty file")
            record_count = 0
            project_uuids: list[str] = []
            for value in iter_json_array(temp_output):
                record_count += 1
                _validate_clean_record(value, record_count, project_uuids)
            _validate_clean_stream_summary(
                record_count, project_uuids, parts.metadata["projectUuid"]
            )
            os.replace(temp_output, output_path)
            temp_output = None
    except OSError as exc:
        raise BackupIOError(f"Cannot unpack backup: {exc}") from exc
    finally:
        if temp_output is not None:
            temp_output.unlink(missing_ok=True)

    return {
        "valid": True,
        "input": str(input_path),
        "output": str(output_path),
        "backupBytes": input_path.stat().st_size,
        "compressedBytes": parts.compressed_bytes,
        "metadataTailBytes": parts.metadata_tail_bytes,
        "cleanBytes": output_path.stat().st_size,
        "recordCount": record_count,
        "metadata": parts.metadata,
        "hashes": {
            "backupSha256": sha256_file(input_path),
            "cleanSha256": sha256_file(output_path),
        },
    }


def iter_json_array_stream(
    source: TextIO,
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
    max_value_chars: int = MAX_JSON_VALUE_CHARS,
) -> Iterator[Any]:
    """Incrementally decode one top-level JSON array from a text stream."""

    if chunk_size < 1:
        raise BackupIOError("JSON stream chunk_size must be positive")
    if max_value_chars < 1:
        raise BackupIOError("JSON stream max_value_chars must be positive")

    def reject_constant(value: str) -> Any:
        raise BackupIOError(f"Non-standard JSON constant is forbidden: {value}")

    decoder = json.JSONDecoder(parse_constant=reject_constant)
    buffer = ""
    position = 0
    eof = False

    def compact_and_read() -> bool:
        nonlocal buffer, position, eof
        if eof:
            return False
        chunk = source.read(chunk_size)
        buffer = buffer[position:] + chunk
        position = 0
        if not chunk:
            eof = True
            return False
        return True

    def skip_whitespace() -> None:
        nonlocal position
        while True:
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position < len(buffer) or eof:
                return
            compact_and_read()

    compact_and_read()
    skip_whitespace()
    if position >= len(buffer):
        raise BackupIOError("Clean KS backup is empty")
    if buffer[position] != "[":
        raise BackupIOError("Clean KS backup must be a top-level JSON array")
    position += 1
    skip_whitespace()
    if position < len(buffer) and buffer[position] == "]":
        position += 1
    else:
        while True:
            skip_whitespace()
            if position >= len(buffer):
                raise BackupIOError("Clean KS backup array is truncated")
            if buffer[position] in {",", "]"}:
                raise BackupIOError("Clean KS backup array is missing a value")
            value_start = position
            while True:
                try:
                    value, end = decoder.raw_decode(buffer, value_start)
                    numeric_continuation = (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and end < len(buffer)
                        and buffer[end] in ".eE+-0123456789"
                    )
                    if (end == len(buffer) or numeric_continuation) and not eof:
                        prefix = buffer[value_start:]
                        chunk = source.read(chunk_size)
                        buffer = prefix + chunk
                        position = 0
                        value_start = 0
                        if not chunk:
                            eof = True
                        continue
                    if end - value_start > max_value_chars:
                        raise BackupIOError(
                            "A single KS backup JSON value exceeds the streaming limit"
                        )
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise BackupIOError(
                            f"Clean KS backup JSON is invalid: {exc}"
                        ) from exc
                    if len(buffer) - value_start > max_value_chars:
                        raise BackupIOError(
                            "A single KS backup JSON value exceeds the streaming limit"
                        )
                    prefix = buffer[value_start:]
                    chunk = source.read(chunk_size)
                    buffer = prefix + chunk
                    position = 0
                    value_start = 0
                    if not chunk:
                        eof = True
            position = end
            yield value
            skip_whitespace()
            if position >= len(buffer):
                raise BackupIOError("Clean KS backup array is truncated")
            separator = buffer[position]
            position += 1
            if separator == "]":
                break
            if separator != ",":
                raise BackupIOError(
                    "Clean KS backup array requires a comma between values"
                )
            skip_whitespace()
            if position >= len(buffer):
                raise BackupIOError("Clean KS backup array is truncated")
            if buffer[position] in {",", "]"}:
                raise BackupIOError(
                    "Clean KS backup array has an empty or trailing value"
                )

    while True:
        while position < len(buffer):
            if not buffer[position].isspace():
                raise BackupIOError(
                    "Unexpected content follows the clean KS backup array"
                )
            position += 1
        if eof:
            break
        chunk = source.read(chunk_size)
        if not chunk:
            eof = True
        elif chunk.strip():
            raise BackupIOError(
                "Unexpected content follows the clean KS backup array"
            )


def iter_json_array(
    path: Path,
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
    max_value_chars: int = MAX_JSON_VALUE_CHARS,
) -> Iterator[Any]:
    """Incrementally decode a top-level JSON array without loading it all in memory."""

    try:
        with path.open("r", encoding="utf-8") as source:
            yield from iter_json_array_stream(
                source,
                chunk_size=chunk_size,
                max_value_chars=max_value_chars,
            )
    except (OSError, UnicodeError) as exc:
        raise BackupIOError(f"Cannot stream clean backup {path}: {exc}") from exc


def is_structural_record(record: dict[str, Any]) -> bool:
    group = record.get("Group")
    record_type = record.get("Type")
    if group == "project" and record_type == "project":
        return True
    if group != "class":
        return False
    if record_type in {"class", "classL10n", "folderL10n"}:
        return True
    if record_type == "tree":
        data = record.get("Data")
        tree_type = data.get("type") if isinstance(data, dict) else None
        return tree_type in {"class", "folder"}
    return False


def _normalized_field_name(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def is_diagram_read_record(record: dict[str, Any]) -> bool:
    """Return whether a record belongs to the read-only Diagramm enrichment slice."""

    if is_structural_record(record):
        return True
    group = record.get("Group")
    record_type = record.get("Type")
    if group == "class":
        if record_type in DIAGRAM_READ_CLASS_TYPES:
            return True
        if record_type == "tree":
            data = record.get("Data")
            return isinstance(data, dict) and data.get("type") == "indicator"
        return False
    return group == "integrator" and record_type in DIAGRAM_READ_INTEGRATION_TYPES


def _sanitize_integration_value(value: Any) -> tuple[Any, int, int]:
    """Keep only allowlisted provenance leaves from a nested integration value."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        kept = 0
        removed = 0
        for key, item in value.items():
            if not isinstance(key, str):
                removed += 1
                continue
            normalized = _normalized_field_name(key)
            if normalized in INTEGRATION_SAFE_SCALAR_FIELDS and (
                item is None or isinstance(item, (str, int, float, bool))
            ):
                sanitized[key] = item
                kept += 1
                continue
            if normalized in INTEGRATION_SAFE_LIST_FIELDS and isinstance(item, list):
                safe_items: list[Any] = []
                nested_kept = 0
                nested_removed = 0
                for child in item:
                    if child is None or isinstance(child, (str, int, float, bool)):
                        safe_items.append(child)
                        nested_kept += 1
                    elif isinstance(child, dict):
                        safe_child, child_kept, child_removed = _sanitize_integration_value(child)
                        if safe_child:
                            safe_items.append(safe_child)
                        nested_kept += child_kept
                        nested_removed += child_removed
                    else:
                        nested_removed += 1
                sanitized[key] = safe_items
                kept += 1 + nested_kept
                removed += nested_removed
                continue
            if normalized in INTEGRATION_SAFE_CONTAINER_FIELDS and isinstance(item, (dict, list)):
                if isinstance(item, dict):
                    safe_item, child_kept, child_removed = _sanitize_integration_value(item)
                else:
                    safe_item = []
                    child_kept = 0
                    child_removed = 0
                    for child in item:
                        if isinstance(child, dict):
                            safe_child, item_kept, item_removed = _sanitize_integration_value(child)
                            if safe_child:
                                safe_item.append(safe_child)
                            child_kept += item_kept
                            child_removed += item_removed
                        else:
                            child_removed += 1
                sanitized[key] = safe_item
                kept += 1 + child_kept
                removed += child_removed
                continue
            removed += 1
        return sanitized, kept, removed
    return None, 0, 1


def sanitize_integration_record(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Project one integration record onto the explicit safe provenance allowlist."""

    sanitized = {
        key: record[key]
        for key in INTEGRATION_SAFE_WRAPPER_FIELDS
        if key in record
    }
    data = record.get("Data")
    safe_data, kept, removed = _sanitize_integration_value(
        data if isinstance(data, dict) else {}
    )
    sanitized["Data"] = safe_data
    removed += len(
        [
            key
            for key in record
            if key not in INTEGRATION_SAFE_WRAPPER_FIELDS and key != "Data"
        ]
    )
    return sanitized, {"keptFields": kept, "removedFields": removed}


def _select_diagram_read_record(
    record: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool, int, int]:
    if not is_diagram_read_record(record):
        return None, False, 0, 0
    if record.get("Group") == "integrator":
        sanitized, counts = sanitize_integration_record(record)
        return (
            sanitized,
            True,
            counts["keptFields"],
            counts["removedFields"],
        )
    return record, False, 0, 0


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _object_count_distribution_digest(
    *,
    source_backup_sha256: str,
    by_uuid: dict[str, dict[str, Any]],
    unresolved: dict[str, int],
) -> dict[str, str]:
    payload = {
        "sourceBackupSha256": source_backup_sha256,
        "byKsEntityUuid": [
            [class_uuid, by_uuid[class_uuid]["objectCount"]]
            for class_uuid in sorted(by_uuid)
        ],
        "unresolvedObjectOwnerCounts": [
            [class_uuid, unresolved[class_uuid]]
            for class_uuid in sorted(unresolved)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "algorithm": "sha256",
        "canonicalization": OBJECT_COUNT_DIGEST_CANONICALIZATION,
        "sourceBackupSha256": source_backup_sha256,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def build_class_stats(
    records: list[dict[str, Any]],
    object_counts_by_class_uuid: dict[str, int],
    *,
    source_backup_sha256: str,
) -> dict[str, Any]:
    """Build read-only owner aggregates without retaining any object record."""

    if not _is_sha256_hex(source_backup_sha256):
        raise BackupIOError("classStats requires a lowercase source backup SHA-256")

    class_ids = sorted(
        str(record["UUID"])
        for record in records
        if record.get("Group") == "class"
        and record.get("Type") == "class"
        and isinstance(record.get("UUID"), str)
    )
    stats = {
        class_uuid: {
            "objectCount": object_counts_by_class_uuid.get(class_uuid, 0),
            "ksIndicatorCount": 0,
            "displayIndicatorCount": 0,
            "derivedFormulaCount": 0,
            "actualFormulaRecordCount": 0,
            "activeRegularFormulaRecordCount": 0,
            "actualCalculatedIndicatorCount": 0,
        }
        for class_uuid in class_ids
    }
    active_indicator_ids_by_owner: dict[str, set[str]] = {}

    for record in records:
        if record.get("Group") != "class":
            continue
        record_type = record.get("Type")
        data = record.get("Data") if isinstance(record.get("Data"), dict) else {}
        owner_uuid = data.get("classUuid")
        if not isinstance(owner_uuid, str) or owner_uuid not in stats:
            continue
        if record_type == "indicator":
            stats[owner_uuid]["ksIndicatorCount"] += 1
            if data.get("dataType") == "number":
                stats[owner_uuid]["displayIndicatorCount"] += 1
                stats[owner_uuid]["derivedFormulaCount"] += 1
        elif record_type == "formula":
            stats[owner_uuid]["actualFormulaRecordCount"] += 1
            if (
                data.get("type") == "regular"
                and data.get("enabled") is True
                and data.get("isVersion") is not True
            ):
                stats[owner_uuid]["activeRegularFormulaRecordCount"] += 1
                indicator_uuid = data.get("indicatorUuid")
                if isinstance(indicator_uuid, str):
                    active_indicator_ids_by_owner.setdefault(owner_uuid, set()).add(
                        indicator_uuid
                    )

    for owner_uuid, indicator_ids in active_indicator_ids_by_owner.items():
        stats[owner_uuid]["actualCalculatedIndicatorCount"] = len(indicator_ids)

    unresolved = {
        class_uuid: count
        for class_uuid, count in object_counts_by_class_uuid.items()
        if class_uuid not in stats
    }
    sorted_unresolved = dict(sorted(unresolved.items()))
    return {
        "readOnly": True,
        "containsObjectRecords": False,
        "containsObjectValues": False,
        "formulaCountRule": "derivedFormulaCount = displayIndicatorCount",
        "displayIndicatorRule": "class/indicator.Data.dataType == number",
        "byKsEntityUuid": stats,
        "unresolvedObjectOwnerCounts": sorted_unresolved,
        "objectCountDigest": _object_count_distribution_digest(
            source_backup_sha256=source_backup_sha256,
            by_uuid=stats,
            unresolved=sorted_unresolved,
        ),
    }


def validate_class_stats(
    records: list[dict[str, Any]],
    class_stats: Any,
    source_type_counts: Any,
    source_sha256: Any,
) -> list[str]:
    """Validate aggregate shape and every count reproducible from the read slice."""

    errors: list[str] = []
    if not isinstance(class_stats, dict):
        return ["classStats must be an object"]
    if class_stats.get("readOnly") is not True:
        errors.append("classStats must keep readOnly=true")
    if class_stats.get("containsObjectRecords") is not False:
        errors.append("classStats must keep containsObjectRecords=false")
    if class_stats.get("containsObjectValues") is not False:
        errors.append("classStats must keep containsObjectValues=false")
    if class_stats.get("formulaCountRule") != (
        "derivedFormulaCount = displayIndicatorCount"
    ):
        errors.append("classStats formulaCountRule is unsupported")
    by_uuid = class_stats.get("byKsEntityUuid")
    if not isinstance(by_uuid, dict):
        return errors + ["classStats.byKsEntityUuid must be an object"]

    digest = class_stats.get("objectCountDigest")
    if not isinstance(digest, dict):
        errors.append("classStats.objectCountDigest must be an object")
        digest = {}
    if digest.get("algorithm") != "sha256":
        errors.append("classStats objectCountDigest algorithm must be sha256")
    if digest.get("canonicalization") != OBJECT_COUNT_DIGEST_CANONICALIZATION:
        errors.append("classStats objectCountDigest canonicalization is unsupported")
    digest_source_sha256 = digest.get("sourceBackupSha256")
    if not _is_sha256_hex(digest_source_sha256):
        errors.append("classStats objectCountDigest source SHA-256 is invalid")
    if source_sha256 != digest_source_sha256:
        errors.append("classStats objectCountDigest is not bound to source.sha256")
    if not _is_sha256_hex(digest.get("sha256")):
        errors.append("classStats objectCountDigest SHA-256 is invalid")

    object_counts: dict[str, int] = {}
    for class_uuid, value in by_uuid.items():
        if not isinstance(class_uuid, str) or not isinstance(value, dict):
            errors.append("classStats entries must map UUID strings to objects")
            continue
        count = value.get("objectCount")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"classStats {class_uuid} has invalid objectCount")
            continue
        object_counts[class_uuid] = count

    unresolved = class_stats.get("unresolvedObjectOwnerCounts")
    if not isinstance(unresolved, dict):
        errors.append("classStats unresolvedObjectOwnerCounts must be an object")
        unresolved = {}
    valid_unresolved: dict[str, int] = {}
    for class_uuid, count in unresolved.items():
        if (
            not isinstance(class_uuid, str)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            errors.append("classStats unresolved object counts are invalid")
            continue
        valid_unresolved[class_uuid] = count
        if class_uuid in object_counts:
            errors.append("classStats resolved and unresolved object owners overlap")

    combined_object_counts = {**object_counts, **valid_unresolved}
    recompute_source_sha256 = (
        digest_source_sha256
        if _is_sha256_hex(digest_source_sha256)
        else "0" * 64
    )
    recomputed = build_class_stats(
        records,
        combined_object_counts,
        source_backup_sha256=recompute_source_sha256,
    )
    recomputed_by_uuid = recomputed["byKsEntityUuid"]
    if set(by_uuid) != set(recomputed_by_uuid):
        errors.append("classStats owner UUID set differs from selected class records")
    for class_uuid in sorted(set(by_uuid).intersection(recomputed_by_uuid)):
        actual = by_uuid[class_uuid]
        expected = recomputed_by_uuid[class_uuid]
        for field, expected_value in expected.items():
            if actual.get(field) != expected_value:
                errors.append(
                    f"classStats {class_uuid} {field} differs from read-model records"
                )
        if actual.get("derivedFormulaCount") != actual.get(
            "displayIndicatorCount"
        ):
            errors.append(
                f"classStats {class_uuid} must keep derivedFormulaCount equal to displayIndicatorCount"
            )
    if digest != recomputed["objectCountDigest"]:
        errors.append("classStats objectCountDigest differs from objectCount distribution")

    if not isinstance(source_type_counts, dict):
        errors.append("sourceCounts must be an object when classStats is present")
    else:
        source_object_count = source_type_counts.get("object/object", 0)
        aggregate_object_count = sum(object_counts.values()) + sum(
            valid_unresolved.values()
        )
        if source_object_count != aggregate_object_count:
            errors.append(
                "classStats objectCount total differs from sourceCounts object/object"
            )

    return errors


def validate_diagram_read_records(
    records: list[dict[str, Any]],
    *,
    class_stats: Any = None,
    source_type_counts: Any = None,
    source_sha256: Any = None,
) -> dict[str, Any]:
    """Validate a read-only structure/indicator/formula/provenance selection."""

    errors: list[str] = []
    warnings: list[str] = []
    structural_records = [record for record in records if is_structural_record(record)]
    errors.extend(validate_structural_slice(structural_records))

    uuids = [record.get("UUID") for record in records]
    if any(not isinstance(value, str) or not value for value in uuids):
        errors.append("every diagram read record requires a UUID")
    uuid_counts: dict[str, int] = {}
    for value in uuids:
        if isinstance(value, str):
            uuid_counts[value] = uuid_counts.get(value, 0) + 1
    duplicate_uuids = sorted(
        value for value, count in uuid_counts.items() if count > 1
    )
    for value in duplicate_uuids:
        errors.append(f"diagram read records contain duplicate UUID {value}")

    selected_type_counts: dict[str, int] = {}
    for record in records:
        key = f"{record.get('Group')}/{record.get('Type')}"
        selected_type_counts[key] = selected_type_counts.get(key, 0) + 1
        if not is_diagram_read_record(record):
            errors.append(f"record {record.get('UUID')} is outside {DIAGRAM_READ_PROFILE}")
        if not isinstance(record.get("Data"), dict):
            errors.append(f"diagram read record {record.get('UUID')} has no Data object")
        if record.get("Group") == "integrator":
            sanitized, _ = sanitize_integration_record(record)
            if sanitized != record:
                errors.append(
                    f"integration provenance {record.get('UUID')} contains a non-allowlisted field"
                )

    class_records = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "class"
    ]
    class_ids = {
        str(record["UUID"])
        for record in class_records
        if isinstance(record.get("UUID"), str)
    }
    tree_records = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "tree"
    ]
    tree_by_uuid = {
        str(record["UUID"]): record
        for record in tree_records
        if isinstance(record.get("UUID"), str)
    }
    trees_by_reference: dict[str, list[dict[str, Any]]] = {}
    for tree in tree_records:
        data = tree.get("Data") if isinstance(tree.get("Data"), dict) else {}
        reference_uuid = data.get("referenceUuid")
        if isinstance(reference_uuid, str):
            trees_by_reference.setdefault(reference_uuid, []).append(tree)

    indicators = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "indicator"
    ]
    indicator_ids = {
        str(record["UUID"])
        for record in indicators
        if isinstance(record.get("UUID"), str)
    }
    indicator_owners: dict[str, str] = {}
    for indicator in indicators:
        indicator_uuid = str(indicator.get("UUID"))
        data = indicator.get("Data") if isinstance(indicator.get("Data"), dict) else {}
        owner_uuid = data.get("classUuid")
        if not isinstance(owner_uuid, str) or owner_uuid not in class_ids:
            errors.append(f"indicator {indicator_uuid} has missing class/relation owner {owner_uuid}")
            continue
        indicator_owners[indicator_uuid] = owner_uuid
        indicator_trees = [
            tree
            for tree in trees_by_reference.get(indicator_uuid, [])
            if isinstance(tree.get("Data"), dict)
            and tree["Data"].get("type") == "indicator"
        ]
        if len(indicator_trees) != 1:
            errors.append(
                f"indicator {indicator_uuid} requires exactly one indicator tree; found {len(indicator_trees)}"
            )
            continue
        owner_tree_ids = {
            str(tree["UUID"])
            for tree in trees_by_reference.get(owner_uuid, [])
            if isinstance(tree.get("Data"), dict)
            and tree["Data"].get("type") == "class"
        }
        cursor = indicator_trees[0]["Data"].get("parentUuid")
        ancestors: set[str] = set()
        while isinstance(cursor, str) and cursor not in ancestors:
            ancestors.add(cursor)
            parent = tree_by_uuid.get(cursor)
            if parent is None or not isinstance(parent.get("Data"), dict):
                break
            cursor = parent["Data"].get("parentUuid")
        if not owner_tree_ids.intersection(ancestors):
            errors.append(
                f"indicator {indicator_uuid} tree ancestry does not terminate at owner {owner_uuid}"
            )

    localized_indicator_ids: set[str] = set()
    for record in records:
        if record.get("Group") != "class" or record.get("Type") not in {
            "indicatorL10n",
            "indicatorUnitL10n",
            "indicatorDimension",
        }:
            continue
        data = record.get("Data") if isinstance(record.get("Data"), dict) else {}
        indicator_uuid = data.get("indicatorUuid")
        if indicator_uuid not in indicator_ids:
            errors.append(
                f"{record.get('Type')} {record.get('UUID')} references missing indicator {indicator_uuid}"
            )
        if record.get("Type") == "indicatorL10n" and isinstance(indicator_uuid, str):
            localized_indicator_ids.add(indicator_uuid)
    missing_l10n = sorted(indicator_ids - localized_indicator_ids)
    if missing_l10n:
        warnings.append(f"{len(missing_l10n)} indicator(s) have no indicatorL10n record")

    formulas = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "formula"
    ]
    formula_ids = {
        str(record["UUID"])
        for record in formulas
        if isinstance(record.get("UUID"), str)
    }
    for formula in formulas:
        formula_uuid = str(formula.get("UUID"))
        data = formula.get("Data") if isinstance(formula.get("Data"), dict) else {}
        indicator_uuid = data.get("indicatorUuid")
        owner_uuid = data.get("classUuid")
        if indicator_uuid not in indicator_ids:
            errors.append(f"formula {formula_uuid} references missing indicator {indicator_uuid}")
        elif indicator_owners.get(str(indicator_uuid)) != owner_uuid:
            errors.append(f"formula {formula_uuid} owner differs from its indicator owner")
    formula_elements = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "formulaElement"
    ]
    for element in formula_elements:
        data = element.get("Data") if isinstance(element.get("Data"), dict) else {}
        formula_uuid = data.get("formulaUuid")
        if formula_uuid not in formula_ids:
            errors.append(
                f"formulaElement {element.get('UUID')} references missing formula {formula_uuid}"
            )
        indicator_uuid = data.get("indicatorUuid")
        if isinstance(indicator_uuid, str) and indicator_uuid not in indicator_ids:
            errors.append(
                f"formulaElement {element.get('UUID')} references missing indicator {indicator_uuid}"
            )

    counts = {
        "records": len(records),
        "structuralRecords": len(structural_records),
        "classesAndRelationClasses": len(class_records),
        "indicators": len(indicators),
        "indicatorL10n": selected_type_counts.get("class/indicatorL10n", 0),
        "indicatorUnitL10n": selected_type_counts.get("class/indicatorUnitL10n", 0),
        "indicatorDimensions": selected_type_counts.get("class/indicatorDimension", 0),
        "formulas": len(formulas),
        "formulaElements": len(formula_elements),
        "integrationProvenance": sum(
            count
            for key, count in selected_type_counts.items()
            if key.startswith("integrator/")
        ),
    }
    if class_stats is not None:
        errors.extend(
            validate_class_stats(
                records,
                class_stats,
                source_type_counts,
                source_sha256,
            )
        )
        by_uuid = class_stats.get("byKsEntityUuid", {})
        if isinstance(by_uuid, dict):
            counts["objectRecordsAggregated"] = sum(
                value.get("objectCount", 0)
                for value in by_uuid.values()
                if isinstance(value, dict)
                and isinstance(value.get("objectCount"), int)
                and not isinstance(value.get("objectCount"), bool)
            )
            unresolved = class_stats.get("unresolvedObjectOwnerCounts", {})
            if isinstance(unresolved, dict):
                counts["objectRecordsAggregated"] += sum(
                    value
                    for value in unresolved.values()
                    if isinstance(value, int) and not isinstance(value, bool)
                )
            counts["classStats"] = len(by_uuid)
    return {
        "kind": "diagram-read-model",
        "profile": DIAGRAM_READ_PROFILE,
        "valid": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "counts": counts,
        "selectedTypeCounts": dict(sorted(selected_type_counts.items())),
        "readOnly": True,
        "restorePayload": False,
        "liveRestoreBlocked": True,
    }


def validate_structural_slice(records: list[dict[str, Any]]) -> list[str]:
    """Check the visible class/relation graph required by structural-v0.1."""

    errors: list[str] = []
    by_uuid = {
        str(record.get("UUID")): record
        for record in records
        if isinstance(record.get("UUID"), str) and record.get("UUID")
    }

    def data_of(record: dict[str, Any]) -> dict[str, Any]:
        value = record.get("Data")
        return value if isinstance(value, dict) else {}

    for record in records:
        data = record.get("Data")
        if not isinstance(data, dict):
            errors.append(f"structural record {record.get('UUID')} has no Data object")
        elif data.get("uuid") != record.get("UUID"):
            errors.append(f"structural record {record.get('UUID')} has mismatched Data.uuid")

    class_records = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "class"
    ]
    ordinary: list[dict[str, Any]] = []
    relation_like: list[dict[str, Any]] = []
    helpers: list[dict[str, Any]] = []
    for record in class_records:
        data = data_of(record)
        source = data.get("relatedSourceUuid")
        target = data.get("relatedDestinationUuid")
        if source is None and target is None:
            ordinary.append(record)
            continue
        if not isinstance(source, str) or not isinstance(target, str):
            errors.append(f"class relation {record.get('UUID')} has incomplete endpoints")
            continue
        relation_like.append(record)
        name = str(data.get("name") or record.get("Name") or "")
        if name.startswith("[[_relation_]]_") or data.get("objectEntityCategory") == "undefined":
            helpers.append(record)

    ordinary_ids = {str(record["UUID"]) for record in ordinary}
    semantic = [
        record
        for record in relation_like
        if record not in helpers
        and data_of(record).get("relatedSourceUuid") in ordinary_ids
        and data_of(record).get("relatedDestinationUuid") in ordinary_ids
    ]
    unexplained = [record for record in relation_like if record not in helpers and record not in semantic]
    for record in unexplained:
        errors.append(f"semantic relation {record.get('UUID')} has invalid ordinary endpoints")

    tree_records = [
        record
        for record in records
        if record.get("Group") == "class" and record.get("Type") == "tree"
    ]
    tree_ids = {str(record.get("UUID")) for record in tree_records}
    tree_refs: dict[str, int] = {}
    for record in tree_records:
        data = data_of(record)
        parent = data.get("parentUuid")
        if parent is not None and str(parent) not in tree_ids:
            errors.append(f"tree {record.get('UUID')} has missing parent {parent}")
        reference = data.get("referenceUuid")
        if data.get("type") == "class":
            if reference not in by_uuid:
                errors.append(f"tree {record.get('UUID')} has missing class reference {reference}")
            if isinstance(reference, str):
                tree_refs[reference] = tree_refs.get(reference, 0) + 1

    l10n_refs: dict[str, int] = {}
    for record in records:
        if record.get("Group") == "class" and record.get("Type") == "classL10n":
            class_uuid = data_of(record).get("classUuid")
            if isinstance(class_uuid, str):
                l10n_refs[class_uuid] = l10n_refs.get(class_uuid, 0) + 1

    visible_ids = {
        str(record["UUID"]) for record in ordinary + semantic if record.get("UUID")
    }
    helper_ids = {str(record["UUID"]) for record in helpers if record.get("UUID")}
    for entity_uuid in sorted(visible_ids):
        if tree_refs.get(entity_uuid, 0) != 1:
            errors.append(f"visible entity {entity_uuid} must have exactly one class tree")
        if l10n_refs.get(entity_uuid, 0) < 1:
            errors.append(f"visible entity {entity_uuid} must have classL10n")
    for helper_uuid in sorted(helper_ids):
        if tree_refs.get(helper_uuid, 0) or l10n_refs.get(helper_uuid, 0):
            errors.append(f"helper {helper_uuid} must not have tree/classL10n")

    def nested_ids(record: dict[str, Any]) -> set[str]:
        return {
            str(item.get("uuid"))
            for item in data_of(record).get("relations") or []
            if isinstance(item, dict) and item.get("uuid")
        }

    for relation in semantic:
        relation_uuid = str(relation["UUID"])
        data = data_of(relation)
        source_uuid = str(data.get("relatedSourceUuid"))
        target_uuid = str(data.get("relatedDestinationUuid"))
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []

        def add_helper_candidate(
            source_start: str,
            source_end: str,
            target_start: str,
            target_end: str,
        ) -> None:
            source_side = [
                helper
                for helper in helpers
                if data_of(helper).get("relatedSourceUuid") == source_start
                and data_of(helper).get("relatedDestinationUuid") == source_end
            ]
            target_side = [
                helper
                for helper in helpers
                if data_of(helper).get("relatedSourceUuid") == target_start
                and data_of(helper).get("relatedDestinationUuid") == target_end
            ]
            if (
                len(source_side) == 1
                and len(target_side) == 1
                and source_side[0].get("UUID") != target_side[0].get("UUID")
            ):
                candidates.append((source_side[0], target_side[0]))

        add_helper_candidate(
            source_uuid, relation_uuid, relation_uuid, target_uuid
        )
        if source_uuid != target_uuid:
            add_helper_candidate(
                relation_uuid, source_uuid, target_uuid, relation_uuid
            )
        if len(candidates) > 1:
            relation_members = nested_ids(relation)
            candidates = [
                candidate
                for candidate in candidates
                if {
                    str(candidate[0].get("UUID")),
                    str(candidate[1].get("UUID")),
                }
                == relation_members
            ]
        if len(candidates) != 1:
            errors.append(f"semantic relation {relation_uuid} requires two oriented helpers")
            continue
        source_helper, target_helper = candidates[0]
        source_helper_uuid = str(source_helper["UUID"])
        target_helper_uuid = str(target_helper["UUID"])
        if nested_ids(relation) != {source_helper_uuid, target_helper_uuid}:
            errors.append(f"semantic relation {relation_uuid} has invalid helper closure")
        source = by_uuid.get(source_uuid)
        target = by_uuid.get(target_uuid)
        if source is None or target is None:
            errors.append(f"semantic relation {relation_uuid} endpoint is missing")
            continue
        if not {source_helper_uuid, relation_uuid}.issubset(nested_ids(source)):
            errors.append(f"semantic relation {relation_uuid} source closure is invalid")
        if not {relation_uuid, target_helper_uuid}.issubset(nested_ids(target)):
            errors.append(f"semantic relation {relation_uuid} target closure is invalid")
    return sorted(set(errors))


def _validate_selected_structural_records(selected: list[dict[str, Any]]) -> None:
    project_records = [
        item
        for item in selected
        if item.get("Group") == "project" and item.get("Type") == "project"
    ]
    if len(project_records) != 1:
        raise BackupIOError(
            "Structural slice requires exactly one project record; "
            f"found {len(project_records)}"
        )
    uuids = [item.get("UUID") for item in selected]
    if any(not isinstance(value, str) or not value for value in uuids):
        raise BackupIOError("Every selected structural record requires a UUID")
    if len(set(uuids)) != len(uuids):
        raise BackupIOError("Selected structural records contain duplicate UUIDs")
    structural_errors = validate_structural_slice(selected)
    if structural_errors:
        raise BackupIOError(
            "Structural slice validation failed: "
            + "; ".join(structural_errors[:5])
        )


def _structural_envelope(
    *,
    selected: list[dict[str, Any]],
    total: int,
    type_counts: dict[str, int],
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "format": "teamvalue.ks-structural-slice",
        "formatVersion": FORMAT_VERSION,
        "profile": PROFILE,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "source": {**source, "recordCount": total},
        "selection": {
            "recordTypes": STRUCTURAL_RECORD_TYPES,
            "excluded": STRUCTURAL_EXCLUSION,
        },
        "sourceCounts": dict(sorted(type_counts.items())),
        "selectedRecordCount": len(selected),
        "records": selected,
    }


def _diagram_read_envelope(
    *,
    selected: list[dict[str, Any]],
    total: int,
    type_counts: dict[str, int],
    source: dict[str, Any],
    validation: dict[str, Any],
    sanitized_records: int,
    kept_integration_fields: int,
    removed_integration_fields: int,
    class_stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "format": DIAGRAM_READ_FORMAT,
        "formatVersion": FORMAT_VERSION,
        "profile": DIAGRAM_READ_PROFILE,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "readOnly": True,
        "restorePayload": False,
        "liveRestoreBlocked": True,
        "allowedDownstreamUse": ["diagram-enrichment", "read-only-audit"],
        "source": {**source, "recordCount": total},
        "selection": {
            "recordTypes": DIAGRAM_READ_RECORD_TYPES,
            "derivedAggregates": DIAGRAM_READ_DERIVED_AGGREGATES,
            "excluded": DIAGRAM_READ_EXCLUSION,
            "integrationProvenance": {
                "sanitized": True,
                "selectedRecordTypes": sorted(DIAGRAM_READ_INTEGRATION_TYPES),
                "selectedRecords": sanitized_records,
                "keptFieldCount": kept_integration_fields,
                "removedFieldCount": removed_integration_fields,
                "safeWrapperFields": sorted(INTEGRATION_SAFE_WRAPPER_FIELDS),
                "safeDataScalarFieldsNormalized": sorted(INTEGRATION_SAFE_SCALAR_FIELDS),
                "safeDataListFieldsNormalized": sorted(INTEGRATION_SAFE_LIST_FIELDS),
                "safeDataContainerFieldsNormalized": sorted(INTEGRATION_SAFE_CONTAINER_FIELDS),
            },
        },
        "sourceCounts": dict(sorted(type_counts.items())),
        "selectedRecordCount": len(selected),
        "selectedCounts": validation["counts"],
        "classStats": class_stats,
        "validation": validation,
        "records": selected,
    }


def slice_structural_records(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Create a small structural-v0.1 record envelope from a full clean backup."""

    ensure_distinct_io(input_path, output_path)
    selected: list[dict[str, Any]] = []
    total = 0
    type_counts: dict[str, int] = {}
    for value in iter_json_array(input_path):
        total += 1
        if not isinstance(value, dict):
            raise BackupIOError(f"Full backup item {total} is not a JSON object")
        key = f"{value.get('Group')}/{value.get('Type')}"
        type_counts[key] = type_counts.get(key, 0) + 1
        if is_structural_record(value):
            selected.append(value)

    _validate_selected_structural_records(selected)
    input_sha256 = sha256_file(input_path)
    envelope = _structural_envelope(
        selected=selected,
        total=total,
        type_counts=type_counts,
        source={"file": str(input_path), "sha256": input_sha256},
    )
    atomic_write_json(output_path, envelope)
    return {
        "valid": True,
        "input": str(input_path),
        "output": str(output_path),
        "sourceRecordCount": total,
        "selectedRecordCount": len(selected),
        "sourceTypeCounts": dict(sorted(type_counts.items())),
        "hashes": {
            "inputSha256": input_sha256,
            "outputSha256": sha256_file(output_path),
        },
    }


def _feed_exact_backup_frame(
    input_path: Path,
    target: Any,
    parts: BackupParts,
    result: dict[str, Any],
    errors: list[Exception],
) -> None:
    """Feed only the zstd frame and hash the complete packed backup once."""

    digest = hashlib.sha256()
    try:
        with input_path.open("rb") as source:
            remaining = parts.compressed_bytes
            while remaining:
                chunk = source.read(min(STREAM_CHUNK_BYTES, remaining))
                if not chunk:
                    raise BackupIOError(
                        "KS backup ended before the zstd frame boundary"
                    )
                digest.update(chunk)
                target.write(chunk)
                remaining -= len(chunk)
            tail = source.read()
            if len(tail) != parts.metadata_tail_bytes:
                raise BackupIOError(
                    "KS backup size changed while streaming the zstd frame"
                )
            digest.update(tail)
        result["backupSha256"] = digest.hexdigest()
        result["backupBytes"] = parts.compressed_bytes + len(tail)
    except Exception as exc:  # delivered to the consumer thread safely
        errors.append(exc)
    finally:
        try:
            target.close()
        except OSError as exc:
            if not errors:
                errors.append(exc)


def _slice_packed_backup_for_profile(
    input_path: Path, output_path: Path, selection_profile: str
) -> dict[str, Any]:
    """Stream a packed KS backup through one exact local selection profile."""

    if selection_profile not in {PROFILE, DIAGRAM_READ_PROFILE}:
        raise BackupIOError(f"Unsupported packed slice profile: {selection_profile}")

    ensure_distinct_io(input_path, output_path)
    parts = split_backup_tail(input_path)
    zstd = shutil.which("zstd")
    if not zstd:
        raise BackupIOError("zstd executable is required for slice-packed")

    try:
        process = subprocess.Popen(
            [
                zstd,
                "-q",
                "-d",
                "-c",
                f"-M{ZSTD_MEMORY_LIMIT_MIB}MB",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise BackupIOError(f"Cannot start zstd decompression: {exc}") from exc
    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise BackupIOError("Cannot open zstd streaming pipes")

    producer_result: dict[str, Any] = {}
    producer_errors: list[Exception] = []
    producer = threading.Thread(
        target=_feed_exact_backup_frame,
        args=(input_path, process.stdin, parts, producer_result, producer_errors),
        name="ks-packed-frame-reader",
        daemon=True,
    )
    producer.start()

    selected: list[dict[str, Any]] = []
    selected_json_chars = 0
    sanitized_integration_records = 0
    kept_integration_fields = 0
    removed_integration_fields = 0
    object_counts_by_class_uuid: dict[str, int] = {}
    total = 0
    type_counts: dict[str, int] = {}
    project_uuids: list[str] = []
    stream_error: Exception | None = None
    text_stream = io.TextIOWrapper(process.stdout, encoding="utf-8", errors="strict")
    try:
        for value in iter_json_array_stream(text_stream):
            total += 1
            record = _validate_clean_record(value, total, project_uuids)
            key = f"{record.get('Group')}/{record.get('Type')}"
            if key not in type_counts and len(type_counts) >= MAX_SOURCE_TYPE_KEYS:
                raise BackupIOError("KS backup exceeds the record-type limit")
            type_counts[key] = type_counts.get(key, 0) + 1
            if selection_profile == DIAGRAM_READ_PROFILE and key == "object/object":
                data = record.get("Data")
                class_uuid = data.get("classUuid") if isinstance(data, dict) else None
                if isinstance(class_uuid, str) and class_uuid:
                    if class_uuid not in object_counts_by_class_uuid:
                        if len(object_counts_by_class_uuid) >= MAX_OBJECT_CLASS_UUIDS:
                            raise BackupIOError(
                                "KS backup exceeds the unique object classUuid limit"
                            )
                        object_counts_by_class_uuid[class_uuid] = 0
                    object_counts_by_class_uuid[class_uuid] += 1
            if selection_profile == PROFILE:
                selected_record = record if is_structural_record(record) else None
                was_sanitized = False
                kept_fields = 0
                removed_fields = 0
            else:
                selected_record, was_sanitized, kept_fields, removed_fields = (
                    _select_diagram_read_record(record)
                )
            if selected_record is not None:
                if len(selected) >= MAX_SELECTED_RECORDS:
                    raise BackupIOError(
                        f"{selection_profile} slice exceeds the selected-record limit"
                    )
                record_chars = len(
                    json.dumps(
                        selected_record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                if selected_json_chars + record_chars > MAX_SELECTED_JSON_CHARS:
                    raise BackupIOError(
                        f"{selection_profile} slice exceeds the selected-content limit"
                    )
                selected_json_chars += record_chars
                selected.append(selected_record)
                if was_sanitized:
                    sanitized_integration_records += 1
                    kept_integration_fields += kept_fields
                    removed_integration_fields += removed_fields
    except (BackupIOError, OSError, UnicodeError) as exc:
        stream_error = exc
    finally:
        if stream_error is not None and process.poll() is None:
            process.terminate()
        try:
            text_stream.close()
        except OSError as exc:
            if stream_error is None:
                stream_error = exc
        producer.join(timeout=10)
        if producer.is_alive():
            if process.poll() is None:
                process.kill()
            producer.join(timeout=5)
            if stream_error is None:
                stream_error = BackupIOError(
                    "Timed out while feeding the bounded zstd frame"
                )
        try:
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait()
            if stream_error is None:
                stream_error = BackupIOError(
                    "Timed out while finishing zstd decompression"
                )
        stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        process.stderr.close()

    if stream_error is not None:
        if isinstance(stream_error, BackupIOError):
            raise stream_error
        raise BackupIOError(
            f"Cannot stream packed KS backup: {stream_error}"
        ) from stream_error
    if producer_errors:
        error = producer_errors[0]
        if isinstance(error, BackupIOError):
            raise error
        raise BackupIOError(f"Cannot read packed KS backup: {error}") from error
    if return_code != 0:
        raise BackupIOError(
            "zstd decompression failed: " + (stderr or f"exit code {return_code}")
        )
    _validate_clean_stream_summary(
        total, project_uuids, parts.metadata["projectUuid"]
    )
    backup_sha256 = producer_result.get("backupSha256")
    backup_bytes = producer_result.get("backupBytes")
    expected_backup_bytes = parts.compressed_bytes + parts.metadata_tail_bytes
    if not isinstance(backup_sha256, str) or backup_bytes != expected_backup_bytes:
        raise BackupIOError("Packed backup hashing did not complete")
    if selection_profile == PROFILE:
        _validate_selected_structural_records(selected)
        read_validation: dict[str, Any] | None = None
        class_stats: dict[str, Any] | None = None
    else:
        class_stats = build_class_stats(
            selected,
            object_counts_by_class_uuid,
            source_backup_sha256=backup_sha256,
        )
        read_validation = validate_diagram_read_records(
            selected,
            class_stats=class_stats,
            source_type_counts=type_counts,
            source_sha256=backup_sha256,
        )
        if not read_validation["valid"]:
            raise BackupIOError(
                "Diagram read slice validation failed: "
                + "; ".join(read_validation["errors"][:5])
            )
    if split_backup_tail(input_path) != parts:
        raise BackupIOError("KS backup metadata changed while streaming")

    source = {
        "kind": "packed-backup-stream",
        "file": str(input_path),
        "sha256": backup_sha256,
        "compressedBytes": parts.compressed_bytes,
        "metadataTailBytes": parts.metadata_tail_bytes,
    }
    if selection_profile == PROFILE:
        envelope = _structural_envelope(
            selected=selected,
            total=total,
            type_counts=type_counts,
            source=source,
        )
        selection = {
            "recordTypes": STRUCTURAL_RECORD_TYPES,
            "excluded": STRUCTURAL_EXCLUSION,
        }
    else:
        if read_validation is None:  # defensive type narrowing
            raise BackupIOError("Diagram read validation did not run")
        if class_stats is None:
            raise BackupIOError("Diagram read class statistics were not built")
        envelope = _diagram_read_envelope(
            selected=selected,
            total=total,
            type_counts=type_counts,
            source=source,
            validation=read_validation,
            sanitized_records=sanitized_integration_records,
            kept_integration_fields=kept_integration_fields,
            removed_integration_fields=removed_integration_fields,
            class_stats=class_stats,
        )
        selection = envelope["selection"]
    atomic_write_json(output_path, envelope)
    output_sha256 = sha256_file(output_path)
    report = {
        "valid": True,
        "mode": "packed-stream",
        "profile": selection_profile,
        "input": str(input_path),
        "output": str(output_path),
        "backupBytes": backup_bytes,
        "compressedBytes": parts.compressed_bytes,
        "metadataTailBytes": parts.metadata_tail_bytes,
        "recordCount": total,
        "selectedRecordCount": len(selected),
        "sourceTypeCounts": dict(sorted(type_counts.items())),
        "selection": selection,
        "streamingLimits": {
            "chunkBytes": STREAM_CHUNK_BYTES,
            "maxJsonValueChars": MAX_JSON_VALUE_CHARS,
            "maxSelectedRecords": MAX_SELECTED_RECORDS,
            "maxSelectedJsonChars": MAX_SELECTED_JSON_CHARS,
            "maxSourceTypeKeys": MAX_SOURCE_TYPE_KEYS,
            "maxObjectClassUuids": MAX_OBJECT_CLASS_UUIDS,
            "zstdMemoryMiB": ZSTD_MEMORY_LIMIT_MIB,
        },
        "metadata": parts.metadata,
        "hashes": {
            "backupSha256": backup_sha256,
            "outputSha256": output_sha256,
        },
        "liveRestoreBlocked": True,
        "readOnly": selection_profile == DIAGRAM_READ_PROFILE,
        "restorePayload": False if selection_profile == DIAGRAM_READ_PROFILE else None,
        "validation": read_validation,
    }
    if selection_profile == DIAGRAM_READ_PROFILE:
        report["classStats"] = envelope["classStats"]
    return report


def slice_packed_backup(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Stream a packed KS backup directly into a structural-v0.1 slice."""

    report = _slice_packed_backup_for_profile(input_path, output_path, PROFILE)
    # Preserve the established structural-v0.1 report shape exactly.
    report.pop("profile", None)
    report.pop("readOnly", None)
    report.pop("restorePayload", None)
    report.pop("validation", None)
    return report


def slice_packed_diagram_read_model(
    input_path: Path, output_path: Path
) -> dict[str, Any]:
    """Create a sanitized read-only enrichment model; never a restore payload."""

    return _slice_packed_backup_for_profile(
        input_path, output_path, DIAGRAM_READ_PROFILE
    )


def _manifest_path(manifest_path: Path, artifact_path: Path) -> str:
    manifest_dir = manifest_path.expanduser().resolve().parent
    resolved = artifact_path.expanduser().resolve()
    try:
        return str(resolved.relative_to(manifest_dir))
    except ValueError:
        raise BackupIOError(
            f"Artifact must stay inside the manifest run directory: {resolved}"
        ) from None


def ensure_manifest_artifact_paths(
    manifest_path: Path, artifact_paths: Iterable[Path]
) -> None:
    """Fail before expensive work when an artifact is outside the run directory."""

    for path in artifact_paths:
        _manifest_path(manifest_path, path)


def resolve_manifest_artifact(manifest_path: Path, entry: dict[str, Any]) -> Path:
    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise BackupIOError("Manifest artifact has no path")
    path = Path(raw_path).expanduser()
    if path.is_absolute() or ".." in path.parts:
        raise BackupIOError("Manifest artifact path must be run-directory-relative")
    manifest_dir = manifest_path.expanduser().resolve().parent
    resolved = (manifest_dir / path).resolve()
    try:
        resolved.relative_to(manifest_dir)
    except ValueError:
        raise BackupIOError("Manifest artifact path escapes the run directory") from None
    return resolved


def update_manifest(
    manifest_path: Path,
    *,
    command: str,
    artifacts: Iterable[tuple[str, Path]],
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge command outputs into one hash-bound, run-directory-relative manifest."""

    if manifest_path.is_symlink():
        raise BackupIOError("Run manifest itself must not be a symlink")
    artifact_items = list(artifacts)
    artifact_names = [name for name, _ in artifact_items]
    if len(set(artifact_names)) != len(artifact_names):
        raise BackupIOError("A command supplied duplicate manifest artifact roles")
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupIOError(f"Cannot read run manifest {manifest_path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise BackupIOError("Run manifest must be a JSON object")
        if manifest.get("format") != MANIFEST_FORMAT:
            raise BackupIOError("Run manifest format is not supported")
    else:
        manifest = {
            "format": MANIFEST_FORMAT,
            "formatVersion": FORMAT_VERSION,
            "toolVersion": TOOL_VERSION,
            "profile": PROFILE,
            "runId": str(uuid.uuid4()),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "liveRestoreBlocked": True,
            "artifacts": {},
            "commands": [],
        }

    if manifest.get("formatVersion") != FORMAT_VERSION:
        raise BackupIOError("Run manifest formatVersion is not supported")
    if manifest.get("toolVersion") != TOOL_VERSION:
        raise BackupIOError("Run manifest toolVersion is not supported")
    if manifest.get("profile") != PROFILE:
        raise BackupIOError("Run manifest profile is not supported")
    try:
        uuid.UUID(str(manifest.get("runId")))
    except (ValueError, AttributeError) as exc:
        raise BackupIOError("Run manifest runId is not a UUID") from exc
    if manifest.get("liveRestoreBlocked") is not True:
        raise BackupIOError("Run manifest must keep liveRestoreBlocked=true")
    if manifest_path.exists():
        _, drift_errors = verify_manifest_hashes(manifest_path)
        if drift_errors:
            raise BackupIOError(
                "Refusing to extend a drifted run manifest: " + "; ".join(drift_errors)
            )

    artifact_table = manifest.setdefault("artifacts", {})
    if not isinstance(artifact_table, dict):
        raise BackupIOError("Run manifest artifacts must be an object")
    recorded_names: list[str] = []
    changed = False
    for name, path in artifact_items:
        if not path.is_file():
            raise BackupIOError(f"Cannot record missing artifact {name}: {path}")
        if path.expanduser().resolve() == manifest_path.expanduser().resolve():
            raise BackupIOError("Run manifest cannot record itself as an artifact")
        new_entry = {
            "path": _manifest_path(manifest_path, path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        previous = artifact_table.get(name)
        if previous is not None and previous != new_entry:
            raise BackupIOError(
                f"Refusing to replace manifest artifact {name} with conflicting content"
            )
        if previous is None:
            artifact_table[name] = new_entry
            changed = True
        recorded_names.append(name)
    if state:
        run_state = manifest.setdefault("state", {})
        if not isinstance(run_state, dict):
            raise BackupIOError("Run manifest state must be an object")
        for key, value in state.items():
            if key in run_state and run_state[key] != value:
                raise BackupIOError(
                    f"Refusing to replace conflicting run manifest state: {key}"
                )
            if key not in run_state:
                run_state[key] = value
                changed = True
    commands = manifest.setdefault("commands", [])
    if not isinstance(commands, list):
        raise BackupIOError("Run manifest commands must be an array")
    command_signature = {
        "command": command,
        "recordedArtifacts": recorded_names,
    }
    already_recorded = any(
        isinstance(item, dict)
        and item.get("command") == command_signature["command"]
        and item.get("recordedArtifacts") == command_signature["recordedArtifacts"]
        for item in commands
    )
    if not already_recorded:
        commands.append(
            {
                **command_signature,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        changed = True
    if not changed:
        return manifest
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.", suffix=".tmp", dir=manifest_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, manifest_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return manifest


def verify_manifest_hashes(manifest_path: Path) -> tuple[dict[str, Any], list[str]]:
    if manifest_path.is_symlink():
        raise BackupIOError("Run manifest itself must not be a symlink")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupIOError(f"Cannot read run manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BackupIOError("Run manifest must be a JSON object")
    errors: list[str] = []
    if manifest.get("format") != MANIFEST_FORMAT:
        errors.append("unsupported run manifest format")
    if manifest.get("formatVersion") != FORMAT_VERSION:
        errors.append("unsupported run manifest formatVersion")
    if manifest.get("toolVersion") != TOOL_VERSION:
        errors.append("unsupported run manifest toolVersion")
    if manifest.get("profile") != PROFILE:
        errors.append("unsupported run manifest profile")
    try:
        uuid.UUID(str(manifest.get("runId")))
    except (ValueError, AttributeError):
        errors.append("run manifest runId is not a UUID")
    if manifest.get("liveRestoreBlocked") is not True:
        errors.append("run manifest must keep liveRestoreBlocked=true")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return manifest, errors + ["run manifest artifacts must be an object"]
    for name, entry in artifacts.items():
        if not isinstance(entry, dict):
            errors.append(f"manifest artifact {name} must be an object")
            continue
        try:
            path = resolve_manifest_artifact(manifest_path, entry)
        except BackupIOError as exc:
            errors.append(f"manifest artifact {name}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"manifest artifact {name} is missing: {path}")
            continue
        actual = sha256_file(path)
        if entry.get("sha256") != actual:
            errors.append(f"manifest artifact {name} SHA-256 mismatch")
        if entry.get("bytes") != path.stat().st_size:
            errors.append(f"manifest artifact {name} byte-size mismatch")
    return manifest, errors
