#!/usr/bin/env python3
"""Fail-closed regressions for plan ambiguity, paths, endpoints, and secrets."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ks_approved_runtime_execute as runtime_executor  # noqa: E402
import ks_api_client  # noqa: E402
import ks_safe_patch_execute as safe_executor  # noqa: E402
from ks_approved_runtime_execute import (  # noqa: E402
    execute_runtime,
    payload_secret_findings as runtime_payload_secret_findings,
)
from ks_safe_files import SafePathError  # noqa: E402
from ks_safe_patch_execute import (  # noqa: E402
    execute_project_write,
    payload_secret_findings as safe_payload_secret_findings,
)
from ks_safe_patch_lint import (  # noqa: E402
    classify_operation,
    endpoint_validation_error,
    lint,
    load_plan,
    norm_endpoint,
    plan_binding_errors,
    secret_findings,
)


PROJECT_UUID = "00000000-0000-4000-8000-000000000001"
STAND_URL = "https://ks.example.invalid/api"


class FakeClient:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls: list[tuple[str, object, dict[str, object]]] = []
        self.project_uuid = PROJECT_UUID
        self.base_url = STAND_URL
        self.password = None
        self.token = None

    def post(self, endpoint, payload, **kwargs):
        self.calls.append((endpoint, payload, kwargs))
        if not self.responses:
            raise AssertionError("unexpected KS API call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def login(self):
        return self.token or "synthetic-token"


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.text = json.dumps(body)
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeHTTPErrorResponse(FakeResponse):
    def raise_for_status(self):
        raise ks_api_client.requests.HTTPError("synthetic HTTP failure")


def runtime_operation(**overrides):
    value = {
        "id": "runtime-op",
        "endpoint": "/integrator/check-connection",
        "payload": {},
        "verificationWaiver": "Synthetic endpoint has no stable read-back.",
        "expectedEffect": "connection is checked",
    }
    value.update(overrides)
    return value


def project_operation(**overrides):
    value = {
        "id": "write-op",
        "endpoint": "/models/update",
        "payload": {"UUID": "model-1", "name": "new"},
        "readBefore": {
            "endpoint": "/models/get-by-id",
            "payload": {"UUID": "model-1"},
        },
        "readBack": {
            "endpoint": "/models/get-by-id",
            "payload": {"UUID": "model-1"},
            "checks": [{"path": "data.name", "equals": "new"}],
        },
    }
    value.update(overrides)
    return value


class EndpointAndRiskTests(unittest.TestCase):
    def test_noncanonical_endpoint_variants_are_rejected(self):
        invalid = (
            "/integrator/get-db-fields?source=1",
            "/integrator/get-db-fields;v=1",
            "/integrator/%67et-db-fields",
            "/integrator//get-db-fields",
            "/integrator/../get-db-fields",
            "/integrator\\get-db-fields",
        )
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                self.assertIsNotNone(endpoint_validation_error(endpoint))
                self.assertEqual(norm_endpoint(endpoint), "")
                self.assertEqual(classify_operation({"endpoint": endpoint}), "unknown")
        self.assertIsNone(endpoint_validation_error("/models/get-by-id/"))
        self.assertEqual(norm_endpoint("/models/get-by-id/"), "/models/get-by-id")

    def test_official_sensitive_families_and_business_effects_escalate(self):
        expectations = {
            "/projects/update": "destructive_or_global",
            "/publications/update-access": "destructive_or_global",
            "/imports/create": "external_or_runtime",
            "/imports/load": "destructive_or_global",
        }
        for endpoint, expected in expectations.items():
            self.assertEqual(classify_operation({"endpoint": endpoint}), expected)
        for summary in (
            "delete all project settings",
            "restore backup state",
            "удалить все данные",
            "восстановить резервную копию",
            "wipe all project data",
            "purge objects",
            "truncate dataset",
            "clear and reset model",
            "drop all rows",
            "overwrite project state",
        ):
            self.assertEqual(
                classify_operation({"endpoint": "/models/update", "summary": summary}),
                "destructive_or_global",
            )
        for summary in (
            "recalculate all indicators",
            "start process",
            "запустить интеграцию",
            "пересчитать модель",
            "import rows from external DB",
            "load rows from source",
            "calculate all formulas",
            "trigger process",
        ):
            self.assertEqual(
                classify_operation({"endpoint": "/models/update", "summary": summary}),
                "external_or_runtime",
            )


class BindingAndPlanTests(unittest.TestCase):
    def test_conflicting_and_explicit_null_aliases_are_blockers(self):
        other_uuid = "00000000-0000-4000-8000-000000000002"
        conflict = {
            "metadata": {
                "targetProjectUuid": PROJECT_UUID,
                "projectUuid": other_uuid,
                "baseUrl": STAND_URL,
                "stand": "https://other.example.invalid/api",
            }
        }
        errors = plan_binding_errors(conflict)
        self.assertIn("Plan project UUID aliases conflict", errors)
        self.assertIn("Plan stand URL aliases conflict", errors)

        explicit_null = {
            "metadata": {"targetProjectUuid": None, "baseUrl": None},
            "projectUuid": PROJECT_UUID,
            "stand": STAND_URL,
        }
        null_errors = plan_binding_errors(explicit_null)
        self.assertTrue(any("targetProjectUuid" in error for error in null_errors))
        self.assertTrue(any("baseUrl" in error for error in null_errors))

        for invalid_stand in (
            "https://example.invalid/api?",
            "https://example.invalid/api#",
            "https://@example.invalid/api",
            "https://example.invalid/%61pi",
            "https://example.invalid/api/../other",
            "https://example.invalid//api",
            "https://example.invalid/api;v=1",
        ):
            with self.subTest(invalid_stand=invalid_stand):
                errors = plan_binding_errors(
                    {
                        "metadata": {
                            "targetProjectUuid": PROJECT_UUID,
                            "baseUrl": invalid_stand,
                        }
                    }
                )
                self.assertTrue(any("baseUrl" in error for error in errors))

    def test_invalid_stand_and_endpoint_never_leak_raw_credentials_to_report(self):
        plan = {
            "metadata": {
                "mode": "dry_run",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": "https://" + "user:password-value@host.invalid/api",
            },
            "operations": [
                {
                    "id": "invalid-endpoint",
                    "endpoint": "/models/get-by-id?token=secret-value",
                    "payload": {},
                }
            ],
        }
        report, blocking = lint(plan)
        self.assertGreater(blocking, 0)
        self.assertNotIn("password-value", report)
        self.assertNotIn("secret-value", report)
        self.assertIn("<invalid/redacted>", report)

    def test_blocked_secret_like_ids_and_endpoints_are_redacted_in_lint_report(self):
        token = "ghp_" + "REPORTSECRET012345678901234567"
        plan = {
            "metadata": {
                "mode": "dry_run",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "operations": [
                {"id": token, "endpoint": "/models/" + token, "payload": {}}
            ],
        }
        report, blocking = lint(plan)
        self.assertGreater(blocking, 0)
        self.assertNotIn(token, report)
        self.assertIn("<redacted>", report)

    def test_project_write_requires_machine_readback_checks(self):
        operation = project_operation(
            readBack={"endpoint": "/models/get-by-id", "payload": {"UUID": "model-1"}}
        )
        plan = {
            "metadata": {
                "mode": "execute_project_writes",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [operation["id"]],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": [operation],
        }
        report, blocking = lint(plan)
        self.assertGreater(blocking, 0)
        self.assertIn("checks must be a non-empty list", report)
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            RuntimeError, "invalid readBack checks"
        ):
            root = Path(tmp)
            execute_project_write(client, operation, base_dir=root, out_dir=root)
        self.assertEqual(client.calls, [])


class NestedAndFilesystemTests(unittest.TestCase):
    def test_destructive_nested_endpoints_are_rejected_before_api(self):
        cases = (
            (
                execute_project_write,
                project_operation(readBefore={"endpoint": "/backups/load", "payload": {}}),
            ),
            (
                execute_runtime,
                runtime_operation(readBefore={"endpoint": "/backups/load", "payload": {}}),
            ),
        )
        for executor, operation in cases:
            with self.subTest(executor=executor.__name__), tempfile.TemporaryDirectory() as tmp:
                client = FakeClient()
                root = Path(tmp)
                with self.assertRaisesRegex(RuntimeError, "must be read_only"):
                    executor(client, operation, base_dir=root, out_dir=root)
                self.assertEqual(client.calls, [])

    def test_payload_path_traversal_absolute_and_symlink_are_rejected_before_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "plan"
            base.mkdir()
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            (base / "linked.json").symlink_to(outside)
            for payload_path in ("../outside.json", str(outside), "linked.json"):
                with self.subTest(payload_path=payload_path):
                    client = FakeClient()
                    operation = runtime_operation(payload=None, payloadPath=payload_path)
                    operation.pop("payload")
                    with self.assertRaises((SafePathError, RuntimeError)):
                        execute_runtime(client, operation, base_dir=base, out_dir=root)
                    self.assertEqual(client.calls, [])

    def test_output_symlink_is_rejected_before_api_and_outside_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            outside = root / "outside"
            out.mkdir()
            outside.mkdir()
            (out / "operations").symlink_to(outside, target_is_directory=True)
            client = FakeClient()
            with self.assertRaises(SafePathError):
                execute_runtime(client, runtime_operation(), base_dir=root, out_dir=out)
            self.assertEqual(client.calls, [])
            self.assertEqual(list(outside.iterdir()), [])

    def test_fixed_report_symlink_is_rejected_before_client_creation(self):
        operation = runtime_operation()
        plan = {
            "metadata": {
                "mode": "approved_runtime",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [operation["id"]],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": [operation],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            outside = root / "outside.txt"
            outside.write_text("untouched", encoding="utf-8")
            (out / "lint_report.md").symlink_to(outside)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = [
                "ks_approved_runtime_execute.py",
                str(plan_path),
                "--execute",
                "--out-dir",
                str(out),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                runtime_executor.KSClient, "from_env"
            ) as from_env, self.assertRaises(SafePathError):
                runtime_executor.main()
            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")
        from_env.assert_not_called()

    def test_ambiguous_payload_sources_are_rejected_before_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "payload.json").write_text("{}", encoding="utf-8")
            operation = runtime_operation(payload={"source": "inline"}, payloadPath="payload.json")
            client = FakeClient()
            with self.assertRaisesRegex(RuntimeError, "only one"):
                execute_runtime(client, operation, base_dir=root, out_dir=root)
            self.assertEqual(client.calls, [])

    def test_nested_read_payload_secrets_are_rejected_before_api(self):
        operation = runtime_operation(
            readBefore={
                "endpoint": "/models/get-by-id",
                "payload": {"opaque": "Authorization: Basic YWJjOmRlZg=="},
            }
        )
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            RuntimeError, "secret-like string"
        ):
            root = Path(tmp)
            execute_runtime(client, operation, base_dir=root, out_dir=root)
        self.assertEqual(client.calls, [])


class CredentialSafetyTests(unittest.TestCase):
    def test_client_rejects_credentialed_or_query_base_urls(self):
        for base_url in (
            "https://" + "alice:TopSecret123@example.invalid/api",
            "https://example.invalid/api?token=TopSecret123",
            "https://example.invalid/api#secret",
            "https://example.invalid/api?",
            "https://example.invalid/api#",
            "https://@example.invalid/api",
            "https://example.invalid/%61pi",
            "https://example.invalid/api/../other",
        ):
            with self.subTest(base_url=base_url), self.assertRaises(
                ks_api_client.KSAPIError
            ):
                ks_api_client.KSClient(base_url=base_url, token="synthetic-token")

    def test_http_error_redacts_full_secret_before_detail_truncation(self):
        password = "CROSSING-SECRET-VALUE-1234567890"
        client = ks_api_client.KSClient(
            base_url=STAND_URL,
            project_uuid=PROJECT_UUID,
            password=password,
            token="synthetic-token",
        )
        body = "x" * 990 + password + "tail"
        response = FakeHTTPErrorResponse({})
        response.text = body
        client.session.post = mock.Mock(return_value=response)
        with self.assertRaises(ks_api_client.KSAPIError) as captured:
            client.post("/models/get-by-id", {})
        rendered = str(captured.exception)
        self.assertNotIn(password, rendered)
        self.assertNotIn("CROSSING-SECRET", rendered)
        self.assertIn("<redacted>", rendered)

    def test_http_redirects_are_disabled_and_three_xx_fails_closed(self):
        client = ks_api_client.KSClient(
            base_url=STAND_URL,
            project_uuid=PROJECT_UUID,
            token="synthetic-token",
        )
        response = FakeResponse({"redirect": True})
        response.status_code = 307
        client.session.post = mock.Mock(return_value=response)
        with self.assertRaisesRegex(ks_api_client.KSAPIError, "HTTP 307"):
            client.post("/integrator/check-connection", {"password": "<password>"})
        self.assertIs(
            client.session.post.call_args.kwargs.get("allow_redirects"),
            False,
        )

    def test_any_json_error_field_fails_even_when_value_is_falsey(self):
        client = ks_api_client.KSClient(
            base_url=STAND_URL,
            project_uuid=PROJECT_UUID,
            token="synthetic-token",
        )
        for value in ({}, "", 0, False, None):
            with self.subTest(value=value):
                client.session.post = mock.Mock(return_value=FakeResponse({"error": value}))
                with self.assertRaises(ks_api_client.KSAPIError):
                    client.post("/models/get-by-id", {})

    def test_core_auth_environment_cannot_be_injected_as_runtime_payload(self):
        operation = runtime_operation(
            payload={"connection": {"password": "<password>"}},
            payloadEnv=[{"path": "connection.password", "env": "KS_TOKEN"}],
        )
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"KS_TOKEN": "core-auth-token"}, clear=False
        ), self.assertRaisesRegex(RuntimeError, "KS_RUNTIME_PAYLOAD"):
            root = Path(tmp)
            execute_runtime(client, operation, base_dir=root, out_dir=root)
        self.assertEqual(client.calls, [])

    def test_embedded_auth_private_keys_and_sensitive_containers_never_crash_or_pass(self):
        values = {
            "neutral": "prefix Authorization: Basic YWJjOmRlZg== suffix",
            "uri": "postgres://" + "user:password@host/db",
            "opaque": "-----BEGIN " + "PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            "secrets": {},
            "token": [],
        }
        self.assertTrue(secret_findings(values))
        self.assertTrue(safe_payload_secret_findings(values, "payload"))
        self.assertTrue(runtime_payload_secret_findings(values, "payload"))

    def test_common_api_key_fields_and_known_token_prefixes_fail_closed(self):
        aws_key = "AKIA" + "ABCDEFGHIJKLMNOP"
        github_token = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        values = {
            "apiKey": aws_key,
            "access_key": github_token,
            "credentials": {"passphrase": "plain-value"},
        }
        self.assertTrue(secret_findings(values))
        self.assertTrue(safe_payload_secret_findings(values, "payload"))
        self.assertTrue(runtime_payload_secret_findings(values, "payload"))
        persisted_shapes = json.dumps(
            {
                "runtime": runtime_executor.sanitize(values),
                "client": ks_api_client._redact(values),
            }
        )
        self.assertNotIn(aws_key, persisted_shapes)
        self.assertNotIn(github_token, persisted_shapes)

        operation = runtime_operation(payload=values)
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            RuntimeError, "sensitive .*field|secret-like string"
        ):
            root = Path(tmp)
            execute_runtime(client, operation, base_dir=root, out_dir=root)
        self.assertEqual(client.calls, [])

    def test_string_encoded_sensitive_objects_are_detected_and_redacted(self):
        secret = "ghp_" + "ENCODEDSECRET0123456789012345"
        encoded = '{"api' + 'Key":"' + secret + '"}'
        values = {"opaqueRequestBody": encoded}
        self.assertTrue(secret_findings(values))
        self.assertTrue(safe_payload_secret_findings(values, "payload"))
        self.assertTrue(runtime_payload_secret_findings(values, "payload"))
        rendered = json.dumps(runtime_executor.sanitize(values))
        self.assertNotIn(secret, rendered)
        self.assertIn("redacted-structured-secret", rendered)

    def test_duplicate_keys_and_nonstandard_constants_are_rejected(self):
        secret = "ghp_" + "DUPLICATESECRET0123456789012345"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "payload.json"
            payload_path.write_text(
                '{"apiKey":"' + secret + '","apiKey":"<redacted>"}',
                encoding="utf-8",
            )
            operation = runtime_operation(payloadPath="payload.json")
            operation.pop("payload")
            client = FakeClient()
            with self.assertRaisesRegex(SafePathError, "duplicate JSON object key"):
                execute_runtime(client, operation, base_dir=root, out_dir=root)
            self.assertEqual(client.calls, [])

            for content in (
                '{"metadata":{},"metadata":{},"operations":[]}',
                '{"metadata":{"value":NaN},"operations":[]}',
            ):
                plan_path = root / "plan.json"
                plan_path.write_text(content, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    load_plan(plan_path)

    def test_login_error_is_redacted_in_runtime_report(self):
        operation = runtime_operation()
        plan = {
            "metadata": {
                "mode": "approved_runtime",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [operation["id"]],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": [operation],
        }
        client = FakeClient()
        client.password = "login-password-value"
        client.token = "login-token-value"
        client.login = mock.Mock(
            side_effect=runtime_executor.KSAPIError(
                "HTTP 401 Authorization: Bearer login-token-value password=login-password-value"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            out = root / "out"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = [
                "ks_approved_runtime_execute.py",
                str(plan_path),
                "--execute",
                "--out-dir",
                str(out),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                runtime_executor.KSClient, "from_env", return_value=client
            ):
                exit_code = runtime_executor.main()
            persisted = "\n".join(
                path.read_text(encoding="utf-8") for path in out.glob("*.json")
            )
        self.assertEqual(exit_code, 1)
        self.assertNotIn("login-password-value", persisted)
        self.assertNotIn("login-token-value", persisted)
        self.assertIn("<redacted>", persisted)

    def test_safe_executor_dry_run_never_requires_a_client(self):
        plan = {
            "metadata": {
                "mode": "dry_run",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "operations": [
                {"id": "read-op", "endpoint": "/models/get-by-id", "payload": {}}
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            out = root / "out"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = ["ks_safe_patch_execute.py", str(plan_path), "--out-dir", str(out)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                safe_executor.KSClient, "from_env"
            ) as from_env:
                exit_code = safe_executor.main()
            self.assertTrue((out / "execution_report.json").exists())
        self.assertEqual(exit_code, 0)
        from_env.assert_not_called()

    def test_api_base_path_mismatch_blocks_before_login_or_api(self):
        operation = runtime_operation()
        plan = {
            "metadata": {
                "mode": "approved_runtime",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": [operation["id"]],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": [operation],
        }
        client = FakeClient()
        client.base_url = "https://ks.example.invalid"
        client.login = mock.Mock(return_value="token")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            out = root / "out"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = [
                "ks_approved_runtime_execute.py",
                str(plan_path),
                "--execute",
                "--out-dir",
                str(out),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                runtime_executor.KSClient, "from_env", return_value=client
            ):
                exit_code = runtime_executor.main()
            report = json.loads(
                (out / "runtime_execution_report.json").read_text(encoding="utf-8")
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["operations"][0]["status"], "denied")
        self.assertIn("KS_BASE_URL does not match", report["operations"][0]["issues"][0])
        client.login.assert_not_called()
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
