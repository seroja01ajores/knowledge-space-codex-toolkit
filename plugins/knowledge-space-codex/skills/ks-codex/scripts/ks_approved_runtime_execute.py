#!/usr/bin/env python3
"""Exact-approved executor for KS runtime operations.

This script is for intentional runtime actions: integration runs, connection
checks, integration-table refresh/export/update, BPMS start/complete, and model
recalculation. It is not a general project-write or destructive/server tool.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from ks_api_client import KSAPIError, KSAPIUncertainResultError, KSClient, _redact
from ks_safe_files import (
    SafePathError,
    atomic_write_text,
    preflight_output_file,
    prepare_output_root,
    prepare_output_subdir,
    read_json_relative,
)
from ks_readback_checks import (
    evaluate_readback_checks,
    require_readback_checks,
    validate_readback_checks,
)
from ks_secret_safety import (
    is_sensitive_key,
    redact_text,
    semantic_secret_value_keys,
    sensitive_value_paths,
    text_contains_secret,
)
from ks_safe_patch_lint import (
    MODE_ORDER,
    UUID_RE,
    approval_matches,
    classify_operation,
    endpoint_validation_error,
    executable_sensitive_payload_errors,
    execution_placeholder_errors,
    execution_readiness_error,
    get_operations,
    has_declared_payload,
    is_unresolved_placeholder_value,
    lint,
    load_plan,
    norm_endpoint,
    nested_read_endpoint_errors,
    normalize_stand_url,
    operation_payload_project_scope_errors,
    payload_project_scope_errors,
    payload_env_definition_errors,
    payload_env_source_errors,
    payload_source_error,
    plan_binding_errors,
    plan_project_uuid,
    plan_stand_url,
    plan_mode_binding_errors,
    resolved_plan_mode,
    readback_checks_error,
    readback_definition_error,
    require_canonical_endpoint,
    require_read_only_endpoint_block,
    require_safe_operation_id,
    single_entity_target_errors,
    secret_findings,
    valid_verification_waiver,
)


PLACEHOLDER_VALUES = {"", "<redacted>", "<password>", "<token>", "<secret>", "<cookie>", "...", None}
SOURCE_CONTEXT_KEYS = {"source", "sources", "connectionparam", "connectionparams", "connection", "connections"}
SOURCE_SECRET_KEYS = {"host", "login", "dbname", "database", "url", "uri", "productname"}


class EffectUnknownError(RuntimeError):
    """A runtime side effect may have applied despite an unavailable response."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def lower_key(key: Any) -> str:
    return str(key).replace("_", "").replace("-", "").lower()


def redact_secret_text(value: str, secret_values: tuple[str, ...]) -> str:
    return redact_text(value, secret_values)


def sanitize(value: Any, source_context: bool = False, secret_values: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        next_source = source_context or any(lower_key(key) in SOURCE_CONTEXT_KEYS for key in value)
        out: dict[str, Any] = {}
        semantic_keys = semantic_secret_value_keys(value)
        for key, item in value.items():
            lk = lower_key(key)
            safe_key = redact_secret_text(str(key), secret_values)
            if is_sensitive_key(key) or key in semantic_keys or (next_source and lk in SOURCE_SECRET_KEYS):
                out[safe_key] = "<redacted>"
            else:
                out[safe_key] = sanitize(item, next_source, secret_values)
        return out
    if isinstance(value, list):
        return [sanitize(item, source_context, secret_values) for item in value]
    if isinstance(value, str):
        value = redact_secret_text(value, secret_values)
        if value.count(".") == 2 and len(value) > 80:
            return "<redacted>"
    return value


def client_secret_values(client: KSClient | None) -> tuple[str, ...]:
    if client is None:
        return ()
    return tuple(
        value
        for value in (getattr(client, "password", None), getattr(client, "token", None))
        if isinstance(value, str) and value
    )


def operation_secret_values(
    operation: dict[str, Any],
    client: KSClient | None,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*payload_env_secret_values(operation), *client_secret_values(client))))


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


def payload_secret_findings(
    value: Any,
    label: str,
    *,
    allowed_secret_paths: set[tuple[str, ...]] | None = None,
) -> list[str]:
    findings: list[str] = []
    allowed_secret_paths = allowed_secret_paths or set()
    sensitive_paths = set(sensitive_value_paths(value))
    for path, item in walk(value):
        if path in allowed_secret_paths:
            continue
        if isinstance(item, str) and is_unresolved_placeholder_value(item):
            findings.append(
                f"{label}: unresolved placeholder at {'.'.join(path) or '<root>'}"
            )
        if not path:
            continue
        key = path[-1]
        if isinstance(item, str) and text_contains_secret(item):
            findings.append(f"{label}: secret-like string at {'.'.join(path)}")
        if path in sensitive_paths:
            findings.append(f"{label}: unredacted sensitive field {'.'.join(path)}; use payloadEnv for runtime secrets")
    return findings


def load_payload(operation: dict[str, Any], *, base_dir: Path) -> Any:
    if "payload" in operation and "payloadPath" in operation:
        raise RuntimeError("must declare only one of payload or payloadPath")
    if "payloadPath" in operation:
        return read_json_relative(
            base_dir,
            operation["payloadPath"],
            label="payloadPath",
        )
    if "payload" in operation:
        payload = operation["payload"]
        if isinstance(payload, str) and payload.startswith("<"):
            raise RuntimeError("payload is still a placeholder")
        return deepcopy(payload)
    return {}


def parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for raw in path.split("."):
        if raw == "":
            raise RuntimeError(f"empty payloadEnv path segment in {path!r}")
        parts.append(int(raw) if raw.isdigit() else raw)
    return parts


def set_path(root: Any, path: str, value: Any) -> None:
    parts = parse_path(path)
    current = root
    for part in parts[:-1]:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise RuntimeError(f"payloadEnv path does not exist: {path}")
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise RuntimeError(f"payloadEnv path does not exist: {path}")
            current = current[part]
    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(current, list) or last >= len(current):
            raise RuntimeError(f"payloadEnv path does not exist: {path}")
        current[last] = value
    else:
        if not isinstance(current, dict):
            raise RuntimeError(f"payloadEnv path parent is not an object: {path}")
        current[last] = value


def get_path(root: Any, path: str) -> Any:
    current = root
    for part in parse_path(path):
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise RuntimeError(f"payloadEnv path does not exist: {path}")
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise RuntimeError(f"payloadEnv path does not exist: {path}")
            current = current[part]
    return current


def payload_env_specs(operation: dict[str, Any]) -> list[tuple[str, str]]:
    env_specs = operation.get("payloadEnv") or []
    if not env_specs:
        return []
    validation_errors = payload_env_definition_errors(operation)
    if validation_errors:
        raise RuntimeError(validation_errors[0])
    if not isinstance(env_specs, list):
        raise RuntimeError("payloadEnv must be a list of {path, env} objects")
    parsed: list[tuple[str, str]] = []
    for index, spec in enumerate(env_specs, start=1):
        if not isinstance(spec, dict):
            raise RuntimeError(f"payloadEnv item #{index} must be an object")
        path = spec.get("path")
        env_name = spec.get("env")
        if not isinstance(path, str) or not path:
            raise RuntimeError(f"payloadEnv item #{index} has no path")
        if not isinstance(env_name, str) or not env_name:
            raise RuntimeError(f"payloadEnv item #{index} has no env")
        parse_path(path)
        parsed.append((path, env_name))
    return parsed


def payload_env_paths(operation: dict[str, Any]) -> set[tuple[str, ...]]:
    return {
        tuple(str(part) for part in parse_path(path))
        for path, _env_name in payload_env_specs(operation)
    }


def payload_env_secret_values(operation: dict[str, Any]) -> tuple[str, ...]:
    """Collect injected values only for in-memory redaction; never persist names or values."""
    values: list[str] = []
    try:
        specs = payload_env_specs(operation)
    except RuntimeError:
        return ()
    for _path, env_name in specs:
        value = os.environ.get(env_name)
        if value and value not in values:
            values.append(value)
    return tuple(values)


def apply_payload_env(
    payload: Any,
    operation: dict[str, Any],
    *,
    execute: bool,
    client: KSClient | None = None,
) -> Any:
    specs = payload_env_specs(operation)
    if not specs:
        return payload
    payload = deepcopy(payload)
    source_errors = payload_env_source_errors(operation, payload)
    if source_errors:
        raise RuntimeError(source_errors[0])
    core_credentials = {
        value
        for value in (
            getattr(client, "login_name", None),
            getattr(client, "password", None),
            getattr(client, "token", None),
        )
        if isinstance(value, str) and value
    }
    for path, env_name in specs:
        current_value = get_path(payload, path)
        if not (
            is_placeholder_value(current_value)
            or is_unresolved_placeholder_value(current_value)
        ):
            raise RuntimeError(
                f"payloadEnv source path must contain an explicit placeholder before injection: {path}"
            )
        if execute:
            if env_name not in os.environ:
                raise RuntimeError(f"payloadEnv variable is missing: {env_name}")
            env_value = os.environ[env_name]
            if not env_value.strip() or is_unresolved_placeholder_value(env_value):
                raise RuntimeError(
                    f"payloadEnv variable is empty or unresolved: {env_name}"
                )
            if env_value in core_credentials:
                raise RuntimeError(
                    "payloadEnv value must not reuse a KS authentication credential"
                )
            set_path(payload, path, env_value)
    return payload


def endpoint_payload(
    block: Any,
    *,
    base_dir: Path,
    fallback_uuid: str | None = None,
    expected_project_uuid: str | None = None,
) -> tuple[str, Any]:
    if not isinstance(block, dict):
        raise RuntimeError("endpoint block must be an object")
    endpoint = require_read_only_endpoint_block(block, label="nested endpoint")
    has_payload_source = "payload" in block or "payloadPath" in block
    payload = load_payload(block, base_dir=base_dir)
    if not has_payload_source and fallback_uuid and endpoint.endswith("/get-by-id"):
        payload = {"UUID": fallback_uuid, "uuid": fallback_uuid}
    for finding in payload_secret_findings(payload, "nested endpoint payload"):
        raise RuntimeError(finding)
    scope_errors = payload_project_scope_errors(
        payload,
        expected_project_uuid,
        label="nested endpoint payload",
    )
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    return endpoint, payload


def plan_mode(plan: dict[str, Any]) -> str:
    return resolved_plan_mode(plan)


def operation_gate(operation: dict[str, Any], plan: dict[str, Any], *, execute: bool) -> tuple[str, list[str]]:
    risk = classify_operation(operation)
    mode = plan_mode(plan)
    issues: list[str] = []

    try:
        require_safe_operation_id(operation)
    except RuntimeError as exc:
        issues.append(str(exc))
    issues.extend(plan_mode_binding_errors(plan))
    endpoint_error = endpoint_validation_error(operation.get("endpoint"))
    if endpoint_error:
        issues.append(endpoint_error)
    issues.extend(nested_read_endpoint_errors(operation))
    issues.extend(payload_env_definition_errors(operation))
    if "payload" in operation:
        issues.extend(payload_env_source_errors(operation, operation.get("payload")))
    issues.extend(executable_sensitive_payload_errors(operation, risk))
    issues.extend(execution_placeholder_errors(operation, risk))
    payload_error = payload_source_error(operation, required=False)
    if payload_error:
        issues.append(payload_error)
    if execute:
        issues.extend(plan_binding_errors(plan))
    plan_project = plan_project_uuid(plan)
    plan_stand = plan_stand_url(plan)
    if execute and plan_project is None:
        issues.append("execution requires a UUID-shaped plan targetProjectUuid")
    if execute and plan_stand is None:
        issues.append("execution requires an explicit http(s) plan baseUrl/stand")
    issues.extend(operation_payload_project_scope_errors(operation, plan_project))
    explicit_projects = [
        operation.get(key)
        for key in ("projectUuid", "targetProjectUuid")
        if key in operation
    ]
    if len({str(value).lower() for value in explicit_projects}) > 1:
        issues.append("operation project UUID aliases conflict")
    if any(
        not isinstance(value, str) or not UUID_RE.fullmatch(value)
        for value in explicit_projects
    ):
        issues.append("operation project UUID must be UUID-shaped")
    if any(
        isinstance(value, str)
        and plan_project
        and value.lower() != plan_project
        for value in explicit_projects
    ):
        issues.append("operation project UUID differs from plan targetProjectUuid")
    readiness_error = execution_readiness_error(operation)
    if readiness_error:
        issues.append(readiness_error)

    for finding in secret_findings({key: value for key, value in operation.items() if key != "payloadEnv"}):
        issues.append(finding)

    if risk == "read_only":
        if not execute:
            issues.append("dry-run only; use --execute to call read-only endpoint")
        return risk, issues
    if risk != "external_or_runtime":
        issues.append(f"{risk} belongs to a different flow, not approved-runtime")
        return risk, issues

    if mode != "approved_runtime":
        issues.append("runtime execution requires metadata.mode=approved_runtime")
    if not approval_matches(operation, plan.get("approval") if isinstance(plan.get("approval"), dict) else {}):
        issues.append("runtime execution requires approval.userApproved plus approved operation id/endpoint")
    if not execute:
        issues.append("runtime execution requires --execute")
    if not has_declared_payload(operation):
        issues.append("runtime operation requires an explicit payload or payloadPath")
    has_waiver = valid_verification_waiver(operation)
    readback_error = readback_definition_error(operation)
    if readback_error and not has_waiver:
        issues.append(
            "runtime operation needs an executable readBack/verification endpoint "
            "or a documented verificationWaiver"
        )
    if not has_waiver:
        checks_error = readback_checks_error(operation)
        if checks_error:
            issues.append(checks_error)
    if operation.get("verificationWaiver") is not None and not has_waiver:
        issues.append("verificationWaiver must be a non-empty reason string or {reason: ...}")
    read_back = operation.get("readBack") or operation.get("verification") or operation.get("verify")
    if not operation.get("expectedEffect"):
        issues.append("runtime operation should describe expectedEffect")

    required_level = MODE_ORDER["approved_runtime"]
    if MODE_ORDER.get(mode, 0) < required_level:
        issues.append(f"mode {mode} is lower than required approved_runtime")
    return risk, issues


def write_json(
    out_dir: Path,
    relative_path: str | Path,
    value: Any,
    *,
    secret_values: tuple[str, ...] = (),
) -> Path:
    return atomic_write_text(
        out_dir,
        relative_path,
        json.dumps(sanitize(_redact(value), secret_values=secret_values), ensure_ascii=False, indent=2),
    )


def operation_output_paths(
    operation: dict[str, Any],
    risk: str,
) -> list[Path]:
    operation_id = require_safe_operation_id(operation)
    prefix = Path("operations") / operation_id
    if risk == "read_only":
        return [prefix.with_name(f"{operation_id}_response.json")]
    if risk != "external_or_runtime":
        return []
    paths = [prefix.with_name(f"{operation_id}_runtime_response.json")]
    if any(
        isinstance(operation.get(name), dict)
        for name in ("readBefore", "preRead", "currentState")
    ):
        paths.append(prefix.with_name(f"{operation_id}_read_before.json"))
    read_back = next(
        (
            operation.get(name)
            for name in ("readBack", "verification", "verify")
            if isinstance(operation.get(name), dict)
        ),
        None,
    )
    if isinstance(read_back, dict):
        paths.append(prefix.with_name(f"{operation_id}_read_back.json"))
        if "checks" in read_back:
            paths.append(prefix.with_name(f"{operation_id}_read_back_checks.json"))
    return paths


def preflight_operation_outputs(
    out_dir: Path,
    operation: dict[str, Any],
    risk: str,
) -> None:
    prepare_output_subdir(out_dir, "operations")
    for relative_path in operation_output_paths(operation, risk):
        preflight_output_file(out_dir, relative_path)


def preflight_operation_inputs(
    operation: dict[str, Any],
    risk: str,
    *,
    base_dir: Path,
    expected_project_uuid: str | None,
    client: KSClient | None = None,
) -> None:
    """Validate all local files, payloads, mappings, and identities pre-login."""
    require_safe_operation_id(operation)
    require_canonical_endpoint(operation.get("endpoint"))
    if risk == "read_only":
        payload = load_payload(operation, base_dir=base_dir)
        findings = payload_secret_findings(payload, "payload")
        if findings:
            raise RuntimeError(findings[0])
        scope_errors = payload_project_scope_errors(payload, expected_project_uuid)
        if scope_errors:
            raise RuntimeError(scope_errors[0])
        return
    if risk != "external_or_runtime":
        raise RuntimeError(f"unsupported approved-runtime preflight risk: {risk}")
    errors = [
        *executable_sensitive_payload_errors(operation, "external_or_runtime"),
        *execution_placeholder_errors(operation, "external_or_runtime"),
        *nested_read_endpoint_errors(operation),
        *payload_env_definition_errors(operation),
    ]
    if errors:
        raise RuntimeError(errors[0])
    entity_uuid = operation.get("entityUuid") if isinstance(operation.get("entityUuid"), str) else None
    read_back = next(
        (operation.get(name) for name in ("readBack", "verification", "verify") if name in operation),
        None,
    )
    read_before = next(
        (operation.get(name) for name in ("readBefore", "preRead", "currentState") if name in operation),
        None,
    )
    if not valid_verification_waiver(operation):
        check_errors = validate_readback_checks(
            read_back.get("checks") if isinstance(read_back, dict) else None
        )
        if check_errors:
            raise RuntimeError(f"invalid readBack checks: {check_errors[0]}")
    back_request = (
        endpoint_payload(
            read_back,
            base_dir=base_dir,
            fallback_uuid=entity_uuid,
            expected_project_uuid=expected_project_uuid,
        )
        if isinstance(read_back, dict)
        else None
    )
    before_request = (
        endpoint_payload(
            read_before,
            base_dir=base_dir,
            fallback_uuid=entity_uuid,
            expected_project_uuid=expected_project_uuid,
        )
        if isinstance(read_before, dict)
        else None
    )
    payload = load_payload(operation, base_dir=base_dir)
    payload = apply_payload_env(
        payload,
        operation,
        execute=client is not None,
        client=client,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("runtime payload must be a JSON object")
    findings = payload_secret_findings(
        payload,
        "payload",
        allowed_secret_paths=payload_env_paths(operation),
    )
    if findings:
        raise RuntimeError(findings[0])
    scope_errors = payload_project_scope_errors(payload, expected_project_uuid)
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    if (
        back_request
        and not valid_verification_waiver(operation)
        and ("entityUuid" in operation or "targetStrategy" in operation)
    ):
        identity_requests = [("readBack", back_request[0], back_request[1])]
        if before_request:
            identity_requests.append(("readBefore", before_request[0], before_request[1]))
        identity_errors = single_entity_target_errors(
            operation,
            payload,
            nested_requests=identity_requests,
        )
        if identity_errors:
            raise RuntimeError(identity_errors[0])


def execute_read(client: KSClient, operation: dict[str, Any], *, base_dir: Path, out_dir: Path) -> dict[str, Any]:
    operation_id = require_safe_operation_id(operation)
    endpoint = require_canonical_endpoint(operation.get("endpoint"))
    if classify_operation({"endpoint": endpoint}) != "read_only":
        raise RuntimeError("execute_read received a non-read-only endpoint")
    preflight_operation_outputs(out_dir, operation, "read_only")
    payload = load_payload(operation, base_dir=base_dir)
    for finding in payload_secret_findings(payload, "payload"):
        raise RuntimeError(finding)
    scope_errors = payload_project_scope_errors(
        payload,
        getattr(client, "project_uuid", None),
    )
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    response = client.post(endpoint, payload if isinstance(payload, dict) else {"value": payload}, ok_empty=True)
    path = write_json(
        out_dir,
        Path("operations") / f"{operation_id}_response.json",
        response,
        secret_values=client_secret_values(client),
    )
    return {"status": "executed_read_only", "responsePath": str(path)}


def execute_runtime(client: KSClient, operation: dict[str, Any], *, base_dir: Path, out_dir: Path) -> dict[str, Any]:
    operation_id = require_safe_operation_id(operation)
    main_endpoint = require_canonical_endpoint(operation.get("endpoint"))
    if classify_operation({"endpoint": main_endpoint}) != "external_or_runtime":
        raise RuntimeError("execute_runtime received a non-runtime endpoint")
    execution_errors = [
        *executable_sensitive_payload_errors(operation, "external_or_runtime"),
        *execution_placeholder_errors(operation, "external_or_runtime"),
    ]
    if execution_errors:
        raise RuntimeError(execution_errors[0])
    nested_errors = nested_read_endpoint_errors(operation)
    if nested_errors:
        raise RuntimeError(nested_errors[0])
    payload_env_errors = payload_env_definition_errors(operation)
    if payload_env_errors:
        raise RuntimeError(payload_env_errors[0])
    if "payload" in operation:
        source_errors = payload_env_source_errors(operation, operation.get("payload"))
        if source_errors:
            raise RuntimeError(source_errors[0])
    preflight_operation_outputs(out_dir, operation, "external_or_runtime")
    secret_values = operation_secret_values(operation, client)
    entity_uuid = operation.get("entityUuid") if isinstance(operation.get("entityUuid"), str) else None
    read_back = next(
        (operation.get(name) for name in ("readBack", "verification", "verify") if name in operation),
        None,
    )
    if not valid_verification_waiver(operation):
        check_errors = validate_readback_checks(
            read_back.get("checks") if isinstance(read_back, dict) else None
        )
        if check_errors:
            raise RuntimeError(f"invalid readBack checks: {check_errors[0]}")
    back_request = (
        endpoint_payload(
            read_back,
            base_dir=base_dir,
            fallback_uuid=entity_uuid,
            expected_project_uuid=getattr(client, "project_uuid", None),
        )
        if isinstance(read_back, dict)
        else None
    )
    read_before = next(
        (operation.get(name) for name in ("readBefore", "preRead", "currentState") if name in operation),
        None,
    )
    before_request = (
        endpoint_payload(
            read_before,
            base_dir=base_dir,
            fallback_uuid=entity_uuid,
            expected_project_uuid=getattr(client, "project_uuid", None),
        )
        if isinstance(read_before, dict)
        else None
    )

    payload = load_payload(operation, base_dir=base_dir)
    payload = apply_payload_env(payload, operation, execute=True, client=client)
    if not isinstance(payload, dict):
        raise RuntimeError("runtime payload must be a JSON object")
    for finding in payload_secret_findings(
        payload,
        "payload",
        allowed_secret_paths=payload_env_paths(operation),
    ):
        raise RuntimeError(finding)
    scope_errors = payload_project_scope_errors(
        payload,
        getattr(client, "project_uuid", None),
    )
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    if (
        back_request
        and not valid_verification_waiver(operation)
        and ("entityUuid" in operation or "targetStrategy" in operation)
    ):
        identity_requests: list[tuple[str, str, Any]] = [
            ("readBack", back_request[0], back_request[1])
        ]
        if before_request:
            identity_requests.append(("readBefore", before_request[0], before_request[1]))
        identity_errors = single_entity_target_errors(
            operation,
            payload,
            nested_requests=identity_requests,
        )
        if identity_errors:
            raise RuntimeError(identity_errors[0])

    if before_request:
        before_endpoint, before_payload = before_request
        before = client.post(before_endpoint, before_payload if isinstance(before_payload, dict) else {}, ok_empty=True)
        write_json(
            out_dir,
            Path("operations") / f"{operation_id}_read_before.json",
            before,
            secret_values=secret_values,
        )

    try:
        response = client.post(main_endpoint, payload, ok_empty=True)
    except KSAPIUncertainResultError as exc:
        readback_state = "not_declared"
        if back_request:
            readback_state = "failed"
            try:
                uncertain_endpoint, uncertain_payload = back_request
                uncertain_after = client.post(
                    uncertain_endpoint,
                    uncertain_payload if isinstance(uncertain_payload, dict) else {},
                    ok_empty=True,
                )
                write_json(
                    out_dir,
                    Path("operations") / f"{operation_id}_read_back.json",
                    uncertain_after,
                    secret_values=secret_values,
                )
                readback_state = "completed"
                if isinstance(read_back, dict) and "checks" in read_back:
                    uncertain_report = evaluate_readback_checks(
                        uncertain_after,
                        read_back.get("checks"),
                    )
                    write_json(
                        out_dir,
                        Path("operations") / f"{operation_id}_read_back_checks.json",
                        uncertain_report,
                        secret_values=secret_values,
                    )
                    readback_state = "checks_passed" if uncertain_report.get("valid") else "checks_failed"
            except (KSAPIError, RuntimeError):
                readback_state = "failed"
        raise EffectUnknownError(
            "effect_unknown: runtime response was unavailable; "
            f"best-effort readBack={readback_state}; do not retry automatically"
        ) from exc
    runtime_path = write_json(
        out_dir,
        Path("operations") / f"{operation_id}_runtime_response.json",
        response,
        secret_values=secret_values,
    )

    back_path = None
    checks_path = None
    if back_request:
        back_endpoint, back_payload = back_request
        after = client.post(back_endpoint, back_payload if isinstance(back_payload, dict) else {}, ok_empty=True)
        back_path = write_json(
            out_dir,
            Path("operations") / f"{operation_id}_read_back.json",
            after,
            secret_values=secret_values,
        )
        if "checks" in read_back:
            check_report = evaluate_readback_checks(after, read_back.get("checks"))
            checks_path = write_json(
                out_dir,
                Path("operations") / f"{operation_id}_read_back_checks.json",
                check_report,
                secret_values=secret_values,
            )
            require_readback_checks(check_report)

    result = {
        "status": "executed_runtime",
        "runtimeResponsePath": str(runtime_path),
        "expectedEffect": operation.get("expectedEffect"),
    }
    if back_path:
        result["readBackPath"] = str(back_path)
    if checks_path:
        result["readBackChecksPath"] = str(checks_path)
    if operation.get("verificationWaiver"):
        result["verificationWaiver"] = operation.get("verificationWaiver")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Exact-approved executor for KS runtime operations")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--execute", action="store_true", help="Actually call exact-approved runtime endpoints")
    parser.add_argument("--out-dir", type=Path, default=Path("ks_approved_runtime_execute_out"))
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any operation is denied/deferred/failed")
    args = parser.parse_args()

    plan = load_plan(args.plan)
    base_dir = args.plan.resolve().parent
    try:
        out_dir = prepare_output_root(args.out_dir)
    except SafePathError as exc:
        raise SystemExit(f"unsafe output directory: {exc}") from exc
    lint_report, lint_blocking = lint(plan)
    atomic_write_text(out_dir, "lint_report.md", lint_report)

    operations = get_operations(plan)
    records: list[dict[str, Any]] = []
    executable: list[dict[str, Any]] = []
    blocked = 0
    client: KSClient | None = None

    for operation in operations:
        risk, issues = operation_gate(operation, plan, execute=args.execute)
        status = "ready"
        if issues:
            status = "deferred" if risk not in {"read_only", "external_or_runtime"} else "denied"
            blocked += 1
        record = {
            "id": operation.get("id"),
            "endpoint": norm_endpoint(operation.get("endpoint")) or "<invalid/redacted>",
            "risk": risk,
            "status": status,
            "issues": issues,
        }
        if not issues:
            executable.append(operation | {"_risk": risk})
        records.append(record)

    if args.execute and lint_blocking:
        global_issue = f"execution blocked by {lint_blocking} lint finding(s)"
        executable_ids = {operation["id"] for operation in executable}
        for record in records:
            if record["id"] in executable_ids:
                record["status"] = "denied"
                record["issues"] = [*record.get("issues", []), global_issue]
        blocked += len(executable)
        executable = []

    if args.execute and executable:
        try:
            prepare_output_subdir(out_dir, "operations")
            preflight_output_file(out_dir, "runtime_execution_report.json")
            preflight_output_file(out_dir, "runtime_execution_report.md")
            for operation in executable:
                preflight_operation_outputs(out_dir, operation, operation["_risk"])
            client = KSClient.from_env(require_project=True)
            plan_project = plan_project_uuid(plan)
            plan_stand = plan_stand_url(plan)
            if plan_project is None:
                raise RuntimeError("Execution requires a UUID-shaped plan targetProjectUuid")
            if client.project_uuid != plan_project:
                raise RuntimeError("KS_PROJECT_UUID does not match plan targetProjectUuid")
            if plan_stand is None or normalize_stand_url(client.base_url) != plan_stand:
                raise RuntimeError("KS_BASE_URL does not match plan baseUrl/stand")
            for operation in executable:
                preflight_operation_inputs(
                    operation,
                    operation["_risk"],
                    base_dir=base_dir,
                    expected_project_uuid=plan_project,
                    client=client,
                )
        except (SafePathError, KSAPIError, RuntimeError) as exc:
            issue = sanitize(
                f"local pre-execution validation failed: {exc}",
                secret_values=client_secret_values(client),
            )
            executable_ids = {operation["id"] for operation in executable}
            for record in records:
                if record["id"] in executable_ids:
                    record["status"] = "denied"
                    record["issues"] = [issue]
                    blocked += 1
            executable = []

    if args.execute and executable:
        try:
            client.login()
        except (KSAPIError, RuntimeError) as exc:
            login_issue = sanitize(
                str(exc),
                secret_values=client_secret_values(client),
            )
            executable_ids = [operation["id"] for operation in executable]
            first_executable_id = executable_ids[0]
            for record in records:
                if record["id"] not in executable_ids:
                    continue
                if record["id"] == first_executable_id:
                    record["status"] = "failed"
                    record["issues"] = [login_issue]
                else:
                    record["status"] = "not_executed_after_failure"
                    record["issues"] = ["login failed; fail-closed stop"]
                blocked += 1
            executable = []
        execution_failed = False
        for operation in executable:
            if execution_failed:
                for record in records:
                    if record["id"] == operation["id"]:
                        record["status"] = "not_executed_after_failure"
                        record["issues"] = ["an earlier operation failed; fail-closed stop"]
                        break
                blocked += 1
                continue
            try:
                if operation["_risk"] == "read_only":
                    result = execute_read(client, operation, base_dir=base_dir, out_dir=out_dir)
                elif operation["_risk"] == "external_or_runtime":
                    result = execute_runtime(client, operation, base_dir=base_dir, out_dir=out_dir)
                else:
                    raise RuntimeError(f"unsupported executable risk {operation['_risk']}")
                for record in records:
                    if record["id"] == operation["id"]:
                        record.update(result)
                        break
            except (KSAPIError, RuntimeError) as exc:
                safe_issue = sanitize(
                    str(exc),
                    secret_values=operation_secret_values(operation, client),
                )
                for record in records:
                    if record["id"] == operation["id"]:
                        record["status"] = (
                            "effect_unknown" if isinstance(exc, EffectUnknownError) else "failed"
                        )
                        record["issues"] = [safe_issue]
                        break
                blocked += 1
                execution_failed = True

    report = {
        "generatedAt": utc_now(),
        "mode": plan_mode(plan),
        "executeFlag": args.execute,
        "targetStand": plan_stand_url(plan) or "<missing>",
        "targetProjectUuid": plan_project_uuid(plan) or "<missing>",
        "lintBlockingFindings": lint_blocking,
        "operations": records,
    }
    report_secret_values = tuple(
        dict.fromkeys(
            (
                *(
                    value
                    for operation in operations
                    for value in payload_env_secret_values(operation)
                ),
                *client_secret_values(client),
            )
        )
    )
    write_json(
        out_dir,
        "runtime_execution_report.json",
        report,
        secret_values=report_secret_values,
    )

    lines = [
        "# KS Approved Runtime Execution Report",
        "",
        f"- generatedAt: `{report['generatedAt']}`",
        f"- planMode: `{report['mode']}`",
        f"- executeFlag: `{args.execute}`",
        f"- targetStand: `{report['targetStand']}`",
        f"- targetProjectUuid: `{report['targetProjectUuid']}`",
        f"- lintBlockingFindings: `{lint_blocking}`",
        "",
        "| Operation | Endpoint | Risk | Status | Issues |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in records:
        safe_record = sanitize(record, secret_values=report_secret_values)
        issues = "; ".join(safe_record.get("issues") or []) or "-"
        lines.append(f"| {safe_record['id']} | {safe_record['endpoint']} | {safe_record['risk']} | {safe_record['status']} | {issues} |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This executor is the separate exact-approved flow for runtime KS actions. It does not make ordinary project edits or destructive/global/server changes. Those belong to their own flows.",
            "",
            "Runtime actions are valid work when the user intentionally requests them, the target project is confirmed, the plan uses `mode=approved_runtime`, and the exact operation id or endpoint is approved.",
        ]
    )
    atomic_write_text(out_dir, "runtime_execution_report.md", "\n".join(lines) + "\n")
    print(f"report: {out_dir / 'runtime_execution_report.md'}")
    return 1 if blocked and (args.strict or args.execute) else 0


if __name__ == "__main__":
    raise SystemExit(main())
