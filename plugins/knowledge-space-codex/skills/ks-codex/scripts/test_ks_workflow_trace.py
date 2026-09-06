#!/usr/bin/env python3
"""Behavioral contracts for known-path-first KS workflow policy traces."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import ks_workflow_trace as workflow


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / (
    "workflow-trace-scenarios.json"
)


class WorkflowTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        defaults = cls.corpus["traceDefaults"]
        for case in cls.corpus["cases"]:
            trace = copy.deepcopy(defaults)
            trace.update(case["trace"])
            case["trace"] = trace

    def _case(self, case_id: str) -> dict[str, object]:
        return next(
            item for item in self.corpus["cases"] if item["id"] == case_id
        )

    def test_scenario_corpus_has_stable_unique_cases(self) -> None:
        self.assertEqual(
            self.corpus["format"],
            "teamvalue.ks-workflow-trace-scenarios",
        )
        self.assertEqual(self.corpus["formatVersion"], "1.2")
        case_ids = [case["id"] for case in self.corpus["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertEqual(
            set(case_ids),
            {
                "supplied-card-mechanical-direct",
                "bundled-pattern-mechanical-direct",
                "broad-read-before-known-path",
                "mechanical-unjustified-full-audit",
                "mismatch-refined-then-discovery",
                "premature-discovery",
                "parallel-readers-single-writer",
                "duplicate-probe-key",
                "direct-mode-delegation",
                "two-writers",
                "runtime-with-exact-approval",
                "runtime-with-mismatched-approval",
                "runtime-with-explicit-verification-waiver",
                "runtime-without-verification",
                "mechanical-class-cannot-run-runtime",
                "full-audit-after-cross-area-risk",
                "explicit-full-audit",
                "area-request-does-not-authorize-full",
                "discovery-cannot-write-before-mode-switch",
                "discovery-switches-to-coordinated-before-write",
                "discovery-action-hidden-in-coordinated",
                "failed-read-before-write",
                "failed-readback",
                "mechanical-second-write",
                "one-read-two-writes",
                "audit-then-mutation-without-known-path",
                "delegation-before-route-decision",
                "failed-delegation-does-not-authorize-reader",
                "blocked-precondition-stops-without-discovery",
                "area-audit-after-exhaustion",
                "supplied-card-cannot-be-skipped",
                "failed-resolution-cannot-pass-compatibility",
                "successful-route-needs-compatibility-before-exhaustion",
                "compatible-route-cannot-be-declared-exhausted",
                "latest-mismatch-invalidates-old-compatibility",
                "compatibility-before-resolution",
                "private-card-requires-full-recipe",
                "cross-project-signal-cannot-authorize-full-audit",
                "server-readonly-requires-api-ui-exhaustion",
                "server-readonly-after-api-ui-exhaustion",
                "card-hash-swap-at-compatibility",
                "new-card-revision-invalidates-compatibility",
                "supplied-card-missing-inspection-before-exhaustion",
                "failed-refinement-does-not-exhaust",
                "failed-resolution-does-not-exhaust",
                "blocked-resolution-does-not-exhaust",
                "unknown-resolution-does-not-exhaust",
                "cross-project-discovery-transition",
                "cross-target-discovery-transition",
                "stale-exhaustion-after-compatible-route",
                "direct-writer-must-be-coordinator",
                "delegation-invalidated-inside-direct-epoch",
                "delegation-invalidated-after-direct-epoch",
                "dry-run-before-read",
                "requested-area-cross-project",
                "requested-area-cross-area",
                "server-readonly-without-approval",
                "delegated-card-hash-mismatch",
                "delegated-read-action-mismatch",
                "api-ui-signal-before-ui-probe",
                "server-readonly-crosses-mode-epoch",
                "latest-failed-read-invalidates-ok-read",
                "latest-failed-dry-run-invalidates-ok-dry-run",
                "latest-failed-readback-invalidates-ok-readback",
                "route-decision-must-be-coordinator-owned",
                "explicitly-inapplicable-card-can-refine",
                "card-hash-required-on-read-only-operation",
                "same-supplied-card-does-not-refine",
                "successful-resolution-reopens-exhaustion",
                "mismatch-reopens-exhaustion",
                "fresh-exhaustion-after-route-reopen",
                "failed-target-bind-does-not-authorize-exhaustion",
                "failed-target-bind-does-not-authorize-discovery",
                "card-read-must-match-latest-resolution",
                "search-after-compatible-route",
                "compatible-route-reopened-by-risk",
                "mutation-retry-with-different-endpoint",
                "mutation-retry-with-different-digest",
                "latest-blocked-api-probe-does-not-escalate",
                "latest-failed-insufficiency-signal-does-not-escalate",
                "server-approval-endpoint-mismatch",
                "server-approval-digest-mismatch",
                "server-approval-area-mismatch",
                "delegated-endpoint-family-mismatch",
                "delegated-evidence-requires-reconciliation",
                "runtime-verify-endpoint-mismatch",
                "supplied-card-second-resolution-forbidden",
                "card-alias-same-sha-does-not-refine",
                "card-alias-new-sha-can-refine",
                "blocked-resolution-invalidates-exhaustion",
                "fresh-exhaustion-after-blocked-resolution",
                "latest-inconclusive-lookup-prevents-exhaustion",
                "unrelated-read-failure-does-not-reopen-route",
                "exact-read-failure-reopens-route",
                "different-operation-failure-does-not-reopen-route",
                "write-cannot-reuse-read-before-prior-mutation",
                "sequential-writes-use-fresh-read-after-readback",
                "next-read-requires-prior-write-readback",
                "later-blocked-reconciliation-invalidates-success",
                "later-ok-reconciliation-restores-success",
                "delegated-endpoint-prefix-mismatch",
            },
        )

    def test_behavioral_scenarios_validate_expected_policy(self) -> None:
        for case in self.corpus["cases"]:
            with self.subTest(case=case["id"]):
                result = workflow.validate_trace(case["trace"])
                self.assertEqual(
                    result["policyValid"],
                    case["expected"]["policyValid"],
                )
                self.assertEqual(
                    [item["code"] for item in result["violations"]],
                    case["expected"]["violationCodes"],
                )
                self.assertEqual(result["scope"], "workflow-policy-only")
                self.assertFalse(result["provesTaskCompletion"])
                self.assertTrue(result["offlineOnly"])
                self.assertFalse(result["authorizesExecution"])

    def test_unknown_actions_and_non_increasing_steps_fail_closed(self) -> None:
        base = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        base["events"][0]["action"] = "invent.solution"
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "action is invalid"):
            workflow.validate_trace(base)

        base = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        base["events"][1]["step"] = base["events"][0]["step"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "strictly increasing"):
            workflow.validate_trace(base)

    def test_mechanical_repeated_reads_exceed_efficiency_budget(self) -> None:
        trace = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        events = trace["events"]
        read_index = next(
            index for index, event in enumerate(events)
            if event["action"] == "target.read"
        )
        events[read_index + 1:read_index + 1] = [
            copy.deepcopy(events[read_index]) for _ in range(99)
        ]
        for step, event in enumerate(events, start=1):
            event["step"] = step

        result = workflow.validate_trace(trace)
        self.assertTrue(result["policyValid"])
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["efficiencyWarnings"], [{
            "code": "mechanical_read_budget_exceeded",
            "step": events[read_index + 1]["step"],
            "action": "target.read",
            "budget": 1,
            "readCount": 100,
            "unreasonedExtraReadCount": 99,
        }])

    def test_mechanical_extra_read_requires_its_own_nonblank_reason(self) -> None:
        for signal, warning_expected in (
            ("Verify button text after the response omitted that field", False),
            ("   ", True),
        ):
            with self.subTest(signal=signal):
                trace = copy.deepcopy(
                    self._case("supplied-card-mechanical-direct")["trace"]
                )
                events = trace["events"]
                read_index = next(
                    index for index, event in enumerate(events)
                    if event["action"] == "target.read"
                )
                extra_read = copy.deepcopy(events[read_index])
                extra_read["signal"] = signal
                events.insert(read_index + 1, extra_read)
                for step, event in enumerate(events, start=1):
                    event["step"] = step

                result = workflow.validate_trace(trace)
                self.assertTrue(result["policyValid"])
                self.assertEqual(bool(result["efficiencyWarnings"]), warning_expected)
                if warning_expected:
                    self.assertEqual(
                        result["efficiencyWarnings"][0]["step"], extra_read["step"]
                    )
                trace["events"] = [
                    event for event in events if event["action"] != "target.readback"
                ]
                self.assertFalse(workflow.validate_trace(trace)["policyValid"])

    def test_runtime_approval_is_bound_to_exact_execution(self) -> None:
        case = self._case("runtime-with-exact-approval")
        for field, replacement in (
            ("candidateRef", "other-route"),
            ("operationId", "other-operation"),
            ("projectRef", "project-b"),
            ("targetRef", "integration-b"),
            ("endpoint", "/bpms/start"),
            ("requestDigest", "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"),
        ):
            trace = copy.deepcopy(case["trace"])
            approval = next(
                event
                for event in trace["events"]
                if event["action"] == "approval.runtime"
            )
            approval[field] = replacement
            with self.subTest(field=field):
                result = workflow.validate_trace(trace)
                self.assertFalse(result["policyValid"])
                self.assertIn(
                    "runtime_approval_missing_or_mismatched",
                    [item["code"] for item in result["violations"]],
                )

    def test_mutations_and_runtime_approval_require_exact_binding_fields(self) -> None:
        case = self._case("runtime-with-exact-approval")
        for action in ("approval.runtime", "runtime.execute"):
            for field in (
                "candidateRef",
                "operationId",
                "projectRef",
                "targetRef",
                "endpoint",
                "requestDigest",
            ):
                trace = copy.deepcopy(case["trace"])
                event = next(
                    item for item in trace["events"] if item["action"] == action
                )
                del event[field]
                with self.subTest(action=action, field=field):
                    with self.assertRaisesRegex(
                        workflow.WorkflowTraceError,
                        "runtime binding is missing",
                    ):
                        workflow.validate_trace(trace)

    def test_project_reads_and_writes_require_target_binding(self) -> None:
        case = self._case("supplied-card-mechanical-direct")
        for action in (
            "target.read",
            "write.dry-run",
            "project.write",
            "target.readback",
        ):
            for field in (
                "candidateRef",
                "operationId",
                "projectRef",
                "targetRef",
                "endpoint",
            ):
                trace = copy.deepcopy(case["trace"])
                event = next(
                    item for item in trace["events"] if item["action"] == action
                )
                del event[field]
                with self.subTest(action=action, field=field):
                    with self.assertRaisesRegex(
                        workflow.WorkflowTraceError,
                        "binding is missing",
                    ):
                        workflow.validate_trace(trace)

    def test_known_path_source_and_delegate_contract_fail_closed(self) -> None:
        trace = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        resolve = next(
            event
            for event in trace["events"]
            if event["action"] == "known-path.resolve"
        )
        del resolve["source"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "source is required"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        delegated = next(
            event for event in trace["events"] if event["action"] == "delegate.read"
        )
        delegated["noWrite"] = False
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "noWrite=true"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        delegated = next(
            event for event in trace["events"] if event["action"] == "delegate.read"
        )
        del delegated["allowedAction"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "allowedAction"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        delegated = next(
            event for event in trace["events"] if event["action"] == "delegate.read"
        )
        del delegated["endpointFamily"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "endpointFamily"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        delegated = next(
            event for event in trace["events"] if event["action"] == "delegate.read"
        )
        del delegated["endpointPrefix"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "endpointPrefix"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        delegated = next(
            event for event in trace["events"] if event["action"] == "delegate.read"
        )
        delegated["endpointPrefix"] = "/"
        with self.assertRaisesRegex(
            workflow.WorkflowTraceError,
            "deterministic absolute API prefix",
        ):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        reader = next(
            event for event in trace["events"] if event["actor"] == "reader-a"
        )
        del reader["endpointFamily"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "endpoint family"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        reader = next(
            event for event in trace["events"] if event["actor"] == "reader-a"
        )
        del reader["endpoint"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "endpoint family"):
            workflow.validate_trace(trace)

    def test_mode_transition_and_card_recipe_contract_fail_closed(self) -> None:
        trace = copy.deepcopy(
            self._case("discovery-switches-to-coordinated-before-write")["trace"]
        )
        transition = next(
            event for event in trace["events"] if event["action"] == "mode.enter"
        )
        del transition["toMode"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "valid toMode"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        trace["events"] = [
            event
            for event in trace["events"]
            if event["action"] != "knowledge.get-card"
        ]
        result = workflow.validate_trace(trace)
        self.assertFalse(result["policyValid"])
        self.assertIn(
            "card_recipe_not_resolved",
            [item["code"] for item in result["violations"]],
        )

    def test_hash_and_digest_fields_are_strict_sha256(self) -> None:
        trace = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        write = next(
            event for event in trace["events"] if event["action"] == "project.write"
        )
        write["requestDigest"] = "not-a-digest"
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "lowercase SHA-256"):
            workflow.validate_trace(trace)

    def test_bound_audit_and_action_results_fail_closed(self) -> None:
        trace = copy.deepcopy(
            self._case("supplied-card-mechanical-direct")["trace"]
        )
        trace["requestedAuditScope"] = "area"
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "bound object"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("runtime-with-exact-approval")["trace"])
        approval = next(
            event
            for event in trace["events"]
            if event["action"] == "approval.runtime"
        )
        approval["result"] = "ok"
        with self.assertRaisesRegex(
            workflow.WorkflowTraceError, "invalid for approval.runtime"
        ):
            workflow.validate_trace(trace)

    def test_discovery_mode_and_server_approval_require_exact_scope(self) -> None:
        trace = copy.deepcopy(
            self._case("server-readonly-after-api-ui-exhaustion")["trace"]
        )
        transition = next(
            event
            for event in trace["events"]
            if event["action"] == "mode.enter"
            and event["toMode"] == "discovery"
        )
        del transition["targetRef"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "mode scope"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(
            self._case("server-readonly-after-api-ui-exhaustion")["trace"]
        )
        approval = next(
            event
            for event in trace["events"]
            if event["action"] == "approval.server-readonly"
        )
        del approval["targetRef"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "discovery binding"):
            workflow.validate_trace(trace)

    def test_mismatch_reconciliation_and_server_request_shapes_fail_closed(self) -> None:
        trace = copy.deepcopy(
            self._case("same-supplied-card-does-not-refine")["trace"]
        )
        mismatch = next(
            event
            for event in trace["events"]
            if event["action"] == "compatibility.check"
        )
        del mismatch["signal"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "mismatch reason"):
            workflow.validate_trace(trace)

        trace = copy.deepcopy(self._case("parallel-readers-single-writer")["trace"])
        reconciliation = next(
            event for event in trace["events"] if event["action"] == "probe.reconcile"
        )
        del reconciliation["endpointFamily"]
        with self.assertRaisesRegex(workflow.WorkflowTraceError, "reconciliation"):
            workflow.validate_trace(trace)

        for field in ("endpoint", "requestDigest"):
            trace = copy.deepcopy(
                self._case("server-readonly-after-api-ui-exhaustion")["trace"]
            )
            approval = next(
                event
                for event in trace["events"]
                if event["action"] == "approval.server-readonly"
            )
            del approval[field]
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    workflow.WorkflowTraceError,
                    "server-readonly request binding",
                ):
                    workflow.validate_trace(trace)


if __name__ == "__main__":
    unittest.main()
