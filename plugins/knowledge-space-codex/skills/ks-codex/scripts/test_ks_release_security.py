#!/usr/bin/env python3
"""Release-gate regressions for exact approval, secrets, and zero-call preflight."""

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

import ks_api_client  # noqa: E402
import ks_approved_runtime_execute as runtime_executor  # noqa: E402
import ks_safe_files  # noqa: E402
from ks_api_client import KSAPIUncertainResultError, KSClient  # noqa: E402
from ks_safe_patch_execute import EffectUnknownError, execute_project_write  # noqa: E402
from ks_safe_patch_lint import get_operations, lint  # noqa: E402
from ks_secret_safety import redact_text, text_contains_secret  # noqa: E402


PROJECT_UUID = "00000000-0000-4000-8000-000000000001"
ENTITY_A = "00000000-0000-4000-8000-000000000101"
ENTITY_B = "00000000-0000-4000-8000-000000000102"
STAND_URL = "https://ks.example.invalid/api"


class FakeClient:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls: list[tuple[str, object, dict[str, object]]] = []
        self.project_uuid = PROJECT_UUID
        self.base_url = STAND_URL
        self.login_name = "ks-login"
        self.password = "ks-password-value"
        self.token = "ks-session-value"
        self.login = mock.Mock(return_value=self.token)

    def post(self, endpoint, payload, **kwargs):
        self.calls.append((endpoint, payload, kwargs))
        if not self.responses:
            return {"ok": True}
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def runtime_operation(**overrides):
    value = {
        "id": "runtime-op",
        "endpoint": "/integrator/check-connection",
        "payload": {},
        "verificationWaiver": "This synthetic endpoint has no stable read-back.",
        "expectedEffect": "connection is checked",
    }
    value.update(overrides)
    return value


def project_operation(**overrides):
    value = {
        "id": "write-op",
        "endpoint": "/models/update",
        "entityUuid": ENTITY_A,
        "payload": {"UUID": ENTITY_A, "name": "new"},
        "readBefore": {"endpoint": "/models/get-by-id", "payload": {"UUID": ENTITY_A}},
        "readBack": {
            "endpoint": "/models/get-by-id",
            "payload": {"UUID": ENTITY_A},
            "checks": [{"path": "data.name", "equals": "new"}],
        },
    }
    value.update(overrides)
    return value


class SchemaAndSecretTests(unittest.TestCase):
    def test_operation_and_mode_aliases_fail_closed(self):
        with self.assertRaisesRegex(SystemExit, "only one"):
            get_operations({"operations": [], "patches": [runtime_operation()]})
        plan = {
            "metadata": {
                "mode": "dry_run",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "mode": "approved_runtime",
            "operations": [runtime_operation()],
        }
        report, blocking = lint(plan)
        self.assertGreater(blocking, 0)
        self.assertIn("mode aliases conflict", report)

    def test_encoded_xml_semantic_and_quoted_secrets_are_redacted(self):
        values = (
            r'{"\u0070assword":"Synthetic Secret Value"}',
            "<password>Synthetic Secret Value</password>",
            "password=\"correct horse battery staple\"",
            "apiKey:'alpha beta gamma'",
            "postgres://" + "user:p@ss@" + "host.invalid/db",
        )
        for value in values:
            with self.subTest(value=value):
                rendered = redact_text(value)
                self.assertNotEqual(rendered, value)
                self.assertNotIn("battery staple", rendered)
                self.assertNotIn("beta gamma", rendered)
                self.assertNotIn("ss@host", rendered)
        semantic = {"Name": "Password", "Value": "Synthetic Secret Value"}
        self.assertTrue(runtime_executor.payload_secret_findings(semantic, "payload"))
        self.assertEqual(runtime_executor.sanitize(semantic)["Value"], "<redacted>")
        self.assertEqual(ks_api_client._redact(semantic)["Value"], "<redacted>")

    def test_exact_secret_json_escaped_variants_are_redacted(self):
        secret = 'abc"def\\ghi\njkl'
        encoded = json.dumps({"message": secret})
        rendered = redact_text(encoded, (secret,))
        self.assertNotIn(json.dumps(secret)[1:-1], rendered)
        self.assertIn("<redacted>", rendered)


class PayloadAndIdentityTests(unittest.TestCase):
    def test_semantic_parameter_requires_exact_payload_env_mapping(self):
        payload = {"parameters": [{"name": "password", "value": "<password>"}]}
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            RuntimeError, "exact payloadEnv mapping"
        ):
            runtime_executor.execute_runtime(
                client,
                runtime_operation(payload=payload),
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
        self.assertEqual(client.calls, [])

    def test_payload_env_cannot_change_identity_or_reuse_ks_credentials(self):
        client = FakeClient()
        identity_operation = runtime_operation(
            payload={"UUID": "<target>"},
            payloadEnv=[
                {"path": "UUID", "env": "KS_RUNTIME_PAYLOAD_TARGET"}
            ],
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"KS_RUNTIME_PAYLOAD_TARGET": ENTITY_A},
            clear=False,
        ), self.assertRaisesRegex(RuntimeError, "credential/source-connection"):
            runtime_executor.execute_runtime(
                client,
                identity_operation,
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
        credential_operation = runtime_operation(
            payload={"connection": {"password": "<password>"}},
            payloadEnv=[
                {
                    "path": "connection.password",
                    "env": "KS_RUNTIME_PAYLOAD_CONNECTION_PASSWORD",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"KS_RUNTIME_PAYLOAD_CONNECTION_PASSWORD": client.token},
            clear=False,
        ), self.assertRaisesRegex(RuntimeError, "must not reuse"):
            runtime_executor.execute_runtime(
                client,
                credential_operation,
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
        self.assertEqual(client.calls, [])

    def test_project_write_target_mismatch_blocks_before_api(self):
        client = FakeClient()
        operation = project_operation(payload={"UUID": ENTITY_B, "name": "new"})
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            RuntimeError, "must exactly match entityUuid"
        ):
            execute_project_write(
                client,
                operation,
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
        self.assertEqual(client.calls, [])

    def test_non_entity_runtime_readback_remains_supported(self):
        operation = runtime_operation(
            verificationWaiver=None,
            readBack={
                "endpoint": "/integrator/get-by-id",
                "payload": {"UUID": ENTITY_A},
                "checks": [{"path": "data.state", "equals": "ready"}],
            },
        )
        operation.pop("verificationWaiver")
        client = FakeClient(({"ok": True}, {"data": {"state": "ready"}}))
        with tempfile.TemporaryDirectory() as tmp:
            result = runtime_executor.execute_runtime(
                client,
                operation,
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
        self.assertEqual(result["status"], "executed_runtime")
        self.assertEqual(len(client.calls), 2)


class PreflightAndTransportTests(unittest.TestCase):
    def test_invalid_second_payload_file_blocks_entire_batch_before_login(self):
        first = runtime_operation(id="first")
        second = runtime_operation(id="second", payloadPath="payload.json")
        second.pop("payload")
        plan = {
            "metadata": {
                "mode": "approved_runtime",
                "targetProjectUuid": PROJECT_UUID,
                "baseUrl": STAND_URL,
            },
            "approval": {
                "userApproved": True,
                "approvedOperationIds": ["first", "second"],
                "approvedEndpoints": [],
                "exactApprovedActions": [],
            },
            "operations": [first, second],
        }
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "payload.json").write_text(
                '{"value": 1, "value": 2}',
                encoding="utf-8",
            )
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            out = root / "out"
            argv = [
                "ks_approved_runtime_execute.py",
                str(plan_path),
                "--execute",
                "--out-dir",
                str(out),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                runtime_executor.KSClient,
                "from_env",
                return_value=client,
            ):
                exit_code = runtime_executor.main()
            report = json.loads(
                (out / "runtime_execution_report.json").read_text(encoding="utf-8")
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual({item["status"] for item in report["operations"]}, {"denied"})
        client.login.assert_not_called()
        self.assertEqual(client.calls, [])

    def test_exact_output_symlink_and_unwritable_probe_block_before_api(self):
        operation = runtime_operation()
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            operations = out / "operations"
            operations.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text("untouched", encoding="utf-8")
            (operations / "runtime-op_runtime_response.json").symlink_to(outside)
            with self.assertRaises(ks_safe_files.SafePathError):
                runtime_executor.execute_runtime(
                    client,
                    operation,
                    base_dir=root,
                    out_dir=out,
                )
            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            ks_safe_files.tempfile,
            "mkstemp",
            side_effect=PermissionError("synthetic read-only output"),
        ), self.assertRaises(ks_safe_files.SafePathError):
            runtime_executor.execute_runtime(
                client,
                operation,
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
        self.assertEqual(client.calls, [])

    def test_transport_failure_is_wrapped_and_mutation_is_not_retried(self):
        secret = "synthetic-transport-secret"
        api_client = KSClient(
            STAND_URL,
            password=secret,
            token="synthetic-session",
            project_uuid=PROJECT_UUID,
        )
        api_client.session.post = mock.Mock(
            side_effect=ks_api_client.requests.Timeout(f"timeout {secret}")
        )
        with self.assertRaises(KSAPIUncertainResultError) as caught:
            api_client.post("/models/update", {"UUID": ENTITY_A})
        self.assertNotIn(secret, str(caught.exception))

        client = FakeClient(
            (
                {"data": {"name": "old"}},
                KSAPIUncertainResultError("synthetic timeout"),
                {"data": {"name": "new"}},
            )
        )
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            EffectUnknownError, "do not retry automatically"
        ):
            execute_project_write(
                client,
                project_operation(),
                base_dir=Path(tmp),
                out_dir=Path(tmp),
            )
            self.fail("effect_unknown must raise")
        endpoints = [call[0] for call in client.calls]
        self.assertEqual(endpoints.count("/models/update"), 1)
        self.assertEqual(endpoints.count("/models/get-by-id"), 2)


if __name__ == "__main__":
    unittest.main()
