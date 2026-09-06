#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ks_safe_files import (
    SafePathError,
    atomic_write_text,
    prepare_output_root,
    read_json_relative,
)
from ks_secret_safety import (
    redact_text,
    text_contains_secret,
)

SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
PLUGIN_ROOT = SKILL_ROOT.parent.parent
DEFAULT_INDEX_ROOT = SKILL_ROOT / "references"
DEFAULT_INDEX_NAME = "capability-index.json"

RISK_ORDER = {
    "read_only": 0,
    "local_artifact_write": 1,
    "project_write": 2,
    "external_or_runtime": 3,
    "destructive_or_global": 4,
    "server_or_db": 5,
}
ALLOWED_PHASES = {"analysis", "change", "runtime", "verification"}
NARROW_READ_OPERATIONS = ("bind", "read-target", "inspect")
ALLOWED_VERIFICATION = {
    "api-readback",
    "browser",
    "offline-report",
    "isolated-restore-readback",
}
SELECTION_PRIORITY = {"dependency": 0, "read-before": 1, "direct": 2}
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
TASK_PLAN_FORMAT = "teamvalue.ks-task-plan"
TASK_PLAN_VERSION = "2.0"
CONTEXT_PACK_FORMAT = "teamvalue.ks-context-pack"
CONTEXT_PACK_VERSION = "1.0"


class CapabilityPlanError(RuntimeError):
    """Raised when a structured capability plan is invalid or unsafe."""


def _string_list(value: Any, *, label: str, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise CapabilityPlanError(f"{label} must be a JSON string array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise CapabilityPlanError(f"{label} must contain non-empty strings")
    return list(value)


def _reject_extra(value: dict[str, Any], allowed: set[str], *, label: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise CapabilityPlanError(f"{label} has unsupported fields: {', '.join(extra)}")


def _contains_secret_leaf(value: Any) -> bool:
    if isinstance(value, str):
        return text_contains_secret(value)
    if isinstance(value, dict):
        return any(_contains_secret_leaf(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_secret_leaf(item) for item in value)
    return False


def _bundled_path(kind: str, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise CapabilityPlanError(f"{kind} path must be safe and relative: {value}")
    root = (SKILL_ROOT / kind).resolve(strict=True)
    candidate = root / relative
    if candidate.is_symlink():
        raise CapabilityPlanError(f"{kind} path must not be a symlink: {value}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CapabilityPlanError(f"{kind} path is unavailable: {value}") from exc
    if not resolved.is_file():
        raise CapabilityPlanError(f"{kind} path is not a file: {value}")
    return resolved


def _validate_resources(value: dict[str, Any], *, label: str) -> None:
    references = _string_list(value.get("references", []), label=f"{label}.references")
    scripts = _string_list(value.get("scripts", []), label=f"{label}.scripts")
    for reference in references:
        _bundled_path("references", reference)
    for script in scripts:
        _bundled_path("scripts", script)


def load_capability_index(index_root: Path, index_name: str) -> dict[str, Any]:
    value = read_json_relative(index_root, index_name, label="capability index")
    if not isinstance(value, dict):
        raise CapabilityPlanError("capability index must be a JSON object")
    if value.get("format") != "teamvalue.ks-capability-index":
        raise CapabilityPlanError("unsupported capability index format")
    if value.get("formatVersion") != "2.0":
        raise CapabilityPlanError("unsupported capability index version")

    risk_order = _string_list(
        value.get("riskOrder"), label="riskOrder", allow_empty=False
    )
    if risk_order != list(RISK_ORDER):
        raise CapabilityPlanError("riskOrder does not match the planner risk model")

    risk_gates = value.get("riskGates")
    areas = value.get("areas")
    if not isinstance(risk_gates, dict) or not isinstance(areas, list) or not areas:
        raise CapabilityPlanError("capability index requires riskGates and areas")

    for risk in risk_order:
        gate = risk_gates.get(risk)
        if not isinstance(gate, dict):
            raise CapabilityPlanError(f"riskGates.{risk} must be an object")
        if not isinstance(gate.get("gate"), str) or not gate["gate"].strip():
            raise CapabilityPlanError(f"riskGates.{risk}.gate is required")
        _validate_resources(gate, label=f"riskGates.{risk}")

    by_id: dict[str, dict[str, Any]] = {}
    for position, area in enumerate(areas):
        if not isinstance(area, dict):
            raise CapabilityPlanError(f"areas[{position}] must be an object")
        area_id = area.get("id")
        if not isinstance(area_id, str) or not ID_PATTERN.fullmatch(area_id):
            raise CapabilityPlanError(f"areas[{position}].id is invalid")
        if area_id in by_id:
            raise CapabilityPlanError(f"duplicate area id: {area_id}")
        if not isinstance(area.get("order"), int):
            raise CapabilityPlanError(f"{area_id}.order must be an integer")
        for field in ("title", "purpose"):
            if not isinstance(area.get(field), str) or not area[field].strip():
                raise CapabilityPlanError(f"{area_id}.{field} is required")
        _string_list(area.get("requires", []), label=f"{area_id}.requires")
        _string_list(area.get("oftenWith", []), label=f"{area_id}.oftenWith")
        _validate_resources(area, label=area_id)

        operations = area.get("operations")
        if not isinstance(operations, list) or not operations:
            raise CapabilityPlanError(f"{area_id}.operations must be non-empty")
        operation_ids: set[str] = set()
        for op_position, operation in enumerate(operations):
            if not isinstance(operation, dict):
                raise CapabilityPlanError(
                    f"{area_id}.operations[{op_position}] must be an object"
                )
            operation_id = operation.get("id")
            if (
                not isinstance(operation_id, str)
                or not ID_PATTERN.fullmatch(operation_id)
            ):
                raise CapabilityPlanError(
                    f"{area_id}.operations[{op_position}].id is invalid"
                )
            if operation_id in operation_ids:
                raise CapabilityPlanError(
                    f"duplicate operation {area_id}.{operation_id}"
                )
            operation_ids.add(operation_id)
            if operation.get("risk") not in RISK_ORDER:
                raise CapabilityPlanError(
                    f"{area_id}.{operation_id}.risk is invalid"
                )
            _validate_resources(
                operation, label=f"{area_id}.operations.{operation_id}"
            )
            _string_list(
                operation.get("outputs", []),
                label=f"{area_id}.{operation_id}.outputs",
            )
            _string_list(
                operation.get("verification", []),
                label=f"{area_id}.{operation_id}.verification",
            )
        by_id[area_id] = area

    for area_id, area in by_id.items():
        for relation in area.get("requires", []) + area.get("oftenWith", []):
            if relation not in by_id:
                raise CapabilityPlanError(
                    f"{area_id} references unknown area {relation}"
                )
        for required in area.get("requires", []):
            required_operations = {
                operation["id"] for operation in by_id[required]["operations"]
            }
            if "inspect" not in required_operations:
                raise CapabilityPlanError(
                    f"required area {required} has no inspect operation"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(area_id: str) -> None:
        if area_id in visiting:
            raise CapabilityPlanError(f"dependency cycle includes {area_id}")
        if area_id in visited:
            return
        visiting.add(area_id)
        for required in by_id[area_id].get("requires", []):
            visit(required)
        visiting.remove(area_id)
        visited.add(area_id)

    for area_id in by_id:
        visit(area_id)
    return value


def _areas_by_id(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {area["id"]: area for area in index["areas"]}


def _operation(area: dict[str, Any], operation_id: str) -> dict[str, Any]:
    for operation in area["operations"]:
        if operation["id"] == operation_id:
            return operation
    raise CapabilityPlanError(
        f"unknown operation for {area['id']}: {operation_id}"
    )


def load_capability_request(input_root: Path, input_name: str) -> dict[str, Any]:
    value = read_json_relative(input_root, input_name, label="capability request")
    if not isinstance(value, dict):
        raise CapabilityPlanError("capability request must be a JSON object")
    _reject_extra(
        value,
        {
            "format",
            "formatVersion",
            "mode",
            "phase",
            "parentPlanSha256",
            "capabilities",
            "verification",
            "knowledge",
        },
        label="capability request",
    )
    if value.get("format") != "teamvalue.ks-capability-request":
        raise CapabilityPlanError("unsupported capability request format")
    if value.get("formatVersion") != "1.0":
        raise CapabilityPlanError("unsupported capability request version")
    if value.get("mode") != "coordinated":
        raise CapabilityPlanError("structured planning is only for coordinated mode")

    phase = value.get("phase", "analysis")
    if phase not in ALLOWED_PHASES:
        raise CapabilityPlanError(f"unsupported request phase: {phase}")

    parent_hash = value.get("parentPlanSha256")
    if parent_hash is not None and (
        not isinstance(parent_hash, str) or not SHA256_PATTERN.fullmatch(parent_hash)
    ):
        raise CapabilityPlanError("parentPlanSha256 must be a lowercase SHA-256")

    capabilities = value.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise CapabilityPlanError("capabilities must be a non-empty array")
    normalized_capabilities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for position, item in enumerate(capabilities):
        if not isinstance(item, dict):
            raise CapabilityPlanError(f"capabilities[{position}] must be an object")
        _reject_extra(item, {"id", "operation"}, label=f"capabilities[{position}]")
        area_id = item.get("id")
        operation_id = item.get("operation")
        if not isinstance(area_id, str) or not ID_PATTERN.fullmatch(area_id):
            raise CapabilityPlanError(f"capabilities[{position}].id is invalid")
        if (
            not isinstance(operation_id, str)
            or not ID_PATTERN.fullmatch(operation_id)
        ):
            raise CapabilityPlanError(
                f"capabilities[{position}].operation is invalid"
            )
        key = (area_id, operation_id)
        if key in seen:
            raise CapabilityPlanError(
                f"duplicate capability selection: {area_id}.{operation_id}"
            )
        seen.add(key)
        normalized_capabilities.append(
            {"id": area_id, "operation": operation_id}
        )

    verification = _string_list(
        value.get("verification", []), label="verification"
    )
    if len(set(verification)) != len(verification):
        raise CapabilityPlanError("verification must not contain duplicates")
    unsupported_verification = sorted(
        set(verification) - ALLOWED_VERIFICATION
    )
    if unsupported_verification:
        raise CapabilityPlanError(
            "unsupported verification modes: "
            + ", ".join(unsupported_verification)
        )

    knowledge = value.get("knowledge", {})
    if not isinstance(knowledge, dict):
        raise CapabilityPlanError("knowledge must be an object")
    _reject_extra(
        knowledge, {"search", "captureCandidate"}, label="knowledge"
    )
    for field in ("search", "captureCandidate"):
        if field in knowledge and not isinstance(knowledge[field], bool):
            raise CapabilityPlanError(f"knowledge.{field} must be boolean")

    normalized = {
        "format": value["format"],
        "formatVersion": value["formatVersion"],
        "mode": value["mode"],
        "phase": phase,
        "capabilities": normalized_capabilities,
        "verification": verification,
        "knowledge": {
            "search": bool(knowledge.get("search", False)),
            "captureCandidate": bool(
                knowledge.get("captureCandidate", False)
            ),
        },
    }
    if parent_hash is not None:
        normalized["parentPlanSha256"] = parent_hash

    if _contains_secret_leaf(normalized):
        raise CapabilityPlanError(
            "capability request contains a recognized secret representation"
        )
    return normalized


def _resource_union(*groups: list[str]) -> list[str]:
    return sorted({item for group in groups for item in group})


def _canonical_sha256(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_task_plan(input_root: Path, input_name: str) -> dict[str, Any]:
    value = read_json_relative(input_root, input_name, label="task plan")
    if not isinstance(value, dict):
        raise CapabilityPlanError("task plan must be a JSON object")
    if value.get("format") != TASK_PLAN_FORMAT:
        raise CapabilityPlanError("unsupported task plan format")
    if value.get("formatVersion") != TASK_PLAN_VERSION:
        raise CapabilityPlanError("unsupported task plan version")
    if value.get("mode") != "coordinated":
        raise CapabilityPlanError("context packs require a coordinated task plan")

    request_hash = value.get("requestSha256")
    if not isinstance(request_hash, str) or not SHA256_PATTERN.fullmatch(
        request_hash
    ):
        raise CapabilityPlanError("task plan requestSha256 is invalid")
    parent_hash = value.get("parentPlanSha256")
    if parent_hash is not None and (
        not isinstance(parent_hash, str)
        or not SHA256_PATTERN.fullmatch(parent_hash)
    ):
        raise CapabilityPlanError("task plan parentPlanSha256 is invalid")

    phases = value.get("phases")
    if not isinstance(phases, list) or not phases:
        raise CapabilityPlanError("task plan phases must be a non-empty array")
    seen_phase_ids: set[str] = set()
    for position, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise CapabilityPlanError(f"phases[{position}] must be an object")
        _reject_extra(
            phase,
            {
                "id",
                "objective",
                "capabilities",
                "references",
                "scripts",
                "gates",
                "outputs",
                "planningOnly",
            },
            label=f"phases[{position}]",
        )
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not ID_PATTERN.fullmatch(phase_id):
            raise CapabilityPlanError(f"phases[{position}].id is invalid")
        if phase_id in seen_phase_ids:
            raise CapabilityPlanError(f"duplicate phase id: {phase_id}")
        seen_phase_ids.add(phase_id)
        if (
            not isinstance(phase.get("objective"), str)
            or not phase["objective"].strip()
        ):
            raise CapabilityPlanError(
                f"phases[{position}].objective is required"
            )
        for field in ("capabilities", "gates", "outputs"):
            _string_list(
                phase.get(field, []),
                label=f"phases[{position}].{field}",
            )
        _validate_resources(phase, label=f"phases[{position}]")
        if phase.get("planningOnly") is not True:
            raise CapabilityPlanError(
                f"phases[{position}] must remain planning-only"
            )

    safety = value.get("safety")
    if not isinstance(safety, dict):
        raise CapabilityPlanError("task plan safety object is required")
    if safety.get("planningOnly") is not True:
        raise CapabilityPlanError("task plan must remain planning-only")
    if safety.get("executionAuthorized") is not False:
        raise CapabilityPlanError("task plan must not authorize execution")
    if safety.get("liveKsCalled") is not False:
        raise CapabilityPlanError("task plan must not claim a live KS call")
    if _contains_secret_leaf(value):
        raise CapabilityPlanError(
            "task plan contains a recognized secret representation"
        )
    return value


def _resource_descriptor(kind: str, value: str) -> dict[str, Any]:
    path = _bundled_path(kind, value)
    payload = path.read_bytes()
    return {
        "path": f"{kind}/{value}",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "defaultAction": (
            "read-for-current-phase"
            if kind == "references"
            else "execute-without-loading-source"
        ),
    }


def build_context_pack(
    plan: dict[str, Any], phase_id: str
) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(phase_id):
        raise CapabilityPlanError("phase id is invalid")
    phases = plan["phases"]
    phase_position = next(
        (
            position
            for position, phase in enumerate(phases)
            if phase["id"] == phase_id
        ),
        None,
    )
    if phase_position is None:
        available = ", ".join(phase["id"] for phase in phases)
        raise CapabilityPlanError(
            f"unknown phase {phase_id}; available phases: {available}"
        )
    phase = phases[phase_position]
    references = [
        _resource_descriptor("references", value)
        for value in phase.get("references", [])
    ]
    scripts = [
        _resource_descriptor("scripts", value)
        for value in phase.get("scripts", [])
    ]
    safety = plan["safety"]
    return {
        "format": CONTEXT_PACK_FORMAT,
        "formatVersion": CONTEXT_PACK_VERSION,
        "planSha256": _canonical_sha256(plan),
        "requestSha256": plan["requestSha256"],
        "mode": "coordinated",
        "phasePosition": phase_position,
        "phaseCount": len(phases),
        "phase": {
            "id": phase["id"],
            "objective": phase["objective"],
            "capabilities": list(phase.get("capabilities", [])),
            "gates": list(phase.get("gates", [])),
            "outputs": list(phase.get("outputs", [])),
            "planningOnly": True,
        },
        "resources": {
            "references": references,
            "scripts": scripts,
            "contentEmbedded": False,
        },
        "loadPolicy": {
            "scope": "current-phase-only",
            "areaLimit": None,
            "loadAllSkillReferences": False,
            "loadScriptSourceByDefault": False,
            "additionalCapabilitiesAllowed": True,
            "rebuildWhenEvidenceChanges": True,
        },
        "handoffPolicy": plan.get("contextPolicy", {}),
        "nextPhaseIds": [
            item["id"] for item in phases[phase_position + 1 :]
        ],
        "safety": {
            "planningOnly": True,
            "executionAuthorized": False,
            "liveKsCalled": False,
            "effectiveRisk": safety.get("effectiveRisk"),
            "requiredGate": safety.get("requiredGate"),
            "requiresEndpointEffectClassification": safety.get(
                "requiresEndpointEffectClassification", True
            ),
            "effectClassificationAuthority": safety.get(
                "effectClassificationAuthority",
                "actual endpoint, payload, channel, and expected effect",
            ),
        },
    }


def _expand_capabilities(
    request: dict[str, Any], index: dict[str, Any]
) -> list[dict[str, Any]]:
    by_id = _areas_by_id(index)
    entries: dict[tuple[str, str], dict[str, Any]] = {}

    def narrow_read_operation(area_id: str) -> str | None:
        operation_ids = {
            operation["id"] for operation in by_id[area_id]["operations"]
        }
        return next(
            (
                candidate
                for candidate in NARROW_READ_OPERATIONS
                if candidate in operation_ids
            ),
            None,
        )

    def add(
        area_id: str, operation_id: str, selection: str, reason: str
    ) -> None:
        if area_id not in by_id:
            raise CapabilityPlanError(f"unknown capability area: {area_id}")
        area = by_id[area_id]
        operation = _operation(area, operation_id)
        key = (area_id, operation_id)
        existing = entries.get(key)
        if existing is None:
            entries[key] = {
                "id": area_id,
                "operation": operation_id,
                "selection": selection,
                "reasons": [reason],
                "risk": operation["risk"],
                "references": _resource_union(
                    area.get("references", []),
                    operation.get("references", []),
                ),
                "scripts": _resource_union(
                    area.get("scripts", []),
                    operation.get("scripts", []),
                ),
                "outputs": list(operation.get("outputs", [])),
                "verification": list(operation.get("verification", [])),
            }
            return
        if SELECTION_PRIORITY[selection] > SELECTION_PRIORITY[existing["selection"]]:
            existing["selection"] = selection
        if reason not in existing["reasons"]:
            existing["reasons"].append(reason)

    def add_dependencies(area_id: str) -> None:
        for required in by_id[area_id].get("requires", []):
            read_operation = narrow_read_operation(required)
            if read_operation is None:
                raise CapabilityPlanError(
                    f"required area {required} has no safe read operation"
                )
            add(
                required,
                read_operation,
                "dependency",
                f"required-by:{area_id}",
            )
            add_dependencies(required)

    for selected in request["capabilities"]:
        add(selected["id"], selected["operation"], "direct", "selected-by-codex")
        read_operation = narrow_read_operation(selected["id"])
        if (
            read_operation is not None
            and selected["operation"] not in NARROW_READ_OPERATIONS
        ):
            add(
                selected["id"],
                read_operation,
                "read-before",
                f"read-before:{selected['operation']}",
            )
        add_dependencies(selected["id"])

    ordered = sorted(
        entries.values(),
        key=lambda entry: (
            by_id[entry["id"]]["order"],
            0 if entry["operation"] == "inspect" else 1,
            entry["operation"],
        ),
    )
    return ordered


def _max_risk(entries: list[dict[str, Any]], knowledge: dict[str, bool]) -> str:
    risks = [entry["risk"] for entry in entries if entry["selection"] == "direct"]
    if knowledge["captureCandidate"]:
        risks.append("local_artifact_write")
    if not risks:
        return "read_only"
    return max(risks, key=lambda risk: RISK_ORDER[risk])


def _gate_resources(
    index: dict[str, Any], risk: str
) -> tuple[str, list[str], list[str]]:
    gate = index["riskGates"][risk]
    return (
        gate["gate"],
        list(gate.get("references", [])),
        list(gate.get("scripts", [])),
    )


def build_plan(
    request: dict[str, Any], index: dict[str, Any]
) -> dict[str, Any]:
    entries = _expand_capabilities(request, index)
    by_id = _areas_by_id(index)
    direct_entries = [
        entry for entry in entries if entry["selection"] == "direct"
    ]
    read_entries = [
        entry for entry in entries if entry["operation"] in NARROW_READ_OPERATIONS
    ]
    selected_area_ids = sorted(
        {entry["id"] for entry in entries},
        key=lambda area_id: (by_id[area_id]["order"], area_id),
    )
    effective_risk = _max_risk(entries, request["knowledge"])
    required_gate, gate_references, gate_scripts = _gate_resources(
        index, effective_risk
    )

    phases: list[dict[str, Any]] = []
    if request["knowledge"]["search"]:
        phases.append(
            {
                "id": "retrieve-private-evidence",
                "objective": (
                    "Resolve focused evidence into one hash-bound full recipe "
                    "before broad project reads"
                ),
                "capabilities": ["knowledge-learning.search"],
                "references": [
                    "knowledge-card.schema.json",
                    "self-learning.md",
                    "known-path-first.md",
                ],
                "scripts": ["ks_knowledge.py"],
                "gates": [
                    "explicit private cards and database roots",
                    "retrieval does not authorize execution",
                ],
                "outputs": [
                    "bounded scope- and version-filtered matches",
                    "one hash-bound full recipe with compatibility requirements",
                ],
                "planningOnly": True,
            }
        )

    if read_entries:
        phases.append(
            {
                "id": "read-current-state",
                "objective": (
                    "Check only the live target, dependencies, and preconditions "
                    "needed by the selected route"
                ),
                "capabilities": [
                    f"{entry['id']}.{entry['operation']}"
                    for entry in read_entries
                ],
                "references": _resource_union(
                    *[entry["references"] for entry in read_entries]
                ),
                "scripts": _resource_union(
                    *[entry["scripts"] for entry in read_entries]
                ),
                "gates": ["project-scoped read-only"],
                "outputs": _resource_union(
                    *[entry["outputs"] for entry in read_entries]
                ),
                "planningOnly": True,
            }
        )

    if len(selected_area_ids) > 1 or len(direct_entries) > 1:
        phases.append(
            {
                "id": "cross-area-synthesis",
                "objective": "Build one evidence-labelled dependency chain",
                "capabilities": selected_area_ids,
                "references": ["multidomain-orchestration.md"],
                "scripts": [],
                "gates": [],
                "outputs": [
                    "verified, inferred, missing, and contradicted dependency chain"
                ],
                "planningOnly": True,
            }
        )

    if effective_risk != "read_only":
        phases.append(
            {
                "id": "approval-boundary",
                "objective": "Confirm the exact effect before any non-read action",
                "capabilities": [
                    f"{entry['id']}.{entry['operation']}"
                    for entry in direct_entries
                    if entry["risk"] != "read_only"
                ],
                "references": gate_references,
                "scripts": gate_scripts,
                "gates": [required_gate],
                "outputs": ["approved or blocked exact effect"],
                "planningOnly": True,
            }
        )

    for entry in direct_entries:
        if entry["operation"] in NARROW_READ_OPERATIONS:
            continue
        if (
            entry["id"] == "knowledge-learning"
            and entry["operation"] == "search"
            and request["knowledge"]["search"]
        ):
            continue
        operation_gate, operation_references, operation_scripts = _gate_resources(
            index, entry["risk"]
        )
        phases.append(
            {
                "id": f"prepare-{entry['id']}-{entry['operation']}",
                "objective": (
                    f"Prepare {entry['operation']} for {by_id[entry['id']]['title']}"
                ),
                "capabilities": [f"{entry['id']}.{entry['operation']}"],
                "references": _resource_union(
                    entry["references"], operation_references
                ),
                "scripts": _resource_union(
                    entry["scripts"], operation_scripts
                ),
                "gates": [operation_gate],
                "outputs": entry["outputs"],
                "planningOnly": True,
            }
        )

    verification_outputs = sorted(
        {
            item
            for entry in entries
            for item in entry["verification"]
        }
        | set(request["verification"])
    )
    phases.append(
        {
            "id": "verification",
            "objective": "Verify structural state and material behavior separately",
            "capabilities": selected_area_ids,
            "references": [],
            "scripts": [],
            "gates": [],
            "outputs": verification_outputs,
            "planningOnly": True,
        }
    )

    if request["knowledge"]["captureCandidate"]:
        phases.append(
            {
                "id": "prepare-learning-candidate",
                "objective": "Prepare a redacted private candidate knowledge card",
                "capabilities": ["knowledge-learning.prepare-candidate"],
                "references": ["knowledge-card.schema.json"],
                "scripts": ["ks_knowledge.py"],
                "gates": [
                    "explicit private cards root",
                    "candidate remains unpromoted",
                ],
                "outputs": ["redacted candidate card and verification gaps"],
                "planningOnly": True,
            }
        )

    canonical_request = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    plan: dict[str, Any] = {
        "format": TASK_PLAN_FORMAT,
        "formatVersion": TASK_PLAN_VERSION,
        "requestSha256": hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest(),
        "mode": "coordinated",
        "phase": request["phase"],
        "capabilities": [
            {
                "id": entry["id"],
                "operation": entry["operation"],
                "selection": entry["selection"],
                "reasons": entry["reasons"],
                "risk": entry["risk"],
            }
            for entry in entries
        ],
        "phases": phases,
        "contextPolicy": {
            "areaLimit": None,
            "loadDetailedReferences": "current-phase-only",
            "contextPackFormat": (
                f"{CONTEXT_PACK_FORMAT}@{CONTEXT_PACK_VERSION}"
            ),
            "retain": [
                "UUID-bound verified facts",
                "unknowns and contradictions",
                "approvals and prohibited effects",
                "artifacts and verification status",
            ],
            "storeRawResponses": False,
            "reloadReducedEvidence": False,
        },
        "knowledge": {
            "searchRequested": request["knowledge"]["search"],
            "captureCandidateRequested": request["knowledge"][
                "captureCandidate"
            ],
            "statuses": ["verified", "promoted"],
            "perPassResultLimit": 5,
            "additionalFocusedPassesAllowed": True,
            "retrievalBeforeBroadRead": request["knowledge"]["search"],
            "fullCardHashBound": request["knowledge"]["search"],
            "requiresLiveCompatibilityCheck": request["knowledge"]["search"],
            "authorizesExecution": False,
        },
        "safety": {
            "planningOnly": True,
            "executionAuthorized": False,
            "liveKsCalled": False,
            "effectiveRisk": effective_risk,
            "declaredCapabilityRisk": effective_risk,
            "requiredGate": required_gate,
            "requiresEndpointEffectClassification": True,
            "effectClassificationAuthority": (
                "actual endpoint, payload, channel, and expected effect"
            ),
            "actualEffectMayEscalateRisk": True,
            "actualEffectMayDowngradeRisk": False,
            "requestTextStored": False,
        },
    }
    if "parentPlanSha256" in request:
        plan["parentPlanSha256"] = request["parentPlanSha256"]
    return plan


def catalog(index: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "teamvalue.ks-capability-catalog",
        "formatVersion": "1.0",
        "areas": [
            {
                "id": area["id"],
                "title": area["title"],
                "purpose": area["purpose"],
                "requires": area.get("requires", []),
                "oftenWith": area.get("oftenWith", []),
                "operations": [
                    {
                        "id": operation["id"],
                        "risk": operation["risk"],
                    }
                    for operation in area["operations"]
                ],
            }
            for area in sorted(
                index["areas"], key=lambda item: (item["order"], item["id"])
            )
        ],
    }


def describe(index: dict[str, Any], capability: str) -> dict[str, Any]:
    by_id = _areas_by_id(index)
    if capability not in by_id:
        raise CapabilityPlanError(f"unknown capability area: {capability}")
    return {
        "format": "teamvalue.ks-capability-description",
        "formatVersion": "1.0",
        "area": by_id[capability],
    }


def _outside_plugin(root: Path) -> Path:
    resolved = prepare_output_root(root)
    plugin = PLUGIN_ROOT.resolve(strict=True)
    try:
        resolved.relative_to(plugin)
    except ValueError:
        return resolved
    raise CapabilityPlanError(
        "generated plans must stay outside the plugin directory"
    )


def _render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate structured coordinated KS capability selections without "
            "interpreting user language or calling KS."
        )
    )
    parser.add_argument("--index-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--index", default=DEFAULT_INDEX_NAME)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("catalog", help="Print the compact capability catalog.")

    describe_parser = subparsers.add_parser(
        "describe", help="Describe one capability area."
    )
    describe_parser.add_argument("--capability", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate and expand a structured capability request."
    )
    validate_parser.add_argument("--input-root", type=Path, required=True)
    validate_parser.add_argument("--input", required=True)
    validate_parser.add_argument("--output-root", type=Path)
    validate_parser.add_argument("--output")

    pack_parser = subparsers.add_parser(
        "pack",
        help=(
            "Build a content-free resource manifest for one task-plan phase."
        ),
    )
    pack_parser.add_argument("--input-root", type=Path, required=True)
    pack_parser.add_argument("--input", required=True)
    pack_parser.add_argument("--phase-id", required=True)
    pack_parser.add_argument("--output-root", type=Path)
    pack_parser.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "pack":
            if bool(args.output_root) != bool(args.output):
                raise CapabilityPlanError(
                    "--output-root and --output must be supplied together"
                )
            plan = load_task_plan(args.input_root, args.input)
            result = build_context_pack(plan, args.phase_id)
        else:
            index = load_capability_index(args.index_root, args.index)
            if args.command == "catalog":
                result = catalog(index)
            elif args.command == "describe":
                result = describe(index, args.capability)
            else:
                if bool(args.output_root) != bool(args.output):
                    raise CapabilityPlanError(
                        "--output-root and --output must be supplied together"
                    )
                request = load_capability_request(args.input_root, args.input)
                result = build_plan(request, index)

        rendered = _render(result)
        if args.command in {"validate", "pack"} and args.output_root:
            output_root = _outside_plugin(args.output_root)
            atomic_write_text(output_root, args.output, rendered)
        print(rendered, end="")
        return 0
    except (CapabilityPlanError, SafePathError, OSError, ValueError) as exc:
        message = redact_text(str(exc)).replace(str(Path.home()), "~")
        raise SystemExit(f"capability planning failed: {message}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
