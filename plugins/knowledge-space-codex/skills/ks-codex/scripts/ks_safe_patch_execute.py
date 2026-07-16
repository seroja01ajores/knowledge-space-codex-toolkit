#!/usr/bin/env python3
"""Guarded executor for KS safe patch plans.

This script is intentionally narrow. It can execute read-only API calls and
approved project-scoped writes. It refuses runtime, destructive/global, unknown,
and server/DB operations so those flows can be handled by separate explicit
procedures later.
"""

from __future__ import annotations

import argparse
import json
import sys
import datetime as dt
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
    RISK_REQUIRED_MODE,
    UUID_RE,
    approval_matches,
    classify_operation,
    endpoint_validation_error,
    executable_sensitive_payload_errors,
    execution_placeholder_errors,
    execution_readiness_error,
    get_operations,
    has_declared_payload,
    has_readback,
    has_readbefore,
    is_unresolved_placeholder_value,
    lint,
    load_plan,
    norm_endpoint,
    nested_read_endpoint_errors,
    normalize_stand_url,
    operation_payload_project_scope_errors,
    payload_project_scope_errors,
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
)


PLACEHOLDER_VALUES = {"", "<redacted>", "<password>", "<token>", "<secret>", "<cookie>", "...", None}
SOURCE_CONTEXT_KEYS = {"source", "sources", "connectionparam", "connectionparams", "connection", "connections"}
SOURCE_SECRET_KEYS = {"host", "login", "dbname", "database", "url", "uri", "productname"}


class EffectUnknownError(RuntimeError):
    """A mutation may have applied even though its response was unavailable."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def lower_key(key: Any) -> str:
    return str(key).replace("_", "").replace("-", "").lower()


def redact_secret_text(value: str, secret_values: tuple[str, ...]) -> str:
    return redact_text(value, secret_values)


def sanitize(
    value: Any,
    source_context: bool = False,
    secret_values: tuple[str, ...] = (),
) -> Any:
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


def payload_secret_findings(value: Any, label: str) -> list[str]:
    findings: list[str] = []
    sensitive_paths = set(sensitive_value_paths(value))
    for path, item in walk(value):
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
            findings.append(f"{label}: unredacted sensitive field {'.'.join(path)}")
    return findings


def load_payload(value: Any, *, base_dir: Path) -> Any:
    if isinstance(value, dict) and "payload" in value and "payloadPath" in value:
        raise RuntimeError("must declare only one of payload or payloadPath")
    if isinstance(value, dict) and "payloadPath" in value:
        return read_json_relative(
            base_dir,
            value["payloadPath"],
            label="payloadPath",
        )
    if isinstance(value, dict) and "payload" in value:
        payload = value["payload"]
        if isinstance(payload, str) and payload.startswith("<"):
            raise RuntimeError("payload is still a placeholder")
        return payload
    return {}


def endpoint_payload(
    block: Any,
    *,
    base_dir: Path,
    fallback_uuid: str | None = None,
    label: str = "nested endpoint",
    expected_project_uuid: str | None = None,
) -> tuple[str, Any]:
    if not isinstance(block, dict):
        raise RuntimeError("endpoint block must be an object")
    endpoint = require_read_only_endpoint_block(block, label=label)
    has_payload_source = "payload" in block or "payloadPath" in block
    payload = load_payload(block, base_dir=base_dir)
    for finding in payload_secret_findings(payload, f"{label} payload"):
        raise RuntimeError(finding)
    scope_errors = payload_project_scope_errors(
        payload,
        expected_project_uuid,
        label=f"{label} payload",
    )
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    if not has_payload_source and fallback_uuid and endpoint.endswith("/get-by-id"):
        payload = {"UUID": fallback_uuid, "uuid": fallback_uuid}
    return endpoint, payload


def plan_mode(plan: dict[str, Any]) -> str:
    return resolved_plan_mode(plan)


def approved_for_project_write(operation: dict[str, Any], plan: dict[str, Any]) -> bool:
    approval = plan.get("approval") if isinstance(plan.get("approval"), dict) else {}
    return approval_matches(operation, approval)


def operation_gate(operation: dict[str, Any], plan: dict[str, Any], *, execute: bool) -> tuple[str, list[str]]:
    risk = classify_operation(operation)
    mode = plan_mode(plan)
    issues: list[str] = []
    op_id = str(operation.get("id"))

    try:
        require_safe_operation_id(operation)
    except RuntimeError as exc:
        issues.append(str(exc))
    issues.extend(plan_mode_binding_errors(plan))
    endpoint_error = endpoint_validation_error(operation.get("endpoint"))
    if endpoint_error:
        issues.append(endpoint_error)
    issues.extend(nested_read_endpoint_errors(operation))
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

    for finding in secret_findings(operation):
        issues.append(finding)

    if risk in {"external_or_runtime", "destructive_or_global", "server_or_db", "unknown"}:
        issues.append(f"{risk} is deferred to a separate exact-approved runtime/destructive/server procedure")
        return risk, issues

    required = RISK_REQUIRED_MODE[risk]
    if MODE_ORDER[mode] < MODE_ORDER[required]:
        issues.append(f"mode {mode} is lower than required {required}")

    if risk == "project_write":
        if not has_declared_payload(operation):
            issues.append("project_write requires an explicit payload or payloadPath")
        if not has_readbefore(operation):
            issues.append("project_write requires readBefore/preRead/currentState")
        if not has_readback(operation):
            issues.append("project_write requires readBack/verification")
        else:
            readback_error = readback_definition_error(operation)
            if readback_error:
                issues.append(readback_error)
            checks_error = readback_checks_error(operation)
            if checks_error:
                issues.append(checks_error)
        read_back = operation.get("readBack") or operation.get("verification") or operation.get("verify")
        if isinstance(read_back, dict) and "checks" in read_back:
            issues.extend(f"invalid readBack checks: {error}" for error in validate_readback_checks(read_back.get("checks")))
        if not approved_for_project_write(operation, plan):
            issues.append("project_write requires approval.userApproved plus approved operation id/endpoint")
        if not execute:
            issues.append("project_write requires --execute")

    if risk == "read_only" and not execute:
        issues.append("dry-run only; use --execute to call read-only endpoint")

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
        json.dumps(
            sanitize(_redact(value), secret_values=secret_values),
            ensure_ascii=False,
            indent=2,
        ),
    )


def operation_output_paths(
    operation: dict[str, Any],
    risk: str,
) -> list[Path]:
    operation_id = require_safe_operation_id(operation)
    prefix = Path("operations") / operation_id
    if risk == "read_only":
        return [prefix.with_name(f"{operation_id}_response.json")]
    if risk == "project_write":
        return [
            prefix.with_name(f"{operation_id}_read_before.json"),
            prefix.with_name(f"{operation_id}_write_response.json"),
            prefix.with_name(f"{operation_id}_read_back.json"),
            prefix.with_name(f"{operation_id}_read_back_checks.json"),
        ]
    return []


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
) -> None:
    """Validate every local input before the first login or project API call."""
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
    if risk != "project_write":
        raise RuntimeError(f"unsupported safe-patch preflight risk: {risk}")
    execution_errors = [
        *executable_sensitive_payload_errors(operation, "project_write"),
        *execution_placeholder_errors(operation, "project_write"),
        *nested_read_endpoint_errors(operation),
    ]
    if execution_errors:
        raise RuntimeError(execution_errors[0])
    entity_uuid = operation.get("entityUuid") if isinstance(operation.get("entityUuid"), str) else None
    read_before_block = next(
        (operation.get(name) for name in ("readBefore", "preRead", "currentState") if name in operation),
        None,
    )
    read_back_block = next(
        (operation.get(name) for name in ("readBack", "verification", "verify") if name in operation),
        None,
    )
    check_errors = validate_readback_checks(
        read_back_block.get("checks") if isinstance(read_back_block, dict) else None
    )
    if check_errors:
        raise RuntimeError(f"invalid readBack checks: {check_errors[0]}")
    before_endpoint, before_payload = endpoint_payload(
        read_before_block,
        base_dir=base_dir,
        fallback_uuid=entity_uuid,
        label="readBefore",
        expected_project_uuid=expected_project_uuid,
    )
    back_endpoint, back_payload = endpoint_payload(
        read_back_block,
        base_dir=base_dir,
        fallback_uuid=entity_uuid,
        label="readBack",
        expected_project_uuid=expected_project_uuid,
    )
    payload = load_payload(operation, base_dir=base_dir)
    if not isinstance(payload, dict):
        raise RuntimeError("project_write payload must be a JSON object")
    findings = payload_secret_findings(payload, "payload")
    if findings:
        raise RuntimeError(findings[0])
    scope_errors = payload_project_scope_errors(payload, expected_project_uuid)
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    identity_errors = single_entity_target_errors(
        operation,
        payload,
        nested_requests=[
            ("readBefore", before_endpoint, before_payload),
            ("readBack", back_endpoint, back_payload),
        ],
    )
    if identity_errors:
        raise RuntimeError(identity_errors[0])


def execute_read_only(client: KSClient, operation: dict[str, Any], *, base_dir: Path, out_dir: Path) -> dict[str, Any]:
    operation_id = require_safe_operation_id(operation)
    endpoint = require_canonical_endpoint(operation.get("endpoint"))
    if classify_operation({"endpoint": endpoint}) != "read_only":
        raise RuntimeError("execute_read_only received a non-read-only endpoint")
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
    result = client.post(endpoint, payload if isinstance(payload, dict) else {"value": payload}, ok_empty=True)
    path = write_json(
        out_dir,
        Path("operations") / f"{operation_id}_response.json",
        result,
        secret_values=client_secret_values(client),
    )
    return {"status": "executed_read_only", "responsePath": str(path)}


def execute_project_write(client: KSClient, operation: dict[str, Any], *, base_dir: Path, out_dir: Path) -> dict[str, Any]:
    operation_id = require_safe_operation_id(operation)
    main_endpoint = require_canonical_endpoint(operation.get("endpoint"))
    if classify_operation({"endpoint": main_endpoint}) != "project_write":
        raise RuntimeError("execute_project_write received a non-project-write endpoint")
    execution_errors = [
        *executable_sensitive_payload_errors(operation, "project_write"),
        *execution_placeholder_errors(operation, "project_write"),
    ]
    if execution_errors:
        raise RuntimeError(execution_errors[0])
    nested_errors = nested_read_endpoint_errors(operation)
    if nested_errors:
        raise RuntimeError(nested_errors[0])
    preflight_operation_outputs(out_dir, operation, "project_write")
    secret_values = client_secret_values(client)
    entity_uuid = operation.get("entityUuid") if isinstance(operation.get("entityUuid"), str) else None
    read_before_block = operation.get("readBefore") or operation.get("preRead") or operation.get("currentState")
    read_back_block = operation.get("readBack") or operation.get("verification") or operation.get("verify")
    check_errors = validate_readback_checks(
        read_back_block.get("checks") if isinstance(read_back_block, dict) else None
    )
    if check_errors:
        raise RuntimeError(f"invalid readBack checks: {check_errors[0]}")
    before_endpoint, before_payload = endpoint_payload(
        read_before_block,
        base_dir=base_dir,
        fallback_uuid=entity_uuid,
        label="readBefore",
        expected_project_uuid=getattr(client, "project_uuid", None),
    )
    back_endpoint, back_payload = endpoint_payload(
        read_back_block,
        base_dir=base_dir,
        fallback_uuid=entity_uuid,
        label="readBack",
        expected_project_uuid=getattr(client, "project_uuid", None),
    )
    payload = load_payload(operation, base_dir=base_dir)
    if not isinstance(payload, dict):
        raise RuntimeError("project_write payload must be a JSON object")
    for finding in payload_secret_findings(payload, "payload"):
        raise RuntimeError(finding)
    scope_errors = payload_project_scope_errors(
        payload,
        getattr(client, "project_uuid", None),
    )
    if scope_errors:
        raise RuntimeError(scope_errors[0])
    identity_errors = single_entity_target_errors(
        operation,
        payload,
        nested_requests=[
            ("readBefore", before_endpoint, before_payload),
            ("readBack", back_endpoint, back_payload),
        ],
    )
    if identity_errors:
        raise RuntimeError(identity_errors[0])

    before = client.post(before_endpoint, before_payload if isinstance(before_payload, dict) else {}, ok_empty=False)
    before_path = write_json(
        out_dir,
        Path("operations") / f"{operation_id}_read_before.json",
        before,
        secret_values=secret_values,
    )
    try:
        write_response = client.post(main_endpoint, payload, ok_empty=True)
    except KSAPIUncertainResultError as exc:
        readback_state = "failed"
        try:
            uncertain_after = client.post(
                back_endpoint,
                back_payload if isinstance(back_payload, dict) else {},
                ok_empty=False,
            )
            write_json(
                out_dir,
                Path("operations") / f"{operation_id}_read_back.json",
                uncertain_after,
                secret_values=secret_values,
            )
            readback_state = "completed"
            if isinstance(read_back_block, dict) and "checks" in read_back_block:
                uncertain_report = evaluate_readback_checks(
                    uncertain_after,
                    read_back_block.get("checks"),
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
            "effect_unknown: mutation response was unavailable; "
            f"best-effort readBack={readback_state}; do not retry automatically"
        ) from exc
    write_path = write_json(
        out_dir,
        Path("operations") / f"{operation_id}_write_response.json",
        write_response,
        secret_values=secret_values,
    )
    after = client.post(back_endpoint, back_payload if isinstance(back_payload, dict) else {}, ok_empty=False)
    back_path = write_json(
        out_dir,
        Path("operations") / f"{operation_id}_read_back.json",
        after,
        secret_values=secret_values,
    )
    result = {
        "status": "executed_project_write",
        "readBeforePath": str(before_path),
        "writeResponsePath": str(write_path),
        "readBackPath": str(back_path),
    }
    if isinstance(read_back_block, dict) and "checks" in read_back_block:
        check_report = evaluate_readback_checks(after, read_back_block.get("checks"))
        checks_path = write_json(
            out_dir,
            Path("operations") / f"{operation_id}_read_back_checks.json",
            check_report,
            secret_values=secret_values,
        )
        result["readBackChecksPath"] = str(checks_path)
        require_readback_checks(check_report)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded executor for KS safe patch plans")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--execute", action="store_true", help="Actually call allowed KS API operations")
    parser.add_argument("--out-dir", type=Path, default=Path("ks_safe_patch_execute_out"))
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any operation is denied")
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
    denied = 0
    client: KSClient | None = None

    for operation in operations:
        risk, issues = operation_gate(operation, plan, execute=args.execute)
        record = {
            "id": operation.get("id"),
            "endpoint": norm_endpoint(operation.get("endpoint")) or "<invalid/redacted>",
            "risk": risk,
            "planned": bool(args.execute),
            "status": "deferred" if risk in {"external_or_runtime", "destructive_or_global", "server_or_db", "unknown"} and issues else ("denied" if issues else "ready"),
            "issues": issues,
        }
        if issues:
            denied += 1
        else:
            executable.append(operation | {"_risk": risk})
        records.append(record)

    if args.execute and lint_blocking:
        global_issue = f"execution blocked by {lint_blocking} lint finding(s)"
        executable_ids = {operation["id"] for operation in executable}
        for record in records:
            if record["id"] in executable_ids:
                record["status"] = "denied"
                record["issues"] = [*record.get("issues", []), global_issue]
        denied += len(executable)
        executable = []

    if args.execute and executable:
        try:
            prepare_output_subdir(out_dir, "operations")
            preflight_output_file(out_dir, "execution_report.json")
            preflight_output_file(out_dir, "execution_report.md")
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
                    denied += 1
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
                denied += 1
            executable = []
        execution_failed = False
        for operation in executable:
            if execution_failed:
                for record in records:
                    if record["id"] == operation["id"]:
                        record["status"] = "not_executed_after_failure"
                        record["issues"] = ["an earlier operation failed; fail-closed stop"]
                        break
                denied += 1
                continue
            try:
                if operation["_risk"] == "read_only":
                    result = execute_read_only(client, operation, base_dir=base_dir, out_dir=out_dir)
                elif operation["_risk"] == "project_write":
                    result = execute_project_write(client, operation, base_dir=base_dir, out_dir=out_dir)
                else:
                    raise RuntimeError(f"unsupported executable risk {operation['_risk']}")
                for record in records:
                    if record["id"] == operation["id"]:
                        record.update(result)
                        break
            except (KSAPIError, RuntimeError) as exc:
                safe_issue = sanitize(
                    str(exc),
                    secret_values=client_secret_values(client),
                )
                for record in records:
                    if record["id"] == operation["id"]:
                        record["status"] = (
                            "effect_unknown" if isinstance(exc, EffectUnknownError) else "failed"
                        )
                        record["issues"] = [safe_issue]
                        break
                denied += 1
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
    report_secret_values = client_secret_values(client)
    write_json(
        out_dir,
        "execution_report.json",
        report,
        secret_values=report_secret_values,
    )

    lines = [
        "# KS Safe Patch Execution Report",
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
        issue_text = "; ".join(safe_record.get("issues") or []) or "-"
        lines.append(f"| {safe_record['id']} | {safe_record['endpoint']} | {safe_record['risk']} | {safe_record['status']} | {issue_text} |")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "This executor only supports read-only and approved project-scoped write operations. Runtime, destructive/global, unknown, and server/DB operations are valid KS work when intentionally requested, but they require separate exact-approved runtime/destructive/server procedures and are not executed by this generic project-write script.",
        ]
    )
    atomic_write_text(out_dir, "execution_report.md", "\n".join(lines) + "\n")
    print(f"report: {out_dir / 'execution_report.md'}")
    return 1 if denied and (args.strict or args.execute) else 0


if __name__ == "__main__":
    raise SystemExit(main())
