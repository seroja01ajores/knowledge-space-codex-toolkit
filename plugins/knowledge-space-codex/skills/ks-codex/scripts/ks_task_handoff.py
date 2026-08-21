#!/usr/bin/env python3
"""Prepare and validate compact, secret-free KS task handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ks_capability_plan import (
    build_context_pack,
    load_capability_request,
    load_task_plan,
)
from ks_safe_files import (
    SafePathError,
    atomic_write_text,
    prepare_output_root,
    read_json_relative,
)
from ks_secret_safety import (
    redact_text,
    sensitive_value_paths,
    text_contains_secret,
)


SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
PLUGIN_ROOT = SKILL_ROOT.parent.parent
STATE_FORMAT = "teamvalue.ks-handoff-state"
STATE_VERSION = "1.0"
HANDOFF_FORMAT = "teamvalue.ks-task-handoff"
HANDOFF_VERSION = "1.0"
MAX_HANDOFF_BYTES = 1024 * 1024
MAX_TEXT_CHARS = 2048
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
)
RISK_CLASSES = {
    "read_only",
    "local_artifact_write",
    "project_write",
    "external_or_runtime",
    "destructive_or_global",
    "server_or_db",
}


class TaskHandoffError(RuntimeError):
    """Raised when a task handoff is invalid or unsafe."""


def _reject_extra(value: dict[str, Any], allowed: set[str], *, label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise TaskHandoffError(
            f"{label} has unsupported fields: {', '.join(extra)}"
        )


def _text(value: Any, *, label: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskHandoffError(f"{label} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise TaskHandoffError(f"{label} exceeds {max_chars} characters")
    if text_contains_secret(normalized):
        raise TaskHandoffError(f"{label} contains a recognized secret")
    return normalized


def _optional_text(
    value: Any, *, label: str, max_chars: int = MAX_TEXT_CHARS
) -> str | None:
    if value is None:
        return None
    return _text(value, label=label, max_chars=max_chars)


def _slug(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, max_chars=128)
    if not ID_PATTERN.fullmatch(normalized):
        raise TaskHandoffError(f"{label} must be a lowercase slug")
    return normalized


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise TaskHandoffError(f"{label} must be a lowercase SHA-256")
    return value


def _string_list(
    value: Any,
    *,
    label: str,
    max_items: int,
    max_chars: int = MAX_TEXT_CHARS,
) -> list[str]:
    if not isinstance(value, list):
        raise TaskHandoffError(f"{label} must be an array")
    if len(value) > max_items:
        raise TaskHandoffError(f"{label} exceeds {max_items} items")
    normalized = [
        _text(item, label=f"{label}[{position}]", max_chars=max_chars)
        for position, item in enumerate(value)
    ]
    if len(set(normalized)) != len(normalized):
        raise TaskHandoffError(f"{label} must not contain duplicates")
    return normalized


def _canonical_sha256(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_relative_path(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, max_chars=512)
    path = Path(normalized)
    if path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise TaskHandoffError(f"{label} must be a safe relative path")
    return path.as_posix()


def _contains_secret(value: Any) -> bool:
    if sensitive_value_paths(value):
        return True
    if isinstance(value, str):
        return text_contains_secret(value)
    if isinstance(value, dict):
        return any(_contains_secret(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def _normalize_target(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskHandoffError("target must be an object")
    _reject_extra(
        value,
        {"standAlias", "projectUuid", "projectUuidStatus"},
        label="target",
    )
    status = value.get("projectUuidStatus")
    if status not in {"confirmed", "unconfirmed", "not-applicable"}:
        raise TaskHandoffError("target.projectUuidStatus is invalid")
    project_uuid = value.get("projectUuid")
    if project_uuid is not None and (
        not isinstance(project_uuid, str)
        or not UUID_PATTERN.fullmatch(project_uuid)
    ):
        raise TaskHandoffError("target.projectUuid is invalid")
    if status == "confirmed" and project_uuid is None:
        raise TaskHandoffError(
            "target.projectUuid is required when its status is confirmed"
        )
    return {
        "standAlias": _optional_text(
            value.get("standAlias"),
            label="target.standAlias",
            max_chars=128,
        ),
        "projectUuid": project_uuid,
        "projectUuidStatus": status,
    }


def _normalize_facts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 200:
        raise TaskHandoffError("facts must be an array with at most 200 items")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskHandoffError(f"facts[{position}] must be an object")
        _reject_extra(
            item,
            {
                "id",
                "status",
                "entityType",
                "entityUuid",
                "statement",
                "evidenceRefs",
            },
            label=f"facts[{position}]",
        )
        fact_id = _slug(item.get("id"), label=f"facts[{position}].id")
        if fact_id in ids:
            raise TaskHandoffError(f"duplicate fact id: {fact_id}")
        ids.add(fact_id)
        status = item.get("status")
        if status not in {"verified", "inferred", "missing", "contradicted"}:
            raise TaskHandoffError(f"facts[{position}].status is invalid")
        entity_uuid = item.get("entityUuid")
        if entity_uuid is not None and (
            not isinstance(entity_uuid, str)
            or not UUID_PATTERN.fullmatch(entity_uuid)
        ):
            raise TaskHandoffError(f"facts[{position}].entityUuid is invalid")
        result.append(
            {
                "id": fact_id,
                "status": status,
                "entityType": _optional_text(
                    item.get("entityType"),
                    label=f"facts[{position}].entityType",
                    max_chars=128,
                ),
                "entityUuid": entity_uuid,
                "statement": _text(
                    item.get("statement"),
                    label=f"facts[{position}].statement",
                ),
                "evidenceRefs": _string_list(
                    item.get("evidenceRefs", []),
                    label=f"facts[{position}].evidenceRefs",
                    max_items=20,
                    max_chars=256,
                ),
            }
        )
    return result


def _normalize_approvals(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 50:
        raise TaskHandoffError(
            "approvals must be an array with at most 50 items"
        )
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskHandoffError(f"approvals[{position}] must be an object")
        _reject_extra(
            item,
            {"id", "risk", "status", "scope", "evidenceRefs"},
            label=f"approvals[{position}]",
        )
        approval_id = _slug(
            item.get("id"), label=f"approvals[{position}].id"
        )
        if approval_id in ids:
            raise TaskHandoffError(f"duplicate approval id: {approval_id}")
        ids.add(approval_id)
        risk = item.get("risk")
        if risk not in RISK_CLASSES:
            raise TaskHandoffError(f"approvals[{position}].risk is invalid")
        status = item.get("status")
        if status not in {
            "not-requested",
            "approved",
            "denied",
            "expired",
        }:
            raise TaskHandoffError(f"approvals[{position}].status is invalid")
        result.append(
            {
                "id": approval_id,
                "risk": risk,
                "status": status,
                "scope": _text(
                    item.get("scope"),
                    label=f"approvals[{position}].scope",
                ),
                "evidenceRefs": _string_list(
                    item.get("evidenceRefs", []),
                    label=f"approvals[{position}].evidenceRefs",
                    max_items=20,
                    max_chars=256,
                ),
            }
        )
    return result


def _normalize_artifacts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 100:
        raise TaskHandoffError(
            "artifacts must be an array with at most 100 items"
        )
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskHandoffError(f"artifacts[{position}] must be an object")
        _reject_extra(
            item,
            {"id", "kind", "path", "sha256", "status"},
            label=f"artifacts[{position}]",
        )
        artifact_id = _slug(
            item.get("id"), label=f"artifacts[{position}].id"
        )
        if artifact_id in ids:
            raise TaskHandoffError(f"duplicate artifact id: {artifact_id}")
        ids.add(artifact_id)
        status = item.get("status")
        if status not in {"created", "validated", "unverified"}:
            raise TaskHandoffError(f"artifacts[{position}].status is invalid")
        result.append(
            {
                "id": artifact_id,
                "kind": _slug(
                    item.get("kind"),
                    label=f"artifacts[{position}].kind",
                ),
                "path": _safe_relative_path(
                    item.get("path"),
                    label=f"artifacts[{position}].path",
                ),
                "sha256": _sha256(
                    item.get("sha256"),
                    label=f"artifacts[{position}].sha256",
                ),
                "status": status,
            }
        )
    return result


def _normalize_verification(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 100:
        raise TaskHandoffError(
            "verification must be an array with at most 100 items"
        )
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskHandoffError(
                f"verification[{position}] must be an object"
            )
        _reject_extra(
            item,
            {"id", "kind", "status", "evidenceRefs", "waiverReason"},
            label=f"verification[{position}]",
        )
        verification_id = _slug(
            item.get("id"), label=f"verification[{position}].id"
        )
        if verification_id in ids:
            raise TaskHandoffError(
                f"duplicate verification id: {verification_id}"
            )
        ids.add(verification_id)
        status = item.get("status")
        if status not in {"passed", "failed", "pending", "waived"}:
            raise TaskHandoffError(
                f"verification[{position}].status is invalid"
            )
        waiver_reason = _optional_text(
            item.get("waiverReason"),
            label=f"verification[{position}].waiverReason",
        )
        if status == "waived" and waiver_reason is None:
            raise TaskHandoffError(
                f"verification[{position}].waiverReason is required"
            )
        if status != "waived" and waiver_reason is not None:
            raise TaskHandoffError(
                f"verification[{position}].waiverReason requires waived status"
            )
        result.append(
            {
                "id": verification_id,
                "kind": _slug(
                    item.get("kind"),
                    label=f"verification[{position}].kind",
                ),
                "status": status,
                "evidenceRefs": _string_list(
                    item.get("evidenceRefs", []),
                    label=f"verification[{position}].evidenceRefs",
                    max_items=20,
                    max_chars=256,
                ),
                "waiverReason": waiver_reason,
            }
        )
    return result


def load_handoff_state(input_root: Path, input_name: str) -> dict[str, Any]:
    value = read_json_relative(
        input_root,
        input_name,
        label="handoff state",
        max_bytes=MAX_HANDOFF_BYTES,
    )
    if not isinstance(value, dict):
        raise TaskHandoffError("handoff state must be a JSON object")
    _reject_extra(
        value,
        {
            "format",
            "formatVersion",
            "completedPhaseId",
            "phaseStatus",
            "nextPhaseId",
            "target",
            "facts",
            "unknowns",
            "contradictions",
            "approvals",
            "artifacts",
            "verification",
            "nextAction",
        },
        label="handoff state",
    )
    if value.get("format") != STATE_FORMAT:
        raise TaskHandoffError("unsupported handoff state format")
    if value.get("formatVersion") != STATE_VERSION:
        raise TaskHandoffError("unsupported handoff state version")
    phase_status = value.get("phaseStatus")
    if phase_status not in {"completed", "partial", "blocked"}:
        raise TaskHandoffError("phaseStatus is invalid")
    normalized = {
        "format": STATE_FORMAT,
        "formatVersion": STATE_VERSION,
        "completedPhaseId": _slug(
            value.get("completedPhaseId"), label="completedPhaseId"
        ),
        "phaseStatus": phase_status,
        "nextPhaseId": (
            _slug(value["nextPhaseId"], label="nextPhaseId")
            if value.get("nextPhaseId") is not None
            else None
        ),
        "target": _normalize_target(value.get("target")),
        "facts": _normalize_facts(value.get("facts", [])),
        "unknowns": _string_list(
            value.get("unknowns", []), label="unknowns", max_items=100
        ),
        "contradictions": _string_list(
            value.get("contradictions", []),
            label="contradictions",
            max_items=100,
        ),
        "approvals": _normalize_approvals(value.get("approvals", [])),
        "artifacts": _normalize_artifacts(value.get("artifacts", [])),
        "verification": _normalize_verification(
            value.get("verification", [])
        ),
        "nextAction": _text(value.get("nextAction"), label="nextAction"),
    }
    if _contains_secret(normalized):
        raise TaskHandoffError(
            "handoff state contains a recognized secret representation"
        )
    return normalized


def prepare_handoff(
    plan: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    phases = plan["phases"]
    phase_ids = [phase["id"] for phase in phases]
    completed_phase = state["completedPhaseId"]
    if completed_phase not in phase_ids:
        raise TaskHandoffError(
            f"completed phase is absent from plan: {completed_phase}"
        )
    position = phase_ids.index(completed_phase)
    if state["phaseStatus"] == "completed":
        expected_next = (
            phase_ids[position + 1] if position + 1 < len(phase_ids) else None
        )
    else:
        expected_next = completed_phase
    requested_next = state["nextPhaseId"]
    if requested_next is not None and requested_next != expected_next:
        raise TaskHandoffError(
            f"nextPhaseId must be {expected_next!r} for this phase status"
        )
    next_phase = expected_next if requested_next is None else requested_next
    context_pack = build_context_pack(plan, completed_phase)
    body: dict[str, Any] = {
        "format": HANDOFF_FORMAT,
        "formatVersion": HANDOFF_VERSION,
        "planSha256": _canonical_sha256(plan),
        "requestSha256": plan["requestSha256"],
        "contextPackSha256": _canonical_sha256(context_pack),
        "stateSha256": _canonical_sha256(state),
        "completedPhaseId": completed_phase,
        "phaseStatus": state["phaseStatus"],
        "nextPhaseId": next_phase,
        "phaseExpectedOutputs": context_pack["phase"]["outputs"],
        "target": state["target"],
        "facts": state["facts"],
        "unknowns": state["unknowns"],
        "contradictions": state["contradictions"],
        "approvals": state["approvals"],
        "artifacts": state["artifacts"],
        "verification": state["verification"],
        "nextAction": state["nextAction"],
        "safety": {
            "planningOnly": True,
            "executionAuthorized": False,
            "containsRawResponses": False,
            "sensitiveValuesPresent": False,
            "actualEffectStillRequiresClassification": True,
        },
    }
    if "parentPlanSha256" in plan:
        body["parentPlanSha256"] = plan["parentPlanSha256"]
    body["handoffSha256"] = _canonical_sha256(body)
    return body


def load_task_handoff(input_root: Path, input_name: str) -> dict[str, Any]:
    value = read_json_relative(
        input_root,
        input_name,
        label="task handoff",
        max_bytes=MAX_HANDOFF_BYTES,
    )
    if not isinstance(value, dict):
        raise TaskHandoffError("task handoff must be a JSON object")
    if value.get("format") != HANDOFF_FORMAT:
        raise TaskHandoffError("unsupported task handoff format")
    if value.get("formatVersion") != HANDOFF_VERSION:
        raise TaskHandoffError("unsupported task handoff version")
    for field in (
        "planSha256",
        "requestSha256",
        "contextPackSha256",
        "stateSha256",
        "handoffSha256",
    ):
        _sha256(value.get(field), label=field)
    parent_hash = value.get("parentPlanSha256")
    if parent_hash is not None:
        _sha256(parent_hash, label="parentPlanSha256")
    safety = value.get("safety")
    if not isinstance(safety, dict):
        raise TaskHandoffError("handoff safety object is required")
    _reject_extra(
        safety,
        {
            "planningOnly",
            "executionAuthorized",
            "containsRawResponses",
            "sensitiveValuesPresent",
            "actualEffectStillRequiresClassification",
        },
        label="handoff safety",
    )
    if safety.get("planningOnly") is not True:
        raise TaskHandoffError("handoff must remain planning-only")
    if safety.get("executionAuthorized") is not False:
        raise TaskHandoffError("handoff must not authorize execution")
    if safety.get("containsRawResponses") is not False:
        raise TaskHandoffError("handoff must not contain raw responses")
    if safety.get("sensitiveValuesPresent") is not False:
        raise TaskHandoffError("handoff must not contain sensitive values")
    if safety.get("actualEffectStillRequiresClassification") is not True:
        raise TaskHandoffError(
            "handoff must preserve actual-effect classification"
        )
    supplied_hash = value["handoffSha256"]
    unsigned = dict(value)
    del unsigned["handoffSha256"]
    if _canonical_sha256(unsigned) != supplied_hash:
        raise TaskHandoffError("handoffSha256 does not match handoff content")
    if _contains_secret(value):
        raise TaskHandoffError(
            "task handoff contains a recognized secret representation"
        )
    return value


def bind_resume_request(
    handoff: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    existing = request.get("parentPlanSha256")
    parent_hash = handoff["planSha256"]
    if existing is not None and existing != parent_hash:
        raise TaskHandoffError(
            "request parentPlanSha256 conflicts with the validated handoff"
        )
    result = dict(request)
    result["parentPlanSha256"] = parent_hash
    return result


def _outside_plugin(root: Path) -> Path:
    resolved = prepare_output_root(root)
    plugin = PLUGIN_ROOT.resolve(strict=True)
    try:
        resolved.relative_to(plugin)
    except ValueError:
        return resolved
    raise TaskHandoffError(
        "generated handoffs and requests must stay outside the plugin"
    )


def _render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and validate compact KS task handoffs without calling KS."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--plan-root", type=Path, required=True)
    prepare.add_argument("--plan", required=True)
    prepare.add_argument("--state-root", type=Path, required=True)
    prepare.add_argument("--state", required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--output", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--input-root", type=Path, required=True)
    validate.add_argument("--input", required=True)

    bind = subparsers.add_parser("bind-request")
    bind.add_argument("--handoff-root", type=Path, required=True)
    bind.add_argument("--handoff", required=True)
    bind.add_argument("--request-root", type=Path, required=True)
    bind.add_argument("--request", required=True)
    bind.add_argument("--output-root", type=Path, required=True)
    bind.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            plan = load_task_plan(args.plan_root, args.plan)
            state = load_handoff_state(args.state_root, args.state)
            result = prepare_handoff(plan, state)
            output_root = _outside_plugin(args.output_root)
            atomic_write_text(output_root, args.output, _render(result))
        elif args.command == "validate":
            result = load_task_handoff(args.input_root, args.input)
        else:
            handoff = load_task_handoff(args.handoff_root, args.handoff)
            request = load_capability_request(args.request_root, args.request)
            result = bind_resume_request(handoff, request)
            output_root = _outside_plugin(args.output_root)
            atomic_write_text(output_root, args.output, _render(result))
        print(_render(result), end="")
        return 0
    except (
        TaskHandoffError,
        SafePathError,
        OSError,
        ValueError,
    ) as exc:
        message = redact_text(str(exc)).replace(str(Path.home()), "~")
        raise SystemExit(f"task handoff failed: {message}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
