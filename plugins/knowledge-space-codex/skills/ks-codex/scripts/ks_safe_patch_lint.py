#!/usr/bin/env python3
"""Offline linter for KS safe patch plans.

The tool does not call KS and does not execute a plan. It classifies operations,
checks basic safety metadata, and reports which execution gate would be required.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ks_readback_checks import validate_readback_checks
from ks_safe_files import SafePathError, strict_json_loads
from ks_secret_safety import (
    is_sensitive_key,
    redact_text,
    sensitive_value_paths,
    text_contains_secret,
)

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
RUNTIME_PAYLOAD_ENV_RE = re.compile(r"^KS_RUNTIME_PAYLOAD_[A-Z0-9_]+$")
CONCRETE_BEARER_RE = re.compile(r"Bearer\s+(?!<token>)(?!<redacted>)[A-Za-z0-9._~+/=-]{16,}", re.I)
PRIVATE_KEY_RE = re.compile(
    r"BEGIN (?:ENCRYPTED )?(?:(?:OPENSSH|RSA|EC|DSA) )?PRIVATE KEY",
    re.I,
)
PLACEHOLDER_VALUES = {"", "<redacted>", "<password>", "<token>", "<secret>", "<cookie>", "...", None}
SOURCE_CONTEXT_KEYS = {"source", "sources", "connectionparam", "connectionparams", "connection", "connections"}
SOURCE_RUNTIME_VALUE_KEYS = {"host", "login", "username", "dbname", "database", "url", "uri", "productname"}

EXTERNAL_RUNTIME_ENDPOINTS = (
    "/integrator/integrate",
    "/integrator/integrate-modular",
    "/integrator/check-connection",
    "/integrator/connect",
    "/integrator/source-update-password",
    "/integrator/get-db-fields",
    "/integrator/get-fields-by-source-operation",
    "/integrator/get-fields-by-table",
    "/integrator/get-source-operations-fields",
    "/integrator/get-custom-query-db-fields",
    "/integrator/get-custom-query-results",
    "/integration-table/refresh-data",
    "/integration-table/update-data",
    "/integration-table/export-data",
    "/processes/start",
    "/processes/run",
    "/tasks/complete",
    "/tasks/execute",
    "/model/recalculate",
    "/models/recalculate",
    "/backups/save",
    "/files/upload",
    "/files/upload-force",
    "/files/upload-with-confirm",
)
DESTRUCTIVE_MARKERS = (
    "/delete",
    "delete-",
    "-delete",
    "/access",
    "/users/",
    "/roles/",
    "/restore",
    "/import-backup",
    "/load-backup",
    "/backups/load",
)
READ_MARKERS = (
    "/get-",
    "/get_",
    "/get/",
    "/list",
    "get-list",
    "get-by",
    "tree-get-down",
    "search",
    "history",
)
WRITE_MARKERS = (
    "/create",
    "/update",
    "/save",
    "/copy",
    "/move",
    "/add-",
    "create-",
    "update-",
    "save-",
    "copy-",
    "move-",
)
DESTRUCTIVE_TOKENS = {
    "access",
    "clear",
    "delete",
    "drop",
    "overwrite",
    "purge",
    "remove",
    "reset",
    "restore",
    "truncate",
    "wipe",
}
RUNTIME_TOKENS = {
    "calculate",
    "complete",
    "connect",
    "download",
    "execute",
    "export",
    "import",
    "integrate",
    "load",
    "recalculate",
    "refresh",
    "run",
    "send",
    "start",
    "trigger",
    "upload",
}
WRITE_TOKENS = {"add", "copy", "create", "move", "save", "update"}
DESTRUCTIVE_ACTION_STEMS_RU = (
    "восстанов",
    "глобаль",
    "доступ",
    "очист",
    "сброс",
    "стер",
    "удал",
)
RUNTIME_ACTION_STEMS_RU = (
    "загруз",
    "запуск",
    "запуст",
    "интеграц",
    "выгруз",
    "перерасч",
    "пересчит",
    "рассчит",
    "экспорт",
)

MODE_ORDER = {
    "dry_run": 0,
    "execute_project_writes": 1,
    "approved_runtime": 2,
    "approved_destructive": 3,
    "server_maintenance": 4,
}

RISK_REQUIRED_MODE = {
    "read_only": "dry_run",
    "project_write": "execute_project_writes",
    "external_or_runtime": "approved_runtime",
    "destructive_or_global": "approved_destructive",
    "server_or_db": "server_maintenance",
    "unknown": "approved_runtime",
}


def load_plan(path: Path) -> dict[str, Any]:
    try:
        data = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SafePathError) as exc:
        raise SystemExit(f"Plan must be valid, duplicate-free UTF-8 JSON: {exc}") from exc
    if isinstance(data, list):
        return {"operations": data, "metadata": {}}
    if not isinstance(data, dict):
        raise SystemExit("Plan must be a JSON object or array of operations")
    return data


def endpoint_validation_error(value: Any) -> str | None:
    """Return why an API endpoint is not a canonical, local KS API path."""
    if not isinstance(value, str) or not value.strip():
        return "endpoint is missing"
    raw = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return "endpoint contains control characters"
    if not raw.startswith("/"):
        return "endpoint must be an absolute API path beginning with /"
    if any(character in raw for character in ("?", "#", "\\", "%")):
        return "endpoint must not contain query, fragment, backslash, or percent encoding"
    endpoint = raw[4:] if raw.startswith("/api/") else raw
    if endpoint in {"", "/", "/api"}:
        return "endpoint must name a concrete API operation"
    if "//" in endpoint:
        return "endpoint contains a repeated slash"
    if any(part in {".", ".."} for part in endpoint.split("/")):
        return "endpoint contains a dot path segment"
    canonical_candidate = endpoint[:-1] if endpoint.endswith("/") else endpoint
    if not re.fullmatch(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", canonical_candidate):
        return "endpoint contains non-canonical path characters"
    return None


def norm_endpoint(value: Any) -> str:
    if endpoint_validation_error(value):
        return ""
    endpoint = value.strip()
    if endpoint.startswith("/api/"):
        endpoint = endpoint[4:]
    if endpoint.endswith("/"):
        endpoint = endpoint[:-1]
    return endpoint


def require_canonical_endpoint(value: Any, *, label: str = "endpoint") -> str:
    error = endpoint_validation_error(value)
    if error:
        raise RuntimeError(f"{label}: {error}")
    return norm_endpoint(value)


def normalize_stand_url(value: Any) -> str | None:
    """Normalize a plan/client URL while preserving the exact KS API base path."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or value.strip().startswith("<")
        or "?" in value
        or "#" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in parsed.path
        or "%" in parsed.path
        or ";" in parsed.path
        or "//" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or any(character.isspace() for character in parsed.path)
    ):
        return None
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _declared_plan_values(
    plan: dict[str, Any],
    metadata_keys: tuple[str, ...],
    top_level_keys: tuple[str, ...],
) -> list[tuple[str, Any]]:
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    declared: list[tuple[str, Any]] = []
    for key in metadata_keys:
        if key in metadata:
            declared.append((f"metadata.{key}", metadata.get(key)))
    for key in top_level_keys:
        if key in plan:
            declared.append((key, plan.get(key)))
    return declared


def plan_binding_errors(plan: dict[str, Any]) -> list[str]:
    """Validate every declared target alias instead of silently choosing one."""
    errors: list[str] = []
    project_values = _declared_plan_values(
        plan,
        ("targetProjectUuid", "projectUuid"),
        ("targetProjectUuid", "projectUuid"),
    )
    if not project_values:
        errors.append("Plan metadata.targetProjectUuid/projectUuid is required")
    else:
        valid_projects: list[str] = []
        for label, value in project_values:
            if not isinstance(value, str) or not UUID_RE.fullmatch(value):
                errors.append(f"Plan {label} must be a UUID-shaped value")
            else:
                valid_projects.append(value.lower())
        if len(set(valid_projects)) > 1:
            errors.append("Plan project UUID aliases conflict")

    stand_values = _declared_plan_values(
        plan,
        ("baseUrl", "stand"),
        ("baseUrl", "stand"),
    )
    if not stand_values:
        errors.append("Plan metadata.baseUrl/stand must be an explicit http(s) KS stand URL")
    else:
        valid_stands: list[str] = []
        for label, value in stand_values:
            normalized = normalize_stand_url(value)
            if normalized is None:
                errors.append(f"Plan {label} must be an explicit http(s) KS stand URL without credentials, query, or fragment")
            else:
                valid_stands.append(normalized)
        if len(set(valid_stands)) > 1:
            errors.append("Plan stand URL aliases conflict")
    return errors


def plan_project_uuid(plan: dict[str, Any]) -> str | None:
    declared = _declared_plan_values(
        plan,
        ("targetProjectUuid", "projectUuid"),
        ("targetProjectUuid", "projectUuid"),
    )
    values = [
        value.lower()
        for _label, value in declared
        if isinstance(value, str) and UUID_RE.fullmatch(value)
    ]
    if len(values) != len(declared) or not values or len(set(values)) != 1:
        return None
    return values[0]


def plan_stand_url(plan: dict[str, Any]) -> str | None:
    declared = _declared_plan_values(
        plan,
        ("baseUrl", "stand"),
        ("baseUrl", "stand"),
    )
    values = [normalize_stand_url(value) for _label, value in declared]
    if not values or any(value is None for value in values):
        return None
    normalized = [value for value in values if value is not None]
    return normalized[0] if len(set(normalized)) == 1 else None


def classify_operation(operation: dict[str, Any]) -> str:
    channel = str(operation.get("channel") or operation.get("transport") or "api").lower()
    endpoint = norm_endpoint(operation.get("endpoint"))
    lower = endpoint.lower()
    action = " ".join(
        str(operation.get(key) or "")
        for key in ("action", "summary", "expectedEffect")
    ).lower()
    action_tokens = {token for token in re.split(r"[^a-z0-9а-яё]+", action) if token}

    if channel not in {"api", "official_api", "http"}:
        return "server_or_db"
    if lower.startswith(("ssh:", "db:", "sql:", "docker:", "file:")):
        return "server_or_db"
    if not lower:
        return "unknown"
    tokens = {token for token in re.split(r"[/_-]+", lower) if token}
    if action_tokens.intersection(DESTRUCTIVE_TOKENS | {"global"}) or any(
        stem in action for stem in DESTRUCTIVE_ACTION_STEMS_RU
    ):
        return "destructive_or_global"
    if "backup" in action_tokens and action_tokens.intersection({"import", "load", "restore"}):
        return "destructive_or_global"
    if any(marker in lower for marker in DESTRUCTIVE_MARKERS):
        return "destructive_or_global"
    if tokens.intersection(DESTRUCTIVE_TOKENS):
        return "destructive_or_global"
    if lower.startswith("/backups/") and "load" in tokens:
        return "destructive_or_global"
    if lower.startswith("/projects/") and tokens.intersection(WRITE_TOKENS | DESTRUCTIVE_TOKENS):
        return "destructive_or_global"
    if lower.startswith("/imports/"):
        if tokens.intersection({"delete", "load", "remove", "restore"}):
            return "destructive_or_global"
        return "external_or_runtime"
    if lower in EXTERNAL_RUNTIME_ENDPOINTS:
        return "external_or_runtime"
    if action_tokens.intersection(RUNTIME_TOKENS) or any(
        stem in action for stem in RUNTIME_ACTION_STEMS_RU
    ):
        return "external_or_runtime"
    if any(word in action for word in ("run integration", "start process", "complete task", "check connection", "refresh integration", "export data", "import data")):
        return "external_or_runtime"
    if tokens.intersection(RUNTIME_TOKENS):
        return "external_or_runtime"
    if tokens.intersection(WRITE_TOKENS) or any(marker in lower for marker in WRITE_MARKERS) or endpoint in {"/data/save"}:
        return "project_write"
    if lower.startswith("/backups/") or lower.startswith("/files/upload"):
        return "unknown"
    if any(marker in lower for marker in READ_MARKERS):
        return "read_only"
    return "unknown"


NESTED_ENDPOINT_GROUPS = (
    ("readBefore", "preRead", "currentState"),
    ("readBack", "verification", "verify"),
)


def nested_read_endpoint_errors(operation: dict[str, Any]) -> list[str]:
    """Require every declared before/after endpoint to be canonical read-only."""
    errors: list[str] = []
    for aliases in NESTED_ENDPOINT_GROUPS:
        declared = [name for name in aliases if name in operation]
        if len(declared) > 1:
            errors.append(
                f"conflicting nested endpoint aliases declared: {', '.join(declared)}"
            )
        for name in declared:
            block = operation.get(name)
            if not isinstance(block, dict):
                errors.append(f"{name} must be an endpoint object")
                continue
            payload_error = payload_source_error(block, required=False, label=f"{name}")
            if payload_error:
                errors.append(payload_error)
            endpoint_error = endpoint_validation_error(block.get("endpoint"))
            if endpoint_error:
                errors.append(f"{name}: {endpoint_error}")
                continue
            nested_risk = classify_operation({"endpoint": block.get("endpoint")})
            if nested_risk != "read_only":
                errors.append(
                    f"{name} endpoint must be read_only, got {nested_risk}; "
                    "use a separate exact-approved operation for side effects"
                )
    return errors


def require_read_only_endpoint_block(
    block: Any,
    *,
    label: str,
) -> str:
    """Direct-executor defense for nested read-before/read-back blocks."""
    if not isinstance(block, dict):
        raise RuntimeError(f"{label} must be an endpoint object")
    endpoint = require_canonical_endpoint(block.get("endpoint"), label=f"{label} endpoint")
    nested_risk = classify_operation({"endpoint": endpoint})
    if nested_risk != "read_only":
        raise RuntimeError(
            f"{label} endpoint must be read_only, got {nested_risk}; "
            "use a separate exact-approved operation for side effects"
        )
    return endpoint


def get_operations(plan: dict[str, Any]) -> list[dict[str, Any]]:
    declared = [key for key in ("operations", "patches") if key in plan]
    if len(declared) > 1:
        raise SystemExit("Plan must declare only one of 'operations' or legacy 'patches'")
    operations = plan[declared[0]] if declared else []
    if not isinstance(operations, list):
        label = declared[0] if declared else "operations"
        raise SystemExit(f"Plan field '{label}' must be an array")
    out = []
    seen_ids: set[str] = set()
    for index, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            raise SystemExit(f"Operation #{index} must be an object")
        copied = dict(op)
        copied.setdefault("id", f"op-{index}")
        operation_id = copied.get("id")
        if not isinstance(operation_id, str) or not OPERATION_ID_RE.fullmatch(operation_id):
            raise SystemExit(
                f"Operation #{index} id must match {OPERATION_ID_RE.pattern}"
            )
        normalized_operation_id = operation_id.casefold()
        if normalized_operation_id in seen_ids:
            raise SystemExit("Operation id is duplicated")
        seen_ids.add(normalized_operation_id)
        out.append(copied)
    return out


def plan_mode_binding_errors(plan: dict[str, Any]) -> list[str]:
    """Reject invalid or conflicting mode aliases instead of truthy fallback."""
    errors: list[str] = []
    metadata_value = plan.get("metadata")
    if "metadata" in plan and not isinstance(metadata_value, dict):
        errors.append("Plan metadata must be an object")
    metadata = metadata_value if isinstance(metadata_value, dict) else {}
    declared: list[tuple[str, Any]] = []
    if "mode" in metadata:
        declared.append(("metadata.mode", metadata.get("mode")))
    if "mode" in plan:
        declared.append(("mode", plan.get("mode")))
    valid: list[str] = []
    for label, value in declared:
        if not isinstance(value, str) or value not in MODE_ORDER:
            errors.append(f"Plan {label} must be one of: {', '.join(MODE_ORDER)}")
        else:
            valid.append(value)
    if len(set(valid)) > 1:
        errors.append("Plan mode aliases conflict")
    return errors


def resolved_plan_mode(plan: dict[str, Any]) -> str:
    if plan_mode_binding_errors(plan):
        return "dry_run"
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    if "mode" in metadata:
        return metadata["mode"]
    if "mode" in plan:
        return plan["mode"]
    return "dry_run"


def require_safe_operation_id(operation: dict[str, Any]) -> str:
    operation_id = operation.get("id")
    if not isinstance(operation_id, str) or not OPERATION_ID_RE.fullmatch(operation_id):
        raise RuntimeError(
            f"operation id must match {OPERATION_ID_RE.pattern}"
        )
    return operation_id


def execution_readiness_error(operation: dict[str, Any]) -> str | None:
    if "executionReady" not in operation:
        return None
    value = operation.get("executionReady")
    if value is False:
        return "operation is an explicit non-executable draft (executionReady=false)"
    if value is not True:
        return "executionReady must be a JSON boolean when declared"
    return None


def payload_env_definition_errors(operation: dict[str, Any]) -> list[str]:
    """Allow only purpose-created runtime payload variables, never KS auth creds."""
    if "payloadEnv" not in operation:
        return []
    value = operation.get("payloadEnv")
    if not isinstance(value, list) or not value:
        return ["payloadEnv must be a non-empty list of {path, env} objects"]
    errors: list[str] = []
    seen_paths: set[str] = set()
    for index, spec in enumerate(value, start=1):
        if not isinstance(spec, dict):
            errors.append(f"payloadEnv item #{index} must be an object")
            continue
        path = spec.get("path")
        env_name = spec.get("env")
        if not isinstance(path, str) or not path or any(
            part in {"", ".", ".."} for part in path.split(".")
        ):
            errors.append(f"payloadEnv item #{index} has an invalid exact payload path")
        elif path in seen_paths:
            errors.append(f"payloadEnv path is duplicated: {path}")
        else:
            seen_paths.add(path)
        if not isinstance(env_name, str) or not RUNTIME_PAYLOAD_ENV_RE.fullmatch(env_name):
            errors.append(
                f"payloadEnv item #{index} env must use the dedicated "
                "KS_RUNTIME_PAYLOAD_* namespace"
            )
    if classify_operation(operation) != "external_or_runtime":
        errors.append("payloadEnv is only supported for external_or_runtime operations")
    return errors


def payload_env_declared_paths(operation: dict[str, Any]) -> set[tuple[str, ...]]:
    value = operation.get("payloadEnv")
    if not isinstance(value, list):
        return set()
    paths: set[tuple[str, ...]] = set()
    for spec in value:
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
            continue
        raw = spec["path"]
        if raw and all(part not in {"", ".", ".."} for part in raw.split(".")):
            paths.add(tuple(raw.split(".")))
    return paths


def sensitive_field_paths(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    return sensitive_value_paths(value, path)


def _normalized_payload_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def runtime_payload_env_allowed_paths(
    value: Any,
    path: tuple[str, ...] = (),
    *,
    source_context: bool = False,
) -> set[tuple[str, ...]]:
    """Allow runtime injection only into credential/source-connection fields."""
    allowed = set(sensitive_value_paths(value, path))
    if isinstance(value, dict):
        current_source = source_context or any(
            _normalized_payload_key(key) in SOURCE_CONTEXT_KEYS for key in value
        )
        for key, item in value.items():
            current = (*path, str(key))
            if current_source and _normalized_payload_key(key) in SOURCE_RUNTIME_VALUE_KEYS:
                allowed.add(current)
            allowed.update(
                runtime_payload_env_allowed_paths(
                    item,
                    current,
                    source_context=current_source,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            allowed.update(
                runtime_payload_env_allowed_paths(
                    item,
                    (*path, str(index)),
                    source_context=source_context,
                )
            )
    return allowed


def payload_env_source_errors(operation: dict[str, Any], payload: Any) -> list[str]:
    declared = payload_env_declared_paths(operation)
    allowed = runtime_payload_env_allowed_paths(payload)
    return [
        f"payloadEnv path {'.'.join(path)} is not a credential/source-connection field"
        for path in sorted(declared - allowed)
    ]


def executable_sensitive_payload_errors(
    operation: dict[str, Any],
    risk: str,
) -> list[str]:
    payload = operation.get("payload")
    if not isinstance(payload, (dict, list)):
        return []
    sensitive_paths = sensitive_field_paths(payload)
    if not sensitive_paths:
        return []
    if risk == "external_or_runtime":
        allowed = payload_env_declared_paths(operation)
        return [
            f"sensitive runtime payload field {'.'.join(path)} requires an exact payloadEnv mapping"
            for path in sensitive_paths
            if path not in allowed
        ]
    return [
        f"{risk} payload must not contain sensitive field {'.'.join(path)}"
        for path in sensitive_paths
    ]


def _normalized_scope_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def payload_project_scope_errors(
    value: Any,
    expected_project_uuid: str | None,
    *,
    label: str = "payload",
    path: tuple[str, ...] = (),
) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            current = (*path, str(key))
            normalized_key = _normalized_scope_key(key)
            if normalized_key.endswith("projectuuid") or normalized_key.endswith("projectuuids"):
                declared_values = item if isinstance(item, list) else [item]
                if (
                    expected_project_uuid is None
                    or not declared_values
                    or any(
                        not isinstance(declared, str)
                        or not UUID_RE.fullmatch(declared)
                        or declared.lower() != expected_project_uuid.lower()
                        for declared in declared_values
                    )
                ):
                    errors.append(
                        f"{label} project scope at {'.'.join(current)} differs from the exact target project"
                    )
            errors.extend(
                payload_project_scope_errors(
                    item,
                    expected_project_uuid,
                    label=label,
                    path=current,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(
                payload_project_scope_errors(
                    item,
                    expected_project_uuid,
                    label=label,
                    path=(*path, str(index)),
                )
            )
    return errors


def operation_payload_project_scope_errors(
    operation: dict[str, Any],
    expected_project_uuid: str | None,
) -> list[str]:
    errors: list[str] = []
    if "payload" in operation:
        errors.extend(
            payload_project_scope_errors(
                operation.get("payload"),
                expected_project_uuid,
            )
        )
    for aliases in NESTED_ENDPOINT_GROUPS:
        for name in aliases:
            block = operation.get(name)
            if isinstance(block, dict) and "payload" in block:
                errors.extend(
                    payload_project_scope_errors(
                        block.get("payload"),
                        expected_project_uuid,
                        label=f"{name} payload",
                    )
                )
    return errors


def _top_level_uuid_values(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    return [
        value
        for key, value in payload.items()
        if _normalized_scope_key(key) == "uuid"
    ]


def single_entity_target_errors(
    operation: dict[str, Any],
    payload: Any,
    *,
    nested_requests: list[tuple[str, str, Any]] | None = None,
) -> list[str]:
    """Bind the mutation payload and get-by-id verification to one reviewed UUID."""
    errors: list[str] = []
    if operation.get("targetStrategy", "single_entity") != "single_entity":
        errors.append("only targetStrategy=single_entity is executable in the guarded flow")
        return errors
    entity_uuid = operation.get("entityUuid")
    if not isinstance(entity_uuid, str) or not UUID_RE.fullmatch(entity_uuid):
        errors.append("single-entity execution requires a UUID-shaped entityUuid")
        return errors
    main_values = _top_level_uuid_values(payload)
    if not main_values:
        errors.append("single-entity mutation payload must declare top-level UUID/uuid")
    elif any(
        not isinstance(value, str)
        or not UUID_RE.fullmatch(value)
        or value.lower() != entity_uuid.lower()
        for value in main_values
    ):
        errors.append("mutation payload UUID/uuid must exactly match entityUuid")
    elif len({value.lower() for value in main_values if isinstance(value, str)}) > 1:
        errors.append("mutation payload UUID aliases conflict")

    for label, endpoint, nested_payload in nested_requests or []:
        if not endpoint.endswith("/get-by-id"):
            continue
        values = _top_level_uuid_values(nested_payload)
        if not values or any(
            not isinstance(value, str)
            or not UUID_RE.fullmatch(value)
            or value.lower() != entity_uuid.lower()
            for value in values
        ):
            errors.append(f"{label} get-by-id UUID/uuid must exactly match entityUuid")
    return errors


def walk(value: Any, path: tuple[str, ...] = ()):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, (*path, str(index)))


def is_placeholder_value(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value in PLACEHOLDER_VALUES
    )


def is_unresolved_placeholder_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return (
        stripped == "..."
        or (stripped.startswith("<") and stripped.endswith(">"))
        or (stripped.startswith("{{") and stripped.endswith("}}"))
        or (stripped.startswith("${") and stripped.endswith("}"))
    )


def unresolved_placeholder_paths(
    value: Any,
    path: tuple[str, ...] = (),
    *,
    ignored_paths: set[tuple[str, ...]] | None = None,
) -> list[tuple[str, ...]]:
    ignored_paths = ignored_paths or set()
    if path in ignored_paths:
        return []
    if is_unresolved_placeholder_value(value):
        return [path]
    paths: list[tuple[str, ...]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            current = (*path, str(key))
            paths.extend(
                unresolved_placeholder_paths(
                    item,
                    current,
                    ignored_paths=ignored_paths,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            current = (*path, str(index))
            paths.extend(
                unresolved_placeholder_paths(
                    item,
                    current,
                    ignored_paths=ignored_paths,
                )
            )
    return paths


def execution_placeholder_errors(
    operation: dict[str, Any],
    risk: str,
) -> list[str]:
    errors: list[str] = []
    ignored_payload_paths = (
        payload_env_declared_paths(operation)
        if risk == "external_or_runtime"
        else set()
    )
    if "payload" in operation:
        for path in unresolved_placeholder_paths(
            operation.get("payload"),
            ignored_paths=ignored_payload_paths,
        ):
            errors.append(
                f"unresolved payload placeholder at {'.'.join(path) or '<root>'}"
            )
    for aliases in NESTED_ENDPOINT_GROUPS:
        for name in aliases:
            block = operation.get(name)
            if isinstance(block, dict) and "payload" in block:
                for path in unresolved_placeholder_paths(block.get("payload")):
                    errors.append(
                        f"unresolved {name} payload placeholder at "
                        f"{'.'.join(path) or '<root>'}"
                    )
    for field in ("entityUuid", "expectedEffect"):
        if field in operation and is_unresolved_placeholder_value(operation.get(field)):
            errors.append(f"{field} is still an unresolved placeholder")
    waiver = operation.get("verificationWaiver")
    waiver_reason = waiver.get("reason") if isinstance(waiver, dict) else waiver
    if waiver is not None and (
        not isinstance(waiver_reason, str)
        or not waiver_reason.strip()
        or is_unresolved_placeholder_value(waiver_reason)
    ):
        errors.append("verificationWaiver reason must be concrete, not a placeholder")
    read_back = get_readback(operation)
    if isinstance(read_back, dict) and "checks" in read_back:
        for path in unresolved_placeholder_paths(read_back.get("checks")):
            errors.append(
                f"unresolved readBack check placeholder at {'.'.join(path) or '<root>'}"
            )
    return errors


def secret_findings(operation: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    sensitive_paths = set(sensitive_value_paths(operation))
    for path, value in walk(operation):
        key = path[-1] if path else ""
        if isinstance(value, str):
            if text_contains_secret(value) or CONCRETE_BEARER_RE.search(value) or PRIVATE_KEY_RE.search(value):
                findings.append(f"secret-like string at {'.'.join(path)}")
            if path in sensitive_paths and not is_placeholder_value(value):
                findings.append(f"unredacted sensitive field {'.'.join(path)}")
        elif path in sensitive_paths and not is_placeholder_value(value):
            findings.append(f"unredacted sensitive field {'.'.join(path)}")
    return findings


def approval_matches(operation: dict[str, Any], approval: dict[str, Any]) -> bool:
    if approval.get("userApproved") is not True:
        return False
    op_id = str(operation.get("id"))
    endpoint = norm_endpoint(operation.get("endpoint"))
    raw_ids = approval.get("approvedOperationIds")
    raw_endpoints = approval.get("approvedEndpoints")
    raw_exact = approval.get("exactApprovedActions")
    approved_ids = set(raw_ids) if isinstance(raw_ids, list) and all(isinstance(v, str) for v in raw_ids) else set()
    approved_endpoints = (
        {norm_endpoint(v) for v in raw_endpoints}
        if isinstance(raw_endpoints, list) and all(isinstance(v, str) for v in raw_endpoints)
        else set()
    )
    exact = set(raw_exact) if isinstance(raw_exact, list) and all(isinstance(v, str) for v in raw_exact) else set()
    return op_id in approved_ids or endpoint in approved_endpoints or op_id in exact


def has_readback(operation: dict[str, Any]) -> bool:
    value = operation.get("readBack") or operation.get("verification") or operation.get("verify")
    return isinstance(value, (dict, list, str)) and bool(value)


def has_declared_payload(operation: dict[str, Any]) -> bool:
    """Require write/runtime payloads to be explicit, including an intentional {}."""
    return "payload" in operation or "payloadPath" in operation


def payload_source_error(
    value: Any,
    *,
    required: bool,
    label: str = "operation",
) -> str | None:
    if not isinstance(value, dict):
        return f"{label} must be an object"
    declared = [key for key in ("payload", "payloadPath") if key in value]
    if len(declared) > 1:
        return f"{label} must declare only one of payload or payloadPath"
    if required and not declared:
        return (
            f"{label} has no explicit payload/payloadPath; "
            "a payloadBuildHint is not executable"
        )
    if "payloadPath" in value:
        raw = value.get("payloadPath")
        if not isinstance(raw, str) or not raw.strip():
            return f"{label} payloadPath must be a non-empty relative path"
        path = Path(raw)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            return f"{label} payloadPath must stay below the plan directory"
    return None


def get_readback(operation: dict[str, Any]) -> Any:
    return operation.get("readBack") or operation.get("verification") or operation.get("verify")


def readback_checks_error(operation: dict[str, Any]) -> str | None:
    value = get_readback(operation)
    if not isinstance(value, dict):
        return "readBack/verification must be an endpoint object with machine checks"
    errors = validate_readback_checks(value.get("checks"))
    if errors:
        return f"invalid readBack checks: {errors[0]}"
    return None


def readback_definition_error(operation: dict[str, Any]) -> str | None:
    """Return why a declared read-back cannot be executed by bundled runners."""
    value = get_readback(operation)
    if value is None:
        return "readBack/verification is missing"
    if not isinstance(value, dict):
        return "readBack/verification must be an endpoint object, not descriptive text"
    endpoint_error = endpoint_validation_error(value.get("endpoint"))
    if endpoint_error:
        return f"readBack/verification: {endpoint_error}"
    nested_risk = classify_operation({"endpoint": value.get("endpoint")})
    if nested_risk != "read_only":
        return (
            f"readBack/verification endpoint must be read_only, got {nested_risk}; "
            "use a separate exact-approved operation for side effects"
        )
    return None


def valid_verification_waiver(operation: dict[str, Any]) -> bool:
    """A runtime waiver must contain an explicit human-readable reason."""
    value = operation.get("verificationWaiver")
    if isinstance(value, str):
        return bool(value.strip()) and not is_unresolved_placeholder_value(value)
    if isinstance(value, dict):
        reason = value.get("reason")
        return (
            isinstance(reason, str)
            and bool(reason.strip())
            and not is_unresolved_placeholder_value(reason)
        )
    return False


def has_readbefore(operation: dict[str, Any]) -> bool:
    value = operation.get("readBefore") or operation.get("preRead") or operation.get("currentState")
    return isinstance(value, (dict, list, str)) and bool(value)


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |" for row in rows[:1]]
    lines.append("| " + " | ".join("-" * widths[i] for i in range(len(rows[0]))) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |")
    return "\n".join(lines)


def lint(plan: dict[str, Any]) -> tuple[str, int]:
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    approval = plan.get("approval") if isinstance(plan.get("approval"), dict) else {}
    mode = resolved_plan_mode(plan)
    project_uuid = plan_project_uuid(plan)
    stand_url = plan_stand_url(plan)
    operations = get_operations(plan)

    rows = [["ID", "Endpoint", "Risk", "Required mode", "Gate"]]
    findings: list[str] = []
    blocking = 0
    counts = Counter()

    for finding in secret_findings(plan):
        findings.append(f"Plan: {finding}")
        blocking += 1

    for error in plan_mode_binding_errors(plan):
        findings.append(error)
        blocking += 1

    for error in plan_binding_errors(plan):
        findings.append(error)
        blocking += 1

    if "userApproved" in approval and not isinstance(approval.get("userApproved"), bool):
        findings.append("approval.userApproved must be a JSON boolean")
        blocking += 1
    for field in ("approvedOperationIds", "approvedEndpoints", "exactApprovedActions"):
        value = approval.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            findings.append(f"approval.{field} must be a string array")
            blocking += 1

    for op in operations:
        risk = classify_operation(op)
        counts[risk] += 1
        required = RISK_REQUIRED_MODE[risk]
        endpoint_error = endpoint_validation_error(op.get("endpoint"))
        endpoint = norm_endpoint(op.get("endpoint")) if endpoint_error is None else "<invalid/redacted>"
        op_id = str(op.get("id"))
        gate = "ok for dry-run"

        if endpoint_error:
            findings.append(f"{op_id}: {endpoint_error}")
            blocking += 1

        for nested_error in nested_read_endpoint_errors(op):
            findings.append(f"{op_id}: {nested_error}")
            blocking += 1

        payload_error = payload_source_error(
            op,
            required=risk in {"project_write", "external_or_runtime", "destructive_or_global"},
        )
        if payload_error:
            findings.append(f"{op_id}: {payload_error}")
            blocking += 1

        declared_op_projects = [
            op.get(key)
            for key in ("projectUuid", "targetProjectUuid")
            if key in op
        ]
        if len({str(value).lower() for value in declared_op_projects}) > 1:
            findings.append(f"{op_id}: operation project UUID aliases conflict")
            blocking += 1
        for value in declared_op_projects:
            if not isinstance(value, str) or not UUID_RE.fullmatch(value):
                findings.append(f"{op_id}: operation project UUID must be UUID-shaped")
                blocking += 1
        op_project = declared_op_projects[0] if declared_op_projects else project_uuid
        if risk != "server_or_db" and endpoint != "/auth/login" and not op_project:
            findings.append(f"{op_id}: missing targetProjectUuid/projectUuid")
            blocking += 1
        if op_project and isinstance(op_project, str) and op_project.startswith("<"):
            findings.append(f"{op_id}: project UUID is still a placeholder")
            blocking += 1
        if any(
            isinstance(value, str)
            and project_uuid
            and value.lower() != project_uuid
            for value in declared_op_projects
        ):
            findings.append(
                f"{op_id}: operation project UUID differs from plan targetProjectUuid"
            )
            blocking += 1

        readiness_error = execution_readiness_error(op)
        if readiness_error:
            findings.append(f"{op_id}: {readiness_error}")
            blocking += 1

        for error in payload_env_definition_errors(op):
            findings.append(f"{op_id}: {error}")
            blocking += 1
        if "payload" in op:
            for error in payload_env_source_errors(op, op.get("payload")):
                findings.append(f"{op_id}: {error}")
                blocking += 1
        for error in executable_sensitive_payload_errors(op, risk):
            findings.append(f"{op_id}: {error}")
            blocking += 1
        for error in execution_placeholder_errors(op, risk):
            findings.append(f"{op_id}: {error}")
            blocking += 1
        for error in operation_payload_project_scope_errors(op, project_uuid):
            findings.append(f"{op_id}: {error}")
            blocking += 1

        for finding in secret_findings(op):
            findings.append(f"{op_id}: {finding}")
            blocking += 1

        if risk in {"project_write", "external_or_runtime", "destructive_or_global"}:
            waiver_allowed = risk == "external_or_runtime" and valid_verification_waiver(op)
            if not has_readback(op) and not waiver_allowed:
                findings.append(f"{op_id}: {risk} operation has no readBack/verification block")
                blocking += 1
            elif has_readback(op):
                readback_error = readback_definition_error(op)
                if readback_error:
                    findings.append(f"{op_id}: {readback_error}")
                    blocking += 1
            if not waiver_allowed:
                checks_error = readback_checks_error(op)
                if checks_error:
                    findings.append(f"{op_id}: {checks_error}")
                    blocking += 1
            if op.get("verificationWaiver") is not None and not valid_verification_waiver(op):
                findings.append(
                    f"{op_id}: verificationWaiver must be a non-empty reason string or object"
                )
                blocking += 1
        if risk == "project_write" and not has_readbefore(op):
            findings.append(f"{op_id}: project_write operation should include readBefore/preRead/currentState")
        if risk in {"external_or_runtime", "destructive_or_global", "unknown"}:
            if not approval_matches(op, approval):
                gate = "exact approval required before execution"
                if mode != "dry_run":
                    findings.append(f"{op_id}: {risk} requires exact user approval in this mode")
                    blocking += 1
            else:
                gate = "approval recorded"
        if risk == "server_or_db":
            gate = "server-maintenance approval required"
            if mode != "server_maintenance" or not approval.get("userApproved"):
                findings.append(f"{op_id}: server/DB action is outside KS project patching without server_maintenance mode")
                blocking += 1

        if MODE_ORDER[mode] < MODE_ORDER[required] and risk not in {"external_or_runtime", "destructive_or_global", "unknown", "server_or_db"}:
            gate = f"not executable in {mode}"
        elif MODE_ORDER[mode] >= MODE_ORDER[required] and gate == "ok for dry-run":
            gate = "mode allows execution if checklist passes"

        rows.append([op_id, endpoint, risk, required, gate])

    lines = ["# KS Safe Patch Plan Lint", ""]
    lines.append(f"Mode: `{mode}`")
    lines.append(f"Target project: `{project_uuid or '<invalid/redacted>'}`")
    lines.append(f"Target stand: `{stand_url or '<invalid/redacted>'}`")
    lines.append(f"Operations: {len(operations)}")
    lines.append(f"Blocking findings: {blocking}")
    lines.append("")
    lines.append("## Risk Counts")
    lines.append("")
    for risk in ("read_only", "project_write", "external_or_runtime", "destructive_or_global", "server_or_db", "unknown"):
        lines.append(f"- {risk}: {counts[risk]}")
    lines.append("")
    lines.append("## Operations")
    lines.append("")
    lines.append(markdown_table(rows))
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("No blocking findings. This does not execute the plan and does not replace browser/API read-back verification.")
    lines.append("")
    lines.append("## Execution Rule")
    lines.append("")
    lines.append("This linter never calls KS. A valid plan means the operation is structured enough to review; it is not permission to run high-risk actions. Runtime, destructive, or server actions need exact approval for the named operation.")
    return redact_text("\n".join(lines) + "\n"), blocking


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline linter for KS safe patch plans")
    parser.add_argument("plan", type=Path, help="Path to JSON patch plan")
    parser.add_argument("--output", type=Path, help="Write markdown report to this path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when blocking findings exist")
    args = parser.parse_args()

    report, blocking = lint(load_plan(args.plan))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 1 if args.strict and blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
