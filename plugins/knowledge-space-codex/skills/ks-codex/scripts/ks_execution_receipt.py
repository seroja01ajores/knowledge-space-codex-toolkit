#!/usr/bin/env python3
"""Build compact evidence receipts from existing KS executor reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from ks_safe_files import (
    SafePathError,
    atomic_write_text,
    prepare_output_root,
    read_json_relative,
)
from ks_safe_patch_lint import (
    classify_operation,
    get_operations,
    norm_endpoint,
    plan_project_uuid,
    plan_stand_url,
    resolved_plan_mode,
)
from ks_secret_safety import redact_text, text_contains_secret


SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
PLUGIN_ROOT = SKILL_ROOT.parent.parent
RECEIPT_FORMAT = "teamvalue.ks-execution-receipt"
RECEIPT_VERSION = "1.0"
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TERMINAL_EXECUTED = {
    "executed_read_only",
    "executed_project_write",
    "executed_runtime",
}
KNOWN_STATUSES = TERMINAL_EXECUTED | {
    "ready",
    "denied",
    "deferred",
    "failed",
    "effect_unknown",
    "not_executed_after_failure",
}


class ExecutionReceiptError(RuntimeError):
    """Raised when executor evidence cannot produce a trusted receipt."""


def _canonical_sha256(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_root(value: Path, *, create: bool = False) -> Path:
    raw = value.expanduser()
    if raw.is_symlink():
        raise ExecutionReceiptError("root path must not be a symlink")
    if create:
        raw.mkdir(parents=True, exist_ok=True)
    try:
        root = raw.resolve(strict=True)
    except OSError as exc:
        raise ExecutionReceiptError("root path is unavailable") from exc
    if not root.is_dir():
        raise ExecutionReceiptError("root path must be a directory")
    return root


def _outside_plugin(value: Path) -> Path:
    root = prepare_output_root(value)
    plugin = PLUGIN_ROOT.resolve(strict=True)
    try:
        root.relative_to(plugin)
    except ValueError:
        return root
    raise ExecutionReceiptError(
        "execution receipts must stay outside the plugin directory"
    )


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return text_contains_secret(value)
    if isinstance(value, dict):
        return any(_contains_secret(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def _resolve_artifact(root: Path, value: str) -> tuple[Path, Path]:
    if root.is_symlink():
        raise ExecutionReceiptError("execution root must not be a symlink")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ExecutionReceiptError("execution root is unavailable") from exc
    if not root.is_dir():
        raise ExecutionReceiptError("execution root must be a directory")
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [root / raw, root.parent / raw]
    for candidate in candidates:
        if candidate.is_symlink():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_file():
            continue
        if any(
            (root / Path(*relative.parts[:index])).is_symlink()
            for index in range(1, len(relative.parts) + 1)
        ):
            continue
        return resolved, relative
    raise ExecutionReceiptError(
        "executor artifact path is unavailable or outside execution root"
    )


def _hash_file(path: Path) -> tuple[str, int]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ExecutionReceiptError("executor artifact must be a regular file")
        if info.st_size > MAX_ARTIFACT_BYTES:
            raise ExecutionReceiptError(
                "executor artifact exceeds the receipt size limit"
            )
        digest = hashlib.sha256()
        remaining = MAX_ARTIFACT_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining <= 0 and os.read(descriptor, 1):
            raise ExecutionReceiptError(
                "executor artifact exceeds the receipt size limit"
            )
        return digest.hexdigest(), info.st_size
    finally:
        os.close(descriptor)


def _artifact_descriptor(
    execution_root: Path, value: str, *, role: str
) -> dict[str, Any]:
    path, relative = _resolve_artifact(execution_root, value)
    digest, size = _hash_file(path)
    descriptor: dict[str, Any] = {
        "role": role,
        "path": relative.as_posix(),
        "sha256": digest,
        "bytes": size,
    }
    if role == "readBackChecksPath":
        checks = read_json_relative(
            execution_root,
            relative,
            label="read-back checks",
            max_bytes=MAX_REPORT_BYTES,
        )
        if not isinstance(checks, dict) or not isinstance(checks.get("valid"), bool):
            raise ExecutionReceiptError(
                "read-back checks artifact has no boolean valid field"
            )
        descriptor["checksValid"] = checks["valid"]
    return descriptor


def _load_plan(root: Path, name: str) -> dict[str, Any]:
    value = read_json_relative(root, name, label="safe patch plan")
    if not isinstance(value, dict):
        raise ExecutionReceiptError("safe patch plan must be a JSON object")
    return value


def _load_report(root: Path, name: str) -> dict[str, Any]:
    value = read_json_relative(
        root,
        name,
        label="executor report",
        max_bytes=MAX_REPORT_BYTES,
    )
    if not isinstance(value, dict):
        raise ExecutionReceiptError("executor report must be a JSON object")
    required = {
        "generatedAt",
        "mode",
        "executeFlag",
        "targetStand",
        "targetProjectUuid",
        "lintBlockingFindings",
        "operations",
    }
    if set(value) != required:
        raise ExecutionReceiptError("executor report shape is unsupported")
    if not isinstance(value["executeFlag"], bool):
        raise ExecutionReceiptError("executor report executeFlag must be boolean")
    if (
        isinstance(value["lintBlockingFindings"], bool)
        or not isinstance(value["lintBlockingFindings"], int)
        or value["lintBlockingFindings"] < 0
    ):
        raise ExecutionReceiptError(
            "executor report lintBlockingFindings is invalid"
        )
    if not isinstance(value["operations"], list):
        raise ExecutionReceiptError("executor report operations must be an array")
    if _contains_secret(value):
        raise ExecutionReceiptError(
            "executor report contains a recognized secret representation"
        )
    return value


def _operation_artifacts(
    execution_root: Path, record: dict[str, Any]
) -> list[dict[str, Any]]:
    values: list[tuple[str, str]] = []
    for key, value in record.items():
        if key.endswith("Path") and isinstance(value, str) and value.strip():
            values.append((key, value))
    return [
        _artifact_descriptor(execution_root, value, role=key)
        for key, value in sorted(values)
    ]


def _verification_state(
    record: dict[str, Any], artifacts: list[dict[str, Any]]
) -> str:
    checks = [
        item["checksValid"]
        for item in artifacts
        if item["role"] == "readBackChecksPath"
    ]
    if checks:
        return "passed" if all(checks) else "failed"
    if record.get("verificationWaiver") is not None:
        return "waived"
    if record["status"] == "executed_read_only":
        return "not-required"
    if record["status"] in TERMINAL_EXECUTED:
        return "readback-without-machine-check"
    if record["status"] == "effect_unknown":
        return "effect-unknown"
    return "not-run"


def _overall_status(report: dict[str, Any], records: list[dict[str, Any]]) -> str:
    statuses = {record["status"] for record in records}
    if not report["executeFlag"]:
        return (
            "dry-run-with-findings"
            if report["lintBlockingFindings"]
            else "dry-run"
        )
    if "effect_unknown" in statuses:
        return "effect-unknown"
    if records and statuses <= TERMINAL_EXECUTED:
        return "completed"
    return "incomplete"


def build_receipt(
    plan: dict[str, Any],
    report: dict[str, Any],
    *,
    execution_root: Path,
) -> dict[str, Any]:
    plan_mode = resolved_plan_mode(plan)
    plan_project = plan_project_uuid(plan) or "<missing>"
    plan_stand = plan_stand_url(plan) or "<missing>"
    if report["mode"] != plan_mode:
        raise ExecutionReceiptError("executor report mode differs from plan")
    if report["targetProjectUuid"] != plan_project:
        raise ExecutionReceiptError(
            "executor report project differs from plan target"
        )
    if report["targetStand"] != plan_stand:
        raise ExecutionReceiptError(
            "executor report stand differs from plan target"
        )

    planned_operations = get_operations(plan)
    by_id: dict[str, dict[str, Any]] = {}
    for operation in planned_operations:
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or not ID_PATTERN.fullmatch(
            operation_id
        ):
            raise ExecutionReceiptError("plan operation id is invalid")
        if operation_id in by_id:
            raise ExecutionReceiptError("plan operation ids must be unique")
        by_id[operation_id] = operation

    report_by_id: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(report["operations"]):
        if not isinstance(record, dict):
            raise ExecutionReceiptError(
                f"executor report operation {position} is not an object"
            )
        operation_id = record.get("id")
        if not isinstance(operation_id, str) or operation_id not in by_id:
            raise ExecutionReceiptError(
                "executor report contains an unknown operation"
            )
        if operation_id in report_by_id:
            raise ExecutionReceiptError(
                "executor report operation ids must be unique"
            )
        status = record.get("status")
        if status not in KNOWN_STATUSES:
            raise ExecutionReceiptError(
                f"executor report status is unsupported: {status}"
            )
        expected = by_id[operation_id]
        expected_endpoint = (
            norm_endpoint(expected.get("endpoint")) or "<invalid/redacted>"
        )
        if record.get("endpoint") != expected_endpoint:
            raise ExecutionReceiptError(
                f"executor report endpoint differs for {operation_id}"
            )
        expected_risk = classify_operation(expected)
        if record.get("risk") != expected_risk:
            raise ExecutionReceiptError(
                f"executor report risk differs for {operation_id}"
            )
        report_by_id[operation_id] = record
    if set(report_by_id) != set(by_id):
        raise ExecutionReceiptError(
            "executor report does not cover every planned operation"
        )

    compact_records: list[dict[str, Any]] = []
    for operation in planned_operations:
        operation_id = operation["id"]
        record = report_by_id[operation_id]
        artifacts = _operation_artifacts(execution_root, record)
        waiver = record.get("verificationWaiver")
        compact_records.append(
            {
                "id": operation_id,
                "endpoint": record["endpoint"],
                "risk": record["risk"],
                "status": record["status"],
                "issueCount": len(record.get("issues") or []),
                "verification": _verification_state(record, artifacts),
                "verificationWaiverSha256": (
                    hashlib.sha256(
                        json.dumps(
                            waiver,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    if waiver is not None
                    else None
                ),
                "artifacts": artifacts,
            }
        )

    body: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "formatVersion": RECEIPT_VERSION,
        "sourceKind": (
            "approved-runtime"
            if plan_mode == "approved_runtime"
            else "safe-patch"
        ),
        "planSha256": _canonical_sha256(plan),
        "reportSha256": _canonical_sha256(report),
        "generatedAt": report["generatedAt"],
        "mode": plan_mode,
        "executeFlag": report["executeFlag"],
        "target": {
            "standSha256": hashlib.sha256(
                plan_stand.encode("utf-8")
            ).hexdigest(),
            "projectUuid": plan_project,
        },
        "lintBlockingFindings": report["lintBlockingFindings"],
        "overallStatus": _overall_status(report, compact_records),
        "operations": compact_records,
        "safety": {
            "authorizesExecution": False,
            "authorizesRetry": False,
            "carriesApproval": False,
            "effectUnknownRequiresExplicitResolution": True,
            "actualEffectClassificationRemainsAuthoritative": True,
        },
    }
    body["receiptSha256"] = _canonical_sha256(body)
    return body


def load_receipt(input_root: Path, input_name: str) -> dict[str, Any]:
    value = read_json_relative(
        input_root,
        input_name,
        label="execution receipt",
        max_bytes=MAX_REPORT_BYTES,
    )
    if not isinstance(value, dict):
        raise ExecutionReceiptError("execution receipt must be a JSON object")
    if value.get("format") != RECEIPT_FORMAT:
        raise ExecutionReceiptError("unsupported execution receipt format")
    if value.get("formatVersion") != RECEIPT_VERSION:
        raise ExecutionReceiptError("unsupported execution receipt version")
    supplied = value.get("receiptSha256")
    if not isinstance(supplied, str) or not SHA256_PATTERN.fullmatch(supplied):
        raise ExecutionReceiptError("execution receipt hash is invalid")
    unsigned = dict(value)
    del unsigned["receiptSha256"]
    if _canonical_sha256(unsigned) != supplied:
        raise ExecutionReceiptError(
            "execution receipt hash does not match its content"
        )
    safety = value.get("safety")
    if not isinstance(safety, dict):
        raise ExecutionReceiptError("execution receipt safety is missing")
    if safety.get("authorizesExecution") is not False:
        raise ExecutionReceiptError(
            "execution receipt must not authorize execution"
        )
    if safety.get("authorizesRetry") is not False:
        raise ExecutionReceiptError(
            "execution receipt must not authorize retry"
        )
    if _contains_secret(value):
        raise ExecutionReceiptError(
            "execution receipt contains a recognized secret representation"
        )
    return value


def _render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build or validate a compact receipt from an existing KS executor "
            "report without calling KS."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--plan-root", type=Path, required=True)
    build.add_argument("--plan", required=True)
    build.add_argument("--execution-root", type=Path, required=True)
    build.add_argument("--report", required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--output", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--input-root", type=Path, required=True)
    validate.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            plan = _load_plan(args.plan_root, args.plan)
            execution_root = _safe_root(args.execution_root)
            report = _load_report(execution_root, args.report)
            result = build_receipt(
                plan,
                report,
                execution_root=execution_root,
            )
            output_root = _outside_plugin(args.output_root)
            atomic_write_text(output_root, args.output, _render(result))
        else:
            result = load_receipt(args.input_root, args.input)
        print(_render(result), end="")
        return 0
    except (
        ExecutionReceiptError,
        SafePathError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        message = redact_text(str(exc)).replace(str(Path.home()), "~")
        raise SystemExit(f"execution receipt failed: {message}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
