#!/usr/bin/env python3
"""Validate normalized KS workflow policy traces without interpreting language."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from ks_safe_files import SafePathError, read_json_relative
from ks_secret_safety import redact_text, text_contains_secret


TRACE_FORMAT = "teamvalue.ks-workflow-trace"
TRACE_VERSION = "1.2"
ACTOR_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
API_PREFIX_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+/?)+$")
TASK_CLASSES = {"mechanical", "single-area", "cross-area", "runtime"}
MODES = {"direct", "coordinated", "discovery"}
AUDIT_SCOPES = {"area", "full"}
KNOWN_PATH_SOURCES = {
    "supplied-card",
    "private-index",
    "bundled-pattern",
    "project-analogue",
}
RISK_SCOPES = {"target", "area", "cross-area"}
RESULTS = {
    "ok",
    "compatible",
    "not-found",
    "mismatch",
    "exhausted",
    "approved",
    "blocked",
    "failed",
    "unknown",
}
ACTIONS = {
    "mode.enter",
    "target.bind",
    "stand.fingerprint",
    "known-path.resolve",
    "knowledge.get-card",
    "compatibility.check",
    "known-path.exhausted",
    "risk.signal",
    "delegate.read",
    "probe.reconcile",
    "target.read",
    "dependency.read",
    "write.dry-run",
    "audit.area",
    "audit.full",
    "discovery.inspect-api",
    "discovery.inspect-ui-network",
    "approval.server-readonly",
    "discovery.inspect-server-readonly",
    "project.write",
    "target.readback",
    "browser.verify",
    "approval.runtime",
    "runtime.execute",
    "runtime.verify",
    "verification.waiver",
}
BROAD_ACTIONS = {
    "target.read",
    "dependency.read",
    "audit.area",
    "audit.full",
    "discovery.inspect-api",
    "discovery.inspect-ui-network",
    "discovery.inspect-server-readonly",
}
DISCOVERY_ACTIONS = {
    "discovery.inspect-api",
    "discovery.inspect-ui-network",
    "discovery.inspect-server-readonly",
}
AUDIT_ACTIONS = {"audit.area", "audit.full"}
MUTATION_ACTIONS = {"project.write", "runtime.execute"}
OPERATION_CHAIN_ACTIONS = {
    "target.read",
    "write.dry-run",
    "project.write",
    "target.readback",
}
RUNTIME_BOUND_ACTIONS = {
    "approval.runtime",
    "runtime.execute",
    "runtime.verify",
    "verification.waiver",
}
DELEGATED_READ_ACTIONS = {
    "target.read",
    "dependency.read",
    "audit.area",
    "audit.full",
    "discovery.inspect-api",
    "discovery.inspect-ui-network",
    "discovery.inspect-server-readonly",
}
EVENT_REQUIRED = {"step", "actor", "action", "result"}
EVENT_OPTIONAL = {
    "toMode",
    "assignee",
    "allowedAction",
    "endpointFamily",
    "endpointPrefix",
    "candidateRef",
    "candidateSha256",
    "operationId",
    "projectRef",
    "targetRef",
    "areaRef",
    "endpoint",
    "requestDigest",
    "signal",
    "source",
    "riskScope",
    "probeKey",
    "noWrite",
}
TEXT_EVENT_FIELDS = EVENT_OPTIONAL - {"noWrite"}

CARD_SOURCES = {"supplied-card", "private-index"}
CONCLUSIVE_RESOLUTION_RESULTS = {"ok", "compatible", "not-found"}
ROUTE_DECISION_ACTIONS = {
    "target.bind",
    "stand.fingerprint",
    "known-path.resolve",
    "knowledge.get-card",
    "compatibility.check",
    "known-path.exhausted",
    "mode.enter",
}
ACTION_RESULTS = {
    "mode.enter": {"ok"},
    "target.bind": {"ok", "blocked", "failed", "unknown"},
    "stand.fingerprint": {"ok", "blocked", "failed", "unknown"},
    "known-path.resolve": {
        "ok",
        "compatible",
        "not-found",
        "blocked",
        "failed",
        "unknown",
    },
    "knowledge.get-card": {"ok", "not-found", "blocked", "failed", "unknown"},
    "compatibility.check": {
        "compatible",
        "mismatch",
        "not-found",
        "blocked",
        "failed",
        "unknown",
    },
    "known-path.exhausted": {"exhausted", "blocked", "failed", "unknown"},
    "risk.signal": {"ok", "blocked", "failed", "unknown"},
    "delegate.read": {"ok", "blocked", "failed", "unknown"},
    "probe.reconcile": {"ok", "blocked", "failed", "unknown"},
    "target.read": {"ok", "blocked", "failed", "unknown"},
    "dependency.read": {"ok", "blocked", "failed", "unknown"},
    "write.dry-run": {"ok", "blocked", "failed", "unknown"},
    "audit.area": {"ok", "blocked", "failed", "unknown"},
    "audit.full": {"ok", "blocked", "failed", "unknown"},
    "discovery.inspect-api": {"ok", "blocked", "failed", "unknown"},
    "discovery.inspect-ui-network": {"ok", "blocked", "failed", "unknown"},
    "approval.server-readonly": {"approved", "blocked", "failed", "unknown"},
    "discovery.inspect-server-readonly": {"ok", "blocked", "failed", "unknown"},
    "project.write": {"ok", "blocked", "failed", "unknown"},
    "target.readback": {"ok", "blocked", "failed", "unknown"},
    "browser.verify": {"ok", "blocked", "failed", "unknown"},
    "approval.runtime": {"approved", "blocked", "failed", "unknown"},
    "runtime.execute": {"ok", "blocked", "failed", "unknown"},
    "runtime.verify": {"ok", "blocked", "failed", "unknown"},
    "verification.waiver": {"approved", "blocked", "failed", "unknown"},
}


class WorkflowTraceError(RuntimeError):
    """Raised when a workflow trace does not match the normalized contract."""


def _bounded_text(value: Any, *, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise WorkflowTraceError(f"{label} must be a non-empty bounded string")
    return value


def _require_fields(
    event: dict[str, Any], position: int, fields: tuple[str, ...], *, label: str
) -> None:
    missing = {field for field in fields if field not in event}
    if missing:
        raise WorkflowTraceError(
            f"events[{position}] {label} is missing: {', '.join(sorted(missing))}"
        )


def _require_api_path(event: dict[str, Any], position: int) -> None:
    if not event["endpoint"].startswith("/"):
        raise WorkflowTraceError(
            f"events[{position}].endpoint must be an absolute API path"
        )


def _require_api_prefix(event: dict[str, Any], position: int) -> None:
    prefix = event["endpointPrefix"]
    if (
        prefix == "/"
        or not prefix.endswith("/")
        or not API_PREFIX_RE.fullmatch(prefix)
        or any(segment in {".", ".."} for segment in prefix.split("/"))
    ):
        raise WorkflowTraceError(
            f"events[{position}].endpointPrefix must be a deterministic absolute API prefix"
        )


def _validate_shape(trace: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "format",
        "formatVersion",
        "taskClass",
        "mode",
        "coordinatorOwner",
        "writerOwner",
        "requestedAuditScope",
        "suppliedCard",
        "events",
    }
    if set(trace) != required:
        raise WorkflowTraceError("workflow trace top-level shape is invalid")
    if trace["format"] != TRACE_FORMAT or trace["formatVersion"] != TRACE_VERSION:
        raise WorkflowTraceError("unsupported workflow trace format")
    if trace["taskClass"] not in TASK_CLASSES:
        raise WorkflowTraceError("taskClass is invalid")
    if trace["mode"] not in MODES:
        raise WorkflowTraceError("mode is invalid")
    coordinator = trace["coordinatorOwner"]
    if not isinstance(coordinator, str) or not ACTOR_RE.fullmatch(coordinator):
        raise WorkflowTraceError("coordinatorOwner is invalid")
    owner = trace["writerOwner"]
    if owner is not None and (
        not isinstance(owner, str) or not ACTOR_RE.fullmatch(owner)
    ):
        raise WorkflowTraceError("writerOwner is invalid")
    requested_audit = trace["requestedAuditScope"]
    if requested_audit is not None:
        if not isinstance(requested_audit, dict):
            raise WorkflowTraceError(
                "requestedAuditScope must be null or a bound object"
            )
        scope = requested_audit.get("scope")
        expected_fields = {
            "area": {"scope", "projectRef", "targetRef", "areaRef"},
            "full": {"scope", "projectRef"},
        }.get(scope)
        if expected_fields is None or set(requested_audit) != expected_fields:
            raise WorkflowTraceError("requestedAuditScope is invalid")
        for field in expected_fields - {"scope"}:
            _bounded_text(
                requested_audit[field], label=f"requestedAuditScope.{field}"
            )
    supplied_card = trace["suppliedCard"]
    if supplied_card is not None:
        if (
            not isinstance(supplied_card, dict)
            or set(supplied_card) != {"ref", "sha256"}
            or not isinstance(supplied_card["ref"], str)
            or not supplied_card["ref"]
            or len(supplied_card["ref"]) > 500
            or not isinstance(supplied_card["sha256"], str)
            or not SHA256_RE.fullmatch(supplied_card["sha256"])
        ):
            raise WorkflowTraceError("suppliedCard is invalid")
    events = trace["events"]
    if not isinstance(events, list) or not events:
        raise WorkflowTraceError("events must be a non-empty array")
    prior_step = 0
    for position, event in enumerate(events):
        if not isinstance(event, dict):
            raise WorkflowTraceError(f"events[{position}] must be an object")
        if not EVENT_REQUIRED.issubset(event) or set(event) - (
            EVENT_REQUIRED | EVENT_OPTIONAL
        ):
            raise WorkflowTraceError(f"events[{position}] shape is invalid")
        step = event["step"]
        if isinstance(step, bool) or not isinstance(step, int) or step <= prior_step:
            raise WorkflowTraceError("event steps must be strictly increasing integers")
        prior_step = step
        actor = event["actor"]
        if not isinstance(actor, str) or not ACTOR_RE.fullmatch(actor):
            raise WorkflowTraceError(f"events[{position}].actor is invalid")
        if event["action"] not in ACTIONS:
            raise WorkflowTraceError(f"events[{position}].action is invalid")
        if event["result"] not in RESULTS:
            raise WorkflowTraceError(f"events[{position}].result is invalid")
        if event["result"] not in ACTION_RESULTS[event["action"]]:
            raise WorkflowTraceError(
                f"events[{position}].result is invalid for {event['action']}"
            )
        for field in TEXT_EVENT_FIELDS & set(event):
            _bounded_text(event[field], label=f"events[{position}].{field}")
        if "noWrite" in event and not isinstance(event["noWrite"], bool):
            raise WorkflowTraceError(f"events[{position}].noWrite must be boolean")
        if event["action"] == "known-path.resolve":
            if event.get("source") not in KNOWN_PATH_SOURCES:
                raise WorkflowTraceError(
                    f"events[{position}].source is required for known-path.resolve"
                )
            if event["result"] in {"ok", "compatible"}:
                _require_fields(
                    event, position, ("candidateRef",), label="candidate binding"
                )
            if event["source"] == "supplied-card":
                _require_fields(
                    event,
                    position,
                    ("candidateRef", "candidateSha256"),
                    label="supplied card binding",
                )
            elif (
                event["source"] == "private-index"
                and event["result"] in {"ok", "compatible"}
            ):
                _require_fields(
                    event,
                    position,
                    ("candidateSha256",),
                    label="card hash binding",
                )
        elif "source" in event:
            raise WorkflowTraceError(
                f"events[{position}].source is allowed only for known-path.resolve"
            )
        if "candidateSha256" in event and not SHA256_RE.fullmatch(
            event["candidateSha256"]
        ):
            raise WorkflowTraceError(
                f"events[{position}].candidateSha256 must be a lowercase SHA-256"
            )
        if "requestDigest" in event and not SHA256_RE.fullmatch(
            event["requestDigest"]
        ):
            raise WorkflowTraceError(
                f"events[{position}].requestDigest must be a lowercase SHA-256"
            )
        if event["action"] == "knowledge.get-card":
            _require_fields(
                event,
                position,
                ("candidateRef", "candidateSha256"),
                label="card binding",
            )
        if event["action"] == "stand.fingerprint":
            _require_fields(event, position, ("projectRef",), label="stand binding")
        if event["action"] == "compatibility.check":
            _require_fields(
                event,
                position,
                ("candidateRef", "projectRef", "targetRef"),
                label="compatibility binding",
            )
            if event["result"] == "mismatch":
                _require_fields(
                    event,
                    position,
                    ("signal",),
                    label="compatibility mismatch reason",
                )
        if event["action"] in {"target.bind", "known-path.exhausted"}:
            _require_fields(
                event,
                position,
                ("projectRef", "targetRef"),
                label="target binding",
            )
        if event["action"] == "mode.enter":
            _require_fields(
                event,
                position,
                ("projectRef", "targetRef"),
                label="mode scope binding",
            )
            if event.get("toMode") not in MODES or event["result"] != "ok":
                raise WorkflowTraceError(
                    f"events[{position}] mode.enter requires a valid toMode and result=ok"
                )
        elif "toMode" in event:
            raise WorkflowTraceError(
                f"events[{position}].toMode is allowed only for mode.enter"
            )
        if event["action"] == "risk.signal":
            if event.get("riskScope") not in RISK_SCOPES:
                raise WorkflowTraceError(
                    f"events[{position}].riskScope is required for risk.signal"
                )
            _require_fields(
                event, position, ("projectRef", "signal"), label="risk binding"
            )
            if event["riskScope"] in {"target", "area"}:
                _require_fields(
                    event, position, ("targetRef",), label="target risk binding"
                )
            if event["riskScope"] in {"area", "cross-area"}:
                _require_fields(
                    event, position, ("areaRef",), label="area risk binding"
                )
        elif "riskScope" in event:
            raise WorkflowTraceError(
                f"events[{position}].riskScope is allowed only for risk.signal"
            )
        if event["action"] == "delegate.read":
            _require_fields(
                event,
                position,
                (
                    "assignee",
                    "allowedAction",
                    "endpointFamily",
                    "endpointPrefix",
                    "candidateRef",
                    "probeKey",
                    "projectRef",
                    "targetRef",
                ),
                label="delegation binding",
            )
            if event.get("noWrite") is not True:
                raise WorkflowTraceError(
                    f"events[{position}] delegated reads require probeKey and noWrite=true"
                )
            if not ACTOR_RE.fullmatch(event["assignee"]):
                raise WorkflowTraceError(f"events[{position}].assignee is invalid")
            if event["allowedAction"] not in DELEGATED_READ_ACTIONS:
                raise WorkflowTraceError(
                    f"events[{position}].allowedAction is not a delegated read"
                )
            _require_api_prefix(event, position)
        elif event["action"] == "probe.reconcile":
            _require_fields(
                event,
                position,
                (
                    "probeKey",
                    "candidateRef",
                    "endpointFamily",
                    "projectRef",
                    "targetRef",
                ),
                label="probe reconciliation binding",
            )
        else:
            if "noWrite" in event:
                raise WorkflowTraceError(
                    f"events[{position}].noWrite is allowed only for delegate.read"
                )
            if "assignee" in event:
                raise WorkflowTraceError(
                    f"events[{position}].assignee is allowed only for delegate.read"
                )
            if "allowedAction" in event:
                raise WorkflowTraceError(
                    f"events[{position}].allowedAction is allowed only for delegate.read"
                )
        if "probeKey" in event and not (
            event["action"] == "delegate.read"
            or event["action"] in DELEGATED_READ_ACTIONS
            or event["action"] == "probe.reconcile"
        ):
            raise WorkflowTraceError(
                f"events[{position}].probeKey is not allowed for this action"
            )
        if "endpointPrefix" in event and event["action"] != "delegate.read":
            raise WorkflowTraceError(
                f"events[{position}].endpointPrefix is allowed only for delegate.read"
            )
        if event["action"] in OPERATION_CHAIN_ACTIONS:
            _require_fields(
                event,
                position,
                (
                    "candidateRef",
                    "operationId",
                    "projectRef",
                    "targetRef",
                    "endpoint",
                ),
                label="operation binding",
            )
            _require_api_path(event, position)
        if event["action"] in {"write.dry-run", "project.write"}:
            _require_fields(
                event, position, ("requestDigest",), label="request digest binding"
            )
        if event["action"] in RUNTIME_BOUND_ACTIONS:
            _require_fields(
                event,
                position,
                (
                    "candidateRef",
                    "operationId",
                    "projectRef",
                    "targetRef",
                    "endpoint",
                    "requestDigest",
                ),
                label="runtime binding",
            )
            _require_api_path(event, position)
        if event["action"] == "verification.waiver":
            _require_fields(
                event, position, ("signal",), label="verification waiver reason"
            )
        if event["action"] == "audit.area":
            _require_fields(
                event,
                position,
                ("projectRef", "targetRef", "areaRef"),
                label="area audit binding",
            )
        if event["action"] == "audit.full":
            _require_fields(event, position, ("projectRef",), label="audit binding")
        if event["action"] in DISCOVERY_ACTIONS or event["action"] == "approval.server-readonly":
            _require_fields(
                event,
                position,
                ("projectRef", "targetRef"),
                label="discovery binding",
            )
        if event["action"] in {
            "approval.server-readonly",
            "discovery.inspect-server-readonly",
        }:
            _require_fields(
                event,
                position,
                ("endpoint", "requestDigest"),
                label="server-readonly request binding",
            )
            _require_api_path(event, position)
        if (
            event["action"] in DELEGATED_READ_ACTIONS
            and event["actor"] not in {coordinator, owner}
        ):
            _require_fields(
                event,
                position,
                ("endpointFamily", "endpoint"),
                label="delegated read endpoint family binding",
            )
            _require_api_path(event, position)
    serialized = json.dumps(trace, ensure_ascii=False, sort_keys=True)
    if text_contains_secret(serialized):
        raise WorkflowTraceError("workflow trace contains a recognized secret")
    return events


def validate_trace(trace: dict[str, Any]) -> dict[str, Any]:
    events = _validate_shape(trace)
    violations: list[dict[str, Any]] = []
    mutations = [event for event in events if event["action"] in MUTATION_ACTIONS]

    def add(code: str, step: int) -> None:
        item = {"code": code, "step": step}
        if item not in violations:
            violations.append(item)

    coordinator = trace["coordinatorOwner"]
    requested_audit = trace["requestedAuditScope"]
    resolution_events = [
        event for event in events if event["action"] == "known-path.resolve"
    ]
    successful_resolutions = [
        event
        for event in resolution_events
        if event["result"] in {"ok", "compatible"}
    ]
    conclusive_resolutions = [
        event
        for event in resolution_events
        if event["result"] in CONCLUSIVE_RESOLUTION_RESULTS
    ]
    compatibility_events = [
        event for event in events if event["action"] == "compatibility.check"
    ]
    exhausted_events = [
        event
        for event in events
        if event["action"] == "known-path.exhausted"
        and event["result"] == "exhausted"
    ]
    target_bind_events = [
        event for event in events if event["action"] == "target.bind"
    ]

    def same_candidate(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return (
            left.get("candidateRef") == right.get("candidateRef")
            and left.get("candidateSha256") == right.get("candidateSha256")
        )

    def same_scope(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return (
            left.get("projectRef") == right.get("projectRef")
            and left.get("targetRef") == right.get("targetRef")
        )

    def same_area(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return left.get("areaRef") == right.get("areaRef")

    def latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        return max(items, key=lambda item: item["step"]) if items else None

    def latest_resolution_for(event: dict[str, Any]) -> dict[str, Any] | None:
        return latest(
            [
                prior
                for prior in successful_resolutions
                if prior["step"] < event["step"]
                and prior.get("candidateRef") == event.get("candidateRef")
            ]
        )

    def latest_target_bind_before(event: dict[str, Any]) -> dict[str, Any] | None:
        return latest(
            [prior for prior in target_bind_events if prior["step"] < event["step"]]
        )

    def has_exact_successful_target_bind(event: dict[str, Any]) -> bool:
        binding = latest_target_bind_before(event)
        return (
            binding is not None
            and binding["result"] == "ok"
            and same_scope(binding, event)
        )

    revision_bound_actions = (
        OPERATION_CHAIN_ACTIONS
        | RUNTIME_BOUND_ACTIONS
        | DELEGATED_READ_ACTIONS
        | {"delegate.read", "probe.reconcile"}
    )
    for event in events:
        if event["action"] not in revision_bound_actions:
            continue
        if event.get("candidateRef") is None:
            continue
        selected = latest_resolution_for(event)
        if (
            selected is not None
            and selected["source"] in CARD_SOURCES
            and not same_candidate(selected, event)
        ):
            add("candidate_revision_not_bound", event["step"])

    for event in events:
        if event["action"] in ROUTE_DECISION_ACTIONS and event["actor"] != coordinator:
            add("route_decision_not_by_coordinator", event["step"])

    for event in events:
        if event["action"] != "knowledge.get-card":
            continue
        current_card_resolution = latest(
            [
                prior
                for prior in successful_resolutions
                if prior["step"] < event["step"]
                and prior["source"] in CARD_SOURCES
            ]
        )
        if (
            current_card_resolution is None
            or not same_candidate(current_card_resolution, event)
        ):
            add("card_read_without_current_resolution", event["step"])

    supplied_card = trace["suppliedCard"]
    supplied_resolution: dict[str, Any] | None = None
    supplied_route_resolutions = [
        event
        for event in resolution_events
        if event["source"] == "supplied-card"
    ]
    for repeated_resolution in supplied_route_resolutions[1:]:
        add(
            "supplied_card_resolved_more_than_once",
            repeated_resolution["step"],
        )
    if supplied_card is not None:
        if not resolution_events:
            add("supplied_card_not_checked_first", 0)
        else:
            first_resolution = min(resolution_events, key=lambda item: item["step"])
            exact_first = (
                first_resolution["source"] == "supplied-card"
                and first_resolution.get("candidateRef") == supplied_card["ref"]
                and first_resolution.get("candidateSha256")
                == supplied_card["sha256"]
            )
            if not exact_first:
                add("supplied_card_not_checked_first", first_resolution["step"])
            elif first_resolution["result"] not in {"ok", "compatible"}:
                add(
                    "supplied_card_not_successfully_resolved",
                    first_resolution["step"],
                )
            else:
                supplied_resolution = first_resolution

    if not resolution_events and (mutations or requested_audit is None):
        add("known_path_resolution_missing", 0)
    elif resolution_events and requested_audit is None:
        first_resolution_step = min(event["step"] for event in resolution_events)
        for event in events:
            if (
                event["action"] in BROAD_ACTIONS
                and event["step"] < first_resolution_step
            ):
                add("known_path_resolved_after_broad_read", event["step"])

    bound_compatibility_steps: set[int] = set()
    negative_compatibility_steps: set[int] = set()
    for event in compatibility_events:
        selected = latest_resolution_for(event)
        if selected is None or not same_candidate(selected, event):
            add("compatibility_without_successful_resolution", event["step"])
            continue
        fingerprint_events = [
            prior
            for prior in events
            if prior["action"] == "stand.fingerprint"
            and prior["step"] < event["step"]
            and prior.get("projectRef") == event.get("projectRef")
        ]
        current_fingerprint = latest(fingerprint_events)
        fingerprinted = (
            current_fingerprint is not None
            and current_fingerprint["result"] == "ok"
        )
        if not fingerprinted:
            add("compatibility_without_successful_fingerprint", event["step"])
        recipe_resolved = True
        if selected["source"] in CARD_SOURCES:
            card_reads = [
                prior
                for prior in events
                if selected["step"] < prior["step"] < event["step"]
                and prior["action"] == "knowledge.get-card"
                and same_candidate(prior, selected)
            ]
            current_card_read = latest(card_reads)
            recipe_resolved = (
                current_card_read is not None
                and current_card_read["result"] == "ok"
            )
            if not recipe_resolved:
                add("card_recipe_not_resolved", event["step"])
        explicitly_inapplicable = (
            event["result"] == "not-found"
            and event.get("signal") == "explicitly-inapplicable"
        )
        if event["result"] == "not-found" and not explicitly_inapplicable:
            add("inapplicable_route_without_explicit_signal", event["step"])
        if fingerprinted and recipe_resolved:
            bound_compatibility_steps.add(event["step"])
            if event["result"] == "mismatch" or explicitly_inapplicable:
                negative_compatibility_steps.add(event["step"])

    def failed_read_matches_route(
        event: dict[str, Any], route: dict[str, Any]
    ) -> bool:
        if not same_candidate(event, route) or not same_scope(event, route):
            return False
        route_operation = route.get("operationId")
        return route_operation is None or event.get("operationId") == route_operation

    def route_reopened_between(route: dict[str, Any], end_step: int) -> bool:
        return any(
            route["step"] < event["step"] < end_step
            and (
                (
                    event["action"] == "risk.signal"
                    and event["result"] == "ok"
                    and event.get("projectRef") == route.get("projectRef")
                    and (
                        event.get("targetRef") is None
                        or event.get("targetRef") == route.get("targetRef")
                    )
                )
                or (
                    event["action"]
                    in {"target.read", "dependency.read", "target.readback"}
                    and event["result"] == "failed"
                    and failed_read_matches_route(event, route)
                )
                or (
                    event["step"] in negative_compatibility_steps
                    and same_scope(event, route)
                )
            )
            for event in events
        )

    for resolution in resolution_events:
        prior_compatible = latest(
            [
                event
                for event in compatibility_events
                if event["step"] in bound_compatibility_steps
                and event["result"] == "compatible"
                and event["step"] < resolution["step"]
            ]
        )
        if prior_compatible is not None and not route_reopened_between(
            prior_compatible, resolution["step"]
        ):
            add("known_path_search_after_compatible_route", resolution["step"])

    def latest_bound_compatibility(
        event: dict[str, Any], *, after_step: int = 0
    ) -> dict[str, Any] | None:
        return latest(
            [
                prior
                for prior in compatibility_events
                if prior["step"] in bound_compatibility_steps
                and after_step < prior["step"] < event["step"]
                and same_candidate(prior, event)
                and same_scope(prior, event)
            ]
        )

    valid_exhaustion_steps: set[int] = set()
    for exhausted_event in exhausted_events:
        exhausted_step = exhausted_event["step"]
        valid = True
        if not has_exact_successful_target_bind(exhausted_event):
            add(
                "known_path_exhausted_without_successful_target_bind",
                exhausted_step,
            )
            valid = False
        prior_resolutions = [
            event
            for event in resolution_events
            if event["step"] < exhausted_step
        ]
        if not prior_resolutions:
            add("known_path_exhausted_without_resolution", exhausted_step)
            valid = False
        latest_prior_resolution = latest(prior_resolutions)
        if (
            latest_prior_resolution is None
            or latest_prior_resolution["result"]
            not in CONCLUSIVE_RESOLUTION_RESULTS
        ):
            add("known_path_exhausted_without_conclusive_resolution", exhausted_step)
            valid = False
        prior_valid_exhaustion = latest(
            [
                event
                for event in exhausted_events
                if event["step"] in valid_exhaustion_steps
                and event["step"] < exhausted_step
                and same_scope(event, exhausted_event)
            ]
        )
        if prior_valid_exhaustion is not None:
            reopen_events = [
                event
                for event in resolution_events
                if prior_valid_exhaustion["step"] < event["step"] < exhausted_step
            ] + [
                event
                for event in compatibility_events
                if prior_valid_exhaustion["step"] < event["step"] < exhausted_step
                and same_scope(event, exhausted_event)
            ]
            latest_reopen = latest(reopen_events)
            if latest_reopen is not None and not any(
                latest_reopen["step"] <= event["step"] < exhausted_step
                for event in conclusive_resolutions
            ):
                add("known_path_not_refined_after_reopen", exhausted_step)
                valid = False
        prior_successes = [
            event
            for event in successful_resolutions
            if event["step"] < exhausted_step
        ]
        if prior_successes:
            latest_success = max(prior_successes, key=lambda item: item["step"])
            route_probe = dict(latest_success)
            route_probe.update(
                {
                    "step": exhausted_step,
                    "projectRef": exhausted_event["projectRef"],
                    "targetRef": exhausted_event["targetRef"],
                }
            )
            current_check = latest_bound_compatibility(
                route_probe, after_step=latest_success["step"]
            )
            if current_check is None:
                add("known_path_exhausted_without_compatibility", exhausted_step)
                valid = False
            elif current_check["step"] not in negative_compatibility_steps:
                add("known_path_exhausted_without_mismatch", exhausted_step)
                valid = False
        prior_negative_checks = [
            event
            for event in compatibility_events
            if event["step"] in negative_compatibility_steps
            and event["step"] < exhausted_step
            and same_scope(event, exhausted_event)
        ]
        if prior_negative_checks:
            latest_negative_event = max(
                prior_negative_checks, key=lambda event: event["step"]
            )
            latest_negative = latest_negative_event["step"]
            if not any(
                latest_negative < event["step"] < exhausted_step
                and not (
                    event.get("candidateSha256") is not None
                    and latest_negative_event.get("candidateSha256") is not None
                    and event.get("candidateSha256")
                    == latest_negative_event.get("candidateSha256")
                )
                and not same_candidate(event, latest_negative_event)
                for event in conclusive_resolutions
            ):
                add("known_path_not_refined_after_mismatch", exhausted_step)
                valid = False
        if supplied_card is not None:
            exact_card_reads = [
                event
                for event in events
                if event["action"] == "knowledge.get-card"
                and event["result"] == "ok"
                and event["step"] < exhausted_step
                and supplied_resolution is not None
                and supplied_resolution["step"] < event["step"]
                and event.get("candidateRef") == supplied_card["ref"]
                and event.get("candidateSha256") == supplied_card["sha256"]
            ]
            if supplied_resolution is None or not exact_card_reads:
                add("supplied_card_not_inspected", exhausted_step)
                valid = False
            supplied_negative = any(
                event["step"] in negative_compatibility_steps
                and event["step"] < exhausted_step
                and event.get("candidateRef") == supplied_card["ref"]
                and event.get("candidateSha256") == supplied_card["sha256"]
                and same_scope(event, exhausted_event)
                for event in compatibility_events
            )
            if not supplied_negative:
                add("supplied_card_not_conclusively_disposed", exhausted_step)
                valid = False
        if valid:
            valid_exhaustion_steps.add(exhausted_step)

    if supplied_resolution is not None:
        route_changes = [
            event
            for event in resolution_events
            if event["step"] > supplied_resolution["step"]
        ]
        for route_change in route_changes:
            exact_read = any(
                event["action"] == "knowledge.get-card"
                and event["result"] == "ok"
                and supplied_resolution["step"] < event["step"] < route_change["step"]
                and same_candidate(event, supplied_resolution)
                for event in events
            )
            negative_disposition = any(
                event["step"] in negative_compatibility_steps
                and event["step"] < route_change["step"]
                and same_candidate(event, supplied_resolution)
                for event in compatibility_events
            )
            if not exact_read:
                add("supplied_card_not_inspected", route_change["step"])
            if not negative_disposition:
                add("supplied_card_not_conclusively_disposed", route_change["step"])
            break

    def valid_exhaustion_before(event: dict[str, Any]) -> dict[str, Any] | None:
        candidates = [
            prior
            for prior in exhausted_events
            if prior["step"] in valid_exhaustion_steps
            and prior["step"] < event["step"]
            and same_scope(prior, event)
        ]
        selected = latest(candidates)
        if selected is None:
            return None
        route_reopened = any(
            selected["step"] < prior["step"] < event["step"]
            for prior in resolution_events
        ) or any(
            selected["step"] < prior["step"] < event["step"]
            and same_scope(prior, event)
            for prior in compatibility_events
        )
        return None if route_reopened else selected

    active_mode = trace["mode"]
    active_mode_scope: tuple[str, str] | None = None
    mode_epoch = 0
    mode_at_step: dict[int, str] = {}
    mode_epoch_at_step: dict[int, int] = {}
    mode_scope_at_step: dict[int, tuple[str, str] | None] = {}
    discovery_entry_at_epoch: dict[int, dict[str, Any]] = {}
    valid_discovery_entry_steps: set[int] = set()
    direct_used = active_mode == "direct"
    for event in events:
        if event["action"] == "mode.enter":
            prior_mode = active_mode
            if event["toMode"] == active_mode:
                add("redundant_mode_transition", event["step"])
            if (
                prior_mode == "discovery"
                and active_mode_scope is not None
                and active_mode_scope
                != (event["projectRef"], event["targetRef"])
            ):
                add("mode_transition_scope_mismatch", event["step"])
            if event["toMode"] == "discovery":
                if not has_exact_successful_target_bind(event):
                    add("discovery_without_successful_target_bind", event["step"])
                if valid_exhaustion_before(event) is None:
                    add("discovery_before_known_path_exhausted", event["step"])
                else:
                    valid_discovery_entry_steps.add(event["step"])
            active_mode = event["toMode"]
            active_mode_scope = (event["projectRef"], event["targetRef"])
            mode_epoch += 1
            if active_mode == "discovery":
                discovery_entry_at_epoch[mode_epoch] = event
            if active_mode == "direct":
                direct_used = True
        mode_at_step[event["step"]] = active_mode
        mode_epoch_at_step[event["step"]] = mode_epoch
        mode_scope_at_step[event["step"]] = active_mode_scope
        if active_mode == "direct" and event["actor"] != coordinator:
            add("direct_mode_non_coordinator_actor", event["step"])

    if direct_used and trace["writerOwner"] != coordinator:
        add("direct_mode_single_owner_required", 0)

    for event in events:
        if event["action"] not in DISCOVERY_ACTIONS:
            continue
        epoch = mode_epoch_at_step[event["step"]]
        entry = discovery_entry_at_epoch.get(epoch)
        if not has_exact_successful_target_bind(event):
            add("discovery_without_successful_target_bind", event["step"])
        if valid_exhaustion_before(event) is None and (
            entry is None or entry["step"] in valid_discovery_entry_steps
        ):
            add("discovery_before_known_path_exhausted", event["step"])
        if mode_at_step[event["step"]] != "discovery":
            add("discovery_action_outside_discovery", event["step"])
        if mode_at_step[event["step"]] == "discovery" and (
            entry is None or not same_scope(entry, event)
        ):
            add("discovery_without_bound_mode_transition", event["step"])

    signal_events = [
        event
        for event in events
        if event["action"] == "risk.signal" and event["result"] == "ok"
    ]
    insufficiency_events = [
        event
        for event in events
        if event["action"] == "risk.signal"
        and event.get("signal") == "api-ui-insufficient"
    ]
    for signal in signal_events:
        if signal.get("signal") != "api-ui-insufficient":
            continue
        epoch = mode_epoch_at_step[signal["step"]]
        api = latest(
            [
                event
                for event in events
                if event["step"] < signal["step"]
                and event["action"] == "discovery.inspect-api"
                and same_scope(event, signal)
                and same_area(event, signal)
                and mode_epoch_at_step[event["step"]] == epoch
            ]
        )
        ui = latest(
            [
                event
                for event in events
                if event["step"] < signal["step"]
                and event["action"] == "discovery.inspect-ui-network"
                and same_scope(event, signal)
                and same_area(event, signal)
                and mode_epoch_at_step[event["step"]] == epoch
            ]
        )
        if (
            api is None
            or api["result"] != "ok"
            or ui is None
            or ui["result"] != "ok"
        ):
            add("api_ui_insufficient_before_bound_probes", signal["step"])

    for event in events:
        if event["action"] != "discovery.inspect-server-readonly":
            continue
        epoch = mode_epoch_at_step[event["step"]]
        api = latest(
            [
                prior
                for prior in events
                if prior["action"] == "discovery.inspect-api"
                and prior["step"] < event["step"]
                and same_scope(prior, event)
                and same_area(prior, event)
                and mode_epoch_at_step[prior["step"]] == epoch
            ]
        )
        ui = latest(
            [
                prior
                for prior in events
                if prior["action"] == "discovery.inspect-ui-network"
                and prior["step"] < event["step"]
                and same_scope(prior, event)
                and same_area(prior, event)
                and mode_epoch_at_step[prior["step"]] == epoch
            ]
        )
        minimum_signal_step = max(
            api["step"] if api is not None else 0,
            ui["step"] if ui is not None else 0,
        )
        insufficiency = latest(
            [
                prior
                for prior in insufficiency_events
                if prior.get("signal") == "api-ui-insufficient"
                and minimum_signal_step < prior["step"] < event["step"]
                and same_scope(prior, event)
                and same_area(prior, event)
                and mode_epoch_at_step[prior["step"]] == epoch
            ]
        )
        if (
            api is None
            or api["result"] != "ok"
            or ui is None
            or ui["result"] != "ok"
            or insufficiency is None
            or insufficiency["result"] != "ok"
        ):
            add("server_readonly_before_api_ui_exhausted", event["step"])
        approval = latest(
            [
                prior
                for prior in events
                if prior["action"] == "approval.server-readonly"
                and insufficiency is not None
                and insufficiency["step"] < prior["step"] < event["step"]
                and same_scope(prior, event)
                and same_area(prior, event)
                and prior.get("endpoint") == event.get("endpoint")
                and prior.get("requestDigest") == event.get("requestDigest")
                and mode_epoch_at_step[prior["step"]] == epoch
            ]
        )
        if approval is None or approval["result"] != "approved":
            add("server_readonly_without_exact_approval", event["step"])

    for event in events:
        if event["action"] not in AUDIT_ACTIONS:
            continue
        prior_signals = [
            signal
            for signal in signal_events
            if signal["step"] < event["step"]
            and signal.get("projectRef") == event.get("projectRef")
        ]
        if event["action"] == "audit.area":
            request_match = requested_audit is not None and (
                (
                    requested_audit["scope"] == "area"
                    and requested_audit["projectRef"] == event["projectRef"]
                    and requested_audit["targetRef"] == event["targetRef"]
                    and requested_audit["areaRef"] == event["areaRef"]
                )
                or (
                    requested_audit["scope"] == "full"
                    and requested_audit["projectRef"] == event["projectRef"]
                )
            )
            signal_match = any(
                signal["riskScope"] == "area"
                and signal.get("targetRef") == event.get("targetRef")
                and signal.get("areaRef") == event.get("areaRef")
                for signal in prior_signals
            )
            justified = request_match or signal_match
            violation = "area_audit_without_signal"
        else:
            justified = (
                requested_audit is not None
                and requested_audit["scope"] == "full"
                and requested_audit["projectRef"] == event["projectRef"]
            ) or any(
                signal["riskScope"] == "cross-area" for signal in prior_signals
            )
            violation = "full_audit_without_cross_area_signal"
        if not justified:
            add(violation, event["step"])
        if mode_at_step[event["step"]] == "direct":
            add("audit_in_direct_mode", event["step"])
        if trace["taskClass"] == "mechanical" and event["action"] == "audit.full":
            add("mechanical_direct_used_full_audit", event["step"])

    delegated = [event for event in events if event["action"] == "delegate.read"]
    probe_steps: dict[str, int] = {}
    successful_delegations: dict[tuple[str, str], dict[str, Any]] = {}
    for event in delegated:
        if event["actor"] != coordinator:
            add("delegation_not_issued_by_coordinator", event["step"])
        if mode_at_step[event["step"]] == "direct":
            add("direct_mode_delegated", event["step"])
        selected = latest_resolution_for(event)
        exact_current_route = selected is not None and same_candidate(selected, event)
        current_compatibility = (
            latest_bound_compatibility(event, after_step=selected["step"])
            if exact_current_route and selected is not None
            else None
        )
        compatible_route = (
            current_compatibility is not None
            and current_compatibility["result"] == "compatible"
        )
        exhausted_route = valid_exhaustion_before(event) is not None
        requested_route = False
        if requested_audit is not None:
            requested_route = (
                requested_audit["scope"] == "full"
                and requested_audit["projectRef"] == event["projectRef"]
            ) or (
                requested_audit["scope"] == "area"
                and requested_audit["projectRef"] == event["projectRef"]
                and requested_audit["targetRef"] == event["targetRef"]
                and event.get("areaRef") == requested_audit["areaRef"]
            )
        if not (compatible_route or exhausted_route or requested_route):
            add("delegation_before_route_decision", event["step"])
        probe_key = event["probeKey"]
        if probe_key in probe_steps:
            add("duplicate_probe_key", event["step"])
        else:
            probe_steps[probe_key] = event["step"]
        if event["assignee"] == trace["writerOwner"]:
            add("delegated_reader_is_writer", event["step"])
        if event["result"] == "ok" and event["actor"] == coordinator:
            saved = dict(event)
            saved["modeEpoch"] = mode_epoch_at_step[event["step"]]
            successful_delegations[(event["assignee"], probe_key)] = saved

    if trace["taskClass"] == "mechanical":
        if trace["mode"] != "direct":
            add("mechanical_requires_direct_mode", 0)
        for event in delegated:
            add("mechanical_direct_delegated", event["step"])
        for event in mutations:
            if event["action"] != "project.write":
                add("mechanical_forbids_runtime", event["step"])

    privileged_actors = {coordinator, trace["writerOwner"]}
    bound_delegated_results: list[dict[str, Any]] = []
    for event in events:
        if event["actor"] in privileged_actors:
            continue
        key = (event["actor"], event.get("probeKey"))
        delegation = successful_delegations.get(key)
        if (
            delegation is None
            or delegation["step"] >= event["step"]
            or event["action"] not in DELEGATED_READ_ACTIONS
            or event["action"] != delegation["allowedAction"]
            or mode_epoch_at_step[event["step"]] != delegation["modeEpoch"]
        ):
            add("reader_without_successful_delegation", event["step"])
            continue
        exact_scope = (
            not same_scope(event, delegation)
            or not same_candidate(event, delegation)
            or not same_area(event, delegation)
        )
        if exact_scope:
            add("delegated_read_scope_mismatch", event["step"])
        endpoint_family_matches = (
            event.get("endpointFamily") == delegation.get("endpointFamily")
        )
        if not endpoint_family_matches:
            add("delegated_read_endpoint_family_mismatch", event["step"])
        endpoint_prefix_matches = event.get("endpoint", "").startswith(
            delegation["endpointPrefix"]
        )
        if not endpoint_prefix_matches:
            add("delegated_read_endpoint_prefix_mismatch", event["step"])
        if not exact_scope and endpoint_family_matches and endpoint_prefix_matches:
            saved_result = dict(event)
            saved_result["modeEpoch"] = mode_epoch_at_step[event["step"]]
            bound_delegated_results.append(saved_result)

    bound_result_steps = {event["step"] for event in bound_delegated_results}
    usable_reconciliations: list[dict[str, Any]] = []
    for event in events:
        if event["action"] != "probe.reconcile":
            continue
        if event["actor"] != coordinator:
            add("probe_reconcile_not_by_coordinator", event["step"])
        epoch = mode_epoch_at_step[event["step"]]
        latest_probe_result = latest(
            [
                prior
                for prior in events
                if prior["step"] < event["step"]
                and prior["actor"] not in privileged_actors
                and prior["action"] in DELEGATED_READ_ACTIONS
                and prior.get("probeKey") == event.get("probeKey")
            ]
        )
        source_usable = (
            latest_probe_result is not None
            and latest_probe_result["step"] in bound_result_steps
            and latest_probe_result["result"] == "ok"
            and same_candidate(latest_probe_result, event)
            and same_scope(latest_probe_result, event)
            and same_area(latest_probe_result, event)
            and latest_probe_result.get("endpointFamily")
            == event.get("endpointFamily")
            and mode_epoch_at_step[latest_probe_result["step"]] == epoch
        )
        if not source_usable:
            add("probe_reconcile_without_usable_delegated_result", event["step"])
        if event["actor"] == coordinator and event["result"] == "ok" and source_usable:
            saved_reconciliation = dict(event)
            saved_reconciliation["modeEpoch"] = epoch
            usable_reconciliations.append(saved_reconciliation)
    usable_reconciliation_steps = {
        event["step"] for event in usable_reconciliations
    }

    if mutations and trace["writerOwner"] is None:
        add("writer_owner_missing", mutations[0]["step"])
    for event in events:
        if event["action"] == "write.dry-run" and (
            trace["writerOwner"] is None
            or event["actor"] != trace["writerOwner"]
        ):
            add("dry_run_owner_mismatch", event["step"])
    mutation_actors = {event["actor"] for event in mutations}
    if len(mutation_actors) > 1:
        add("multiple_writers", min(event["step"] for event in mutations))
    if trace["taskClass"] == "mechanical" and len(mutations) > 1:
        add("mechanical_multiple_mutations", mutations[1]["step"])
    for event in mutations:
        if mode_at_step[event["step"]] == "discovery":
            add("mutation_while_in_discovery", event["step"])
        if trace["writerOwner"] is not None and event["actor"] != trace["writerOwner"]:
            add("writer_owner_mismatch", event["step"])
        selected = latest_resolution_for(event)
        if selected is None:
            add("mutation_before_known_path_resolution", event["step"])
            current_compatibility = None
        elif not same_candidate(selected, event):
            current_compatibility = None
        else:
            current_compatibility = latest_bound_compatibility(
                event, after_step=selected["step"]
            )
        if (
            current_compatibility is None
            or current_compatibility["result"] != "compatible"
        ):
            add("mutation_before_compatibility", event["step"])
        latest_results_by_probe: dict[tuple[str, str], dict[str, Any]] = {}
        for delegated_result in bound_delegated_results:
            if (
                delegated_result["step"] < event["step"]
                and same_candidate(delegated_result, event)
                and same_scope(delegated_result, event)
                and delegated_result["modeEpoch"]
                == mode_epoch_at_step[event["step"]]
            ):
                result_key = (
                    delegated_result["probeKey"],
                    delegated_result["endpointFamily"],
                )
                latest_results_by_probe[result_key] = delegated_result
        for delegated_result in latest_results_by_probe.values():
            latest_reconciliation = latest(
                [
                    reconciliation
                    for reconciliation in events
                    if reconciliation["action"] == "probe.reconcile"
                    and delegated_result["step"]
                    < reconciliation["step"]
                    < event["step"]
                    and reconciliation.get("probeKey")
                    == delegated_result["probeKey"]
                    and reconciliation.get("endpointFamily")
                    == delegated_result["endpointFamily"]
                    and same_candidate(reconciliation, delegated_result)
                    and same_scope(reconciliation, delegated_result)
                    and same_area(reconciliation, delegated_result)
                    and mode_epoch_at_step[reconciliation["step"]]
                    == delegated_result["modeEpoch"]
                ]
            )
            reconciled = (
                latest_reconciliation is not None
                and latest_reconciliation["step"] in usable_reconciliation_steps
            )
            if delegated_result["result"] != "ok" or not reconciled:
                add("delegated_evidence_not_reconciled", event["step"])

    mutation_keys: dict[tuple[Any, ...], list[int]] = {}
    for event in mutations:
        key = (
            event.get("candidateRef"),
            event.get("candidateSha256"),
            event.get("operationId"),
            event.get("projectRef"),
            event.get("targetRef"),
        )
        mutation_keys.setdefault(key, []).append(event["step"])
    for steps in mutation_keys.values():
        if len(steps) > 1:
            add("mutation_retried", steps[1])

    def same_operation(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return (
            same_candidate(left, right)
            and left.get("operationId") == right.get("operationId")
            and same_scope(left, right)
        )

    for event in events:
        if event["action"] != "target.read":
            continue
        prior_write = latest(
            [
                prior
                for prior in events
                if prior["action"] == "project.write"
                and prior["step"] < event["step"]
                and same_scope(prior, event)
            ]
        )
        if prior_write is None:
            continue
        prior_readback = latest(
            [
                prior
                for prior in events
                if prior["action"] == "target.readback"
                and prior_write["step"] < prior["step"] < event["step"]
                and same_operation(prior, prior_write)
            ]
        )
        if prior_readback is None or prior_readback["result"] != "ok":
            add("target_read_before_prior_write_readback", event["step"])

    for event in events:
        if event["action"] == "project.write":
            chain_reads = [
                prior
                for prior in events
                if prior["action"] == "target.read"
                and prior["step"] < event["step"]
                and same_operation(prior, event)
            ]
            current_read = latest(chain_reads)
            read_ok = current_read is not None and current_read["result"] == "ok"
            latest_prior_mutation = latest(
                [
                    prior
                    for prior in mutations
                    if prior["step"] < event["step"] and same_scope(prior, event)
                ]
            )
            read_is_fresh_after_mutation = (
                latest_prior_mutation is None
                or (
                    current_read is not None
                    and current_read["step"] > latest_prior_mutation["step"]
                )
            )
            selected = latest_resolution_for(event)
            compatibility = (
                latest_bound_compatibility(event, after_step=selected["step"])
                if selected is not None and same_candidate(selected, event)
                else None
            )
            if (
                not read_ok
                or not read_is_fresh_after_mutation
                or compatibility is None
                or compatibility["step"] >= current_read["step"]
            ):
                add("project_write_without_successful_bound_read", event["step"])
            dry_runs = [
                prior
                for prior in events
                if prior["action"] == "write.dry-run"
                and prior["step"] < event["step"]
                and same_operation(prior, event)
                and prior.get("endpoint") == event.get("endpoint")
                and prior.get("requestDigest") == event.get("requestDigest")
            ]
            current_dry_run = latest(dry_runs)
            if (
                current_dry_run is None
                or current_dry_run["result"] != "ok"
                or not read_ok
                or current_read["step"] >= current_dry_run["step"]
            ):
                add("project_write_without_bound_dry_run", event["step"])
            read_backs = [
                later
                for later in events
                if later["action"] == "target.readback"
                and later["step"] > event["step"]
                and same_operation(later, event)
            ]
            current_read_back = latest(read_backs)
            if current_read_back is None or current_read_back["result"] != "ok":
                add(
                    "project_write_without_successful_bound_readback",
                    event["step"],
                )
        if event["action"] == "runtime.execute":
            approvals = [
                prior
                for prior in events
                if prior["action"] == "approval.runtime"
                and prior["step"] < event["step"]
                and same_operation(prior, event)
                and prior.get("endpoint") == event.get("endpoint")
                and prior.get("requestDigest") == event.get("requestDigest")
            ]
            approval = latest(approvals)
            selected = latest_resolution_for(event)
            compatibility = (
                latest_bound_compatibility(event, after_step=selected["step"])
                if selected is not None and same_candidate(selected, event)
                else None
            )
            if (
                approval is None
                or approval["result"] != "approved"
                or compatibility is None
                or compatibility["step"] >= approval["step"]
            ):
                add("runtime_approval_missing_or_mismatched", event["step"])
            verifications = [
                later
                for later in events
                if later["action"] == "runtime.verify"
                and later["step"] > event["step"]
                and same_operation(later, event)
                and later.get("endpoint") == event.get("endpoint")
                and later.get("requestDigest") == event.get("requestDigest")
            ]
            verification = latest(verifications)
            verified = verification is not None and verification["result"] == "ok"
            waivers = [
                prior
                for prior in events
                if prior["action"] == "verification.waiver"
                and prior["step"] < event["step"]
                and same_operation(prior, event)
                and prior.get("endpoint") == event.get("endpoint")
                and prior.get("requestDigest") == event.get("requestDigest")
                and bool(prior.get("signal"))
            ]
            waiver = latest(waivers)
            waived = waiver is not None and waiver["result"] == "approved"
            if not (verified or waived):
                add("runtime_verification_missing", event["step"])

    efficiency_warnings = []
    if trace["taskClass"] == "mechanical":
        for action in ("target.read", "target.readback", "dependency.read"):
            reads = [event for event in events if event["action"] == action]
            unreasoned = [
                event for event in reads[1:] if not event.get("signal", "").strip()
            ]
            if unreasoned:
                efficiency_warnings.append(
                    {
                        "code": "mechanical_read_budget_exceeded",
                        "step": unreasoned[0]["step"],
                        "action": action,
                        "budget": 1,
                        "readCount": len(reads),
                        "unreasonedExtraReadCount": len(unreasoned),
                    }
                )

    violations.sort(key=lambda item: (item["step"], item["code"]))
    return {
        "format": "teamvalue.ks-workflow-trace-validation",
        "formatVersion": TRACE_VERSION,
        "scope": "workflow-policy-only",
        "policyValid": not violations,
        "violations": violations,
        "efficiencyWarnings": efficiency_warnings,
        "provesTaskCompletion": False,
        "offlineOnly": True,
        "authorizesExecution": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a normalized KS workflow policy trace offline."
    )
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = read_json_relative(args.input_root, args.input, label="trace")
        if not isinstance(value, dict):
            raise WorkflowTraceError("workflow trace must be a JSON object")
        result = validate_trace(value)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["policyValid"] else 3
    except (SafePathError, WorkflowTraceError, OSError, ValueError) as exc:
        message = redact_text(str(exc)).replace(str(Path.home()), "~")
        raise SystemExit(f"workflow trace validation failed: {message}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
