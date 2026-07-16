#!/usr/bin/env python3
"""Focused regressions for KS safety classification, secrets, and read-back."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ks_approved_runtime_execute as runtime_executor  # noqa: E402
import ks_safe_patch_execute as safe_executor  # noqa: E402
from ks_approved_runtime_execute import (  # noqa: E402
    apply_payload_env,
    execute_runtime,
    operation_gate as runtime_operation_gate,
    payload_env_paths,
    payload_secret_findings,
    redact_secret_text,
    write_json as write_runtime_json,
)
from ks_readback_checks import (  # noqa: E402
    ReadBackCheckError,
    evaluate_readback_checks,
)
from ks_safe_patch_execute import execute_project_write  # noqa: E402
from ks_safe_patch_execute import operation_gate as project_operation_gate  # noqa: E402
from ks_safe_patch_lint import (  # noqa: E402
    approval_matches,
    classify_operation,
    get_operations,
    lint,
)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, endpoint, payload, **kwargs):
        self.calls.append((endpoint, payload, kwargs))
        if not self.responses:
            raise AssertionError("unexpected KS API call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RiskClassificationTests(unittest.TestCase):
    def test_external_queries_backup_save_and_upload_use_runtime_gate(self):
        expectations = {
            "/integrator/get-db-fields": "external_or_runtime",
            "/integrator/get-custom-query-results": "external_or_runtime",
            "/backups/save": "external_or_runtime",
            "/files/upload": "external_or_runtime",
            "/backups/load": "destructive_or_global",
            "/files/get-by-ids": "read_only",
        }
        for endpoint, expected in expectations.items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(classify_operation({"endpoint": endpoint}), expected)

    def test_runtime_prefixes_cannot_hide_destructive_suffixes(self):
        expectations = {
            "/files/upload-force": "external_or_runtime",
            "/files/upload/delete": "destructive_or_global",
            "/files/upload-delete": "destructive_or_global",
            "/integrator/get-db-fields/delete": "destructive_or_global",
            "/backups/save": "external_or_runtime",
            "/backups/load": "destructive_or_global",
            "/backups/save/load": "destructive_or_global",
        }
        for endpoint, expected in expectations.items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(classify_operation({"endpoint": endpoint}), expected)

    def test_mixed_read_write_markers_never_classify_as_read_only(self):
        expectations = {
            "/models/get-and-update": "project_write",
            "/tasks/get-and-complete": "external_or_runtime",
            "/integrator/get-fields-and-update": "project_write",
            "/files/get-and-upload": "external_or_runtime",
        }
        for endpoint, expected in expectations.items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(classify_operation({"endpoint": endpoint}), expected)

    def test_approval_requires_boolean_true_and_string_arrays(self):
        operation = {"id": "approved-op", "endpoint": "/models/update"}
        self.assertFalse(
            approval_matches(
                operation,
                {"userApproved": "false", "approvedOperationIds": ["approved-op"]},
            )
        )
        self.assertFalse(
            approval_matches(
                operation,
                {"userApproved": True, "approvedOperationIds": "approved-op"},
            )
        )
        self.assertTrue(
            approval_matches(
                operation,
                {"userApproved": True, "approvedOperationIds": ["approved-op"]},
            )
        )

    def test_operation_ids_reject_traversal_absolute_and_duplicates(self):
        for operation_id in ("../escaped", "/absolute", "nested/path", "with.dot"):
            with self.subTest(operation_id=operation_id), self.assertRaises(SystemExit):
                get_operations({"operations": [{"id": operation_id}]})
        with self.assertRaises(SystemExit):
            get_operations({"operations": [{"id": "same"}, {"id": "same"}]})
        with self.assertRaises(SystemExit):
            get_operations({"operations": [{"id": "CaseID"}, {"id": "caseid"}]})

    def test_explicit_non_executable_draft_stays_blocked_after_payload_is_added(self):
        operation = {
            "id": "draft-operation",
            "endpoint": "/dashboards/update",
            "payload": {},
            "readBefore": {"endpoint": "/dashboards/get-by-id"},
            "readBack": {"endpoint": "/dashboards/get-by-id"},
            "executionReady": False,
            "blockingReason": "full payload and machine checks are not reviewed",
        }
        plan = {
            "metadata": {
                "mode": "execute_project_writes",
                "targetProjectUuid": "00000000-0000-4000-8000-000000000001",
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [operation["id"]],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": [operation],
        }
        _risk, issues = project_operation_gate(operation, plan, execute=True)
        self.assertIn(
            "operation is an explicit non-executable draft (executionReady=false)",
            issues,
        )
        report, blocking = lint(plan)
        self.assertGreater(blocking, 0)
        self.assertIn("executionReady=false", report)

    def test_direct_runtime_rejects_unsafe_id_before_any_file_or_api_call(self):
        client = FakeClient([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "out"
            operation = {
                "id": "../escaped",
                "endpoint": "/integrator/check-connection",
                "payload": {},
                "verificationWaiver": "Synthetic direct-call regression.",
            }
            with self.assertRaisesRegex(RuntimeError, "operation id must match"):
                execute_runtime(client, operation, base_dir=root, out_dir=out_dir)
            self.assertFalse((root / "escaped_runtime_response.json").exists())
            self.assertEqual(client.calls, [])

    def test_project_write_without_explicit_payload_is_blocked(self):
        operation = {
            "id": "draft-write",
            "endpoint": "/dashboards/update",
            "entityUuid": "dashboard-1",
            "payloadBuildHint": "construct the full dashboard payload",
            "readBefore": {"endpoint": "/dashboards/get-by-id"},
            "readBack": {"endpoint": "/dashboards/get-by-id"},
        }
        plan = {
            "metadata": {
                "mode": "execute_project_writes",
                "targetProjectUuid": "00000000-0000-4000-8000-000000000001",
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": ["draft-write"],
            },
            "operations": [operation],
        }
        _risk, issues = project_operation_gate(operation, plan, execute=True)
        self.assertIn("project_write requires an explicit payload or payloadPath", issues)
        report, blocking = lint(plan)
        self.assertGreater(blocking, 0)
        self.assertIn("no explicit payload/payloadPath", report)

    def test_nested_request_payload_does_not_bypass_project_or_runtime_gate(self):
        project_operation = {
            "id": "nested-project",
            "endpoint": "/dashboards/update",
            "request": {"payload": {"name": "not-read-by-executor"}},
            "readBefore": {"endpoint": "/dashboards/get-by-id"},
            "readBack": {"endpoint": "/dashboards/get-by-id"},
        }
        project_plan = {
            "metadata": {"mode": "execute_project_writes"},
            "approval": {
                "userApproved": True,
                "approvedOperationIds": ["nested-project"],
            },
        }
        _risk, project_issues = project_operation_gate(
            project_operation, project_plan, execute=True
        )
        self.assertIn(
            "project_write requires an explicit payload or payloadPath",
            project_issues,
        )

        runtime_operation = {
            "id": "nested-runtime",
            "endpoint": "/integrator/check-connection",
            "request": {"payload": {"source": "not-read-by-executor"}},
            "readBack": {"endpoint": "/integrator/get-by-id"},
            "expectedEffect": "connection is checked",
        }
        runtime_plan = {
            "metadata": {"mode": "approved_runtime"},
            "approval": {
                "userApproved": True,
                "approvedOperationIds": ["nested-runtime"],
            },
        }
        _risk, runtime_issues = runtime_operation_gate(
            runtime_operation, runtime_plan, execute=True
        )
        self.assertIn(
            "runtime operation requires an explicit payload or payloadPath",
            runtime_issues,
        )

    def test_runtime_descriptive_readback_requires_documented_waiver(self):
        operation = {
            "id": "runtime-text-readback",
            "endpoint": "/integrator/check-connection",
            "payload": {},
            "readBack": "verify later",
            "expectedEffect": "connection is checked",
        }
        plan = {
            "metadata": {"mode": "approved_runtime"},
            "approval": {
                "userApproved": True,
                "approvedOperationIds": ["runtime-text-readback"],
            },
        }
        _risk, issues = runtime_operation_gate(operation, plan, execute=True)
        self.assertIn(
            "runtime operation needs an executable readBack/verification endpoint or a documented verificationWaiver",
            issues,
        )
        operation["verificationWaiver"] = {
            "reason": "Endpoint has no stable read API; inspect the persisted response manually."
        }
        _risk, waived_issues = runtime_operation_gate(operation, plan, execute=True)
        self.assertNotIn(
            "runtime operation needs an executable readBack/verification endpoint or a documented verificationWaiver",
            waived_issues,
        )

    def test_execute_main_blocks_lint_findings_before_client_creation(self):
        project_uuid = "00000000-0000-4000-8000-000000000001"
        operation = {
            "id": "runtime-lint-block",
            "endpoint": "/integrator/check-connection",
            "payload": {},
            "verificationWaiver": "Synthetic endpoint has no read-back.",
            "expectedEffect": "connection is checked",
        }
        plan = {
            "metadata": {
                "mode": "approved_runtime",
                "targetProjectUuid": project_uuid,
                "baseUrl": "https://ks.example.invalid/api",
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [operation["id"]],
                "approvedEndpoints": "not-an-array",
            },
            "operations": [operation],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            out_dir = root / "out"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = ["ks_approved_runtime_execute.py", str(plan_path), "--execute", "--out-dir", str(out_dir)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                runtime_executor.KSClient, "from_env"
            ) as from_env:
                exit_code = runtime_executor.main()
            report = json.loads(
                (out_dir / "runtime_execution_report.json").read_text(encoding="utf-8")
            )
        self.assertEqual(exit_code, 1)
        from_env.assert_not_called()
        self.assertEqual(report["operations"][0]["status"], "denied")
        self.assertGreater(report["lintBlockingFindings"], 0)

    def test_runtime_failure_marks_following_operation_not_executed(self):
        project_uuid = "00000000-0000-4000-8000-000000000001"
        operations = [
            {
                "id": "runtime-first",
                "endpoint": "/integrator/check-connection",
                "payload": {},
                "verificationWaiver": "Synthetic failure regression.",
                "expectedEffect": "first call",
            },
            {
                "id": "runtime-second",
                "endpoint": "/integrator/check-connection",
                "payload": {},
                "verificationWaiver": "Synthetic failure regression.",
                "expectedEffect": "second call",
            },
        ]
        plan = {
            "metadata": {
                "mode": "approved_runtime",
                "targetProjectUuid": project_uuid,
                "baseUrl": "https://ks.example.invalid/api",
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [item["id"] for item in operations],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": operations,
        }
        client = FakeClient([runtime_executor.KSAPIError("synthetic failure")])
        client.project_uuid = project_uuid
        client.base_url = "https://ks.example.invalid/api"
        client.login = mock.Mock(return_value="token")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            out_dir = root / "out"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = ["ks_approved_runtime_execute.py", str(plan_path), "--execute", "--out-dir", str(out_dir)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                runtime_executor.KSClient, "from_env", return_value=client
            ):
                exit_code = runtime_executor.main()
            report = json.loads(
                (out_dir / "runtime_execution_report.json").read_text(encoding="utf-8")
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual([item["status"] for item in report["operations"]], [
            "failed",
            "not_executed_after_failure",
        ])
        self.assertEqual(len(client.calls), 1)


class PayloadEnvTests(unittest.TestCase):
    def test_declared_exact_path_is_allowed_but_sibling_secret_is_rejected(self):
        operation = {
            "endpoint": "/integrator/check-connection",
            "payloadEnv": [{"path": "connection.password", "env": "KS_RUNTIME_PAYLOAD_TEST_SOURCE_PASSWORD"}],
        }
        payload = {
            "connection": {"password": "<password>"},
            "unapproved": {"password": "still-plain-text"},
        }
        with mock.patch.dict(os.environ, {"KS_RUNTIME_PAYLOAD_TEST_SOURCE_PASSWORD": "injected-secret"}, clear=False):
            injected = apply_payload_env(payload, operation, execute=True)
        self.assertEqual(injected["connection"]["password"], "injected-secret")
        findings = payload_secret_findings(
            injected,
            "payload",
            allowed_secret_paths=payload_env_paths(operation),
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("unapproved.password", findings[0])
        self.assertNotIn("injected-secret", " ".join(findings))

    def test_injected_value_is_redacted_from_arbitrary_output_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_runtime_json(
                root,
                "response.json",
                {
                    "echo": "prefix injected-secret suffix",
                    "key-injected-secret": "safe value",
                },
                secret_values=("injected-secret",),
            )
            text = (root / "response.json").read_text(encoding="utf-8")
        self.assertNotIn("injected-secret", text)
        self.assertIn("<redacted>", text)

    def test_overlapping_secret_values_are_redacted_longest_first(self):
        self.assertEqual(
            redact_secret_text("abcdef and abc", ("abc", "abcdef")),
            "<redacted> and <redacted>",
        )

    def test_runtime_executes_with_payload_env_and_persists_no_secret(self):
        operation = {
            "id": "runtime-1",
            "endpoint": "/integrator/check-connection",
            "payload": {"connection": {"password": "<password>"}},
            "payloadEnv": [{"path": "connection.password", "env": "KS_RUNTIME_PAYLOAD_TEST_SOURCE_PASSWORD"}],
            "readBack": {
                "endpoint": "/integrator/get-by-id",
                "payload": {"UUID": "source-1"},
                "checks": [{"path": "data.state", "equals": "ready"}],
            },
            "expectedEffect": "connection is checked",
        }
        client = FakeClient([
            {"echo": "injected-secret"},
            {"data": {"state": "ready", "echo": "injected-secret"}},
        ])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"KS_RUNTIME_PAYLOAD_TEST_SOURCE_PASSWORD": "injected-secret"},
            clear=False,
        ):
            out_dir = Path(tmp)
            result = execute_runtime(client, operation, base_dir=out_dir, out_dir=out_dir)
            persisted = "\n".join(path.read_text(encoding="utf-8") for path in out_dir.rglob("*.json"))

        self.assertEqual(result["status"], "executed_runtime")
        self.assertEqual(client.calls[0][1]["connection"]["password"], "injected-secret")
        self.assertNotIn("injected-secret", persisted)
        self.assertIn("readBackChecksPath", result)


class ReadBackTests(unittest.TestCase):
    def test_descriptive_or_mismatching_checks_fail_closed(self):
        invalid = evaluate_readback_checks({"state": "ready"}, ["state is ready"])
        mismatch = evaluate_readback_checks(
            {"data": {"state": "old"}},
            [{"path": "/data/state", "equals": "new"}],
        )
        self.assertFalse(invalid["valid"])
        self.assertFalse(mismatch["valid"])
        self.assertNotIn("old", str(mismatch))
        self.assertNotIn("new", str(mismatch))

    def test_json_checks_do_not_conflate_booleans_and_numbers(self):
        for actual, expected in ((True, 1), (False, 0), (1, True), (0, False)):
            with self.subTest(actual=actual, expected=expected):
                report = evaluate_readback_checks(
                    {"value": actual},
                    [{"path": "value", "equals": expected}],
                )
                self.assertFalse(report["valid"])
        contains = evaluate_readback_checks(
            {"values": [True]},
            [{"path": "values", "contains": 1}],
        )
        self.assertFalse(contains["valid"])

    def test_invalid_runtime_check_is_rejected_before_any_api_call(self):
        operation = {
            "id": "runtime-invalid",
            "endpoint": "/integrator/check-connection",
            "payload": {},
            "readBack": {
                "endpoint": "/integrator/get-by-id",
                "checks": ["connection became ready"],
            },
        }
        client = FakeClient([])
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, "invalid readBack checks"):
                execute_runtime(client, operation, base_dir=out_dir, out_dir=out_dir)
        self.assertEqual(client.calls, [])

    def test_project_write_mismatch_raises_after_persisting_value_free_report(self):
        entity_uuid = "00000000-0000-4000-8000-000000000101"
        operation = {
            "id": "write-1",
            "endpoint": "/models/update",
            "entityUuid": entity_uuid,
            "payload": {"UUID": entity_uuid, "name": "new"},
            "readBefore": {"endpoint": "/models/get-by-id", "payload": {"UUID": entity_uuid}},
            "readBack": {
                "endpoint": "/models/get-by-id",
                "payload": {"UUID": entity_uuid},
                "checks": [{"path": "data.name", "equals": "new"}],
            },
        }
        client = FakeClient([
            {"data": {"name": "old"}},
            {"ok": True},
            {"data": {"name": "old"}},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with self.assertRaises(ReadBackCheckError):
                execute_project_write(client, operation, base_dir=out_dir, out_dir=out_dir)
            report_text = (out_dir / "operations" / "write-1_read_back_checks.json").read_text(encoding="utf-8")

        self.assertIn('"valid": false', report_text)
        self.assertNotIn('"old"', report_text)
        self.assertNotIn('"new"', report_text)


if __name__ == "__main__":
    unittest.main()
