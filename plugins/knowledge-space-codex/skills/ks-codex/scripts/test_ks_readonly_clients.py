#!/usr/bin/env python3
"""Focused regressions for read-only helpers using the shared KS client."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import ks_project_snapshot
import ks_smoke_check
from ks_api_client import KSAPIError, KSClient
from ks_safe_files import SafePathError


PROJECT_UUID = "11111111-1111-4111-8111-111111111111"


class _RedirectResponse:
    status_code = 302
    text = "redirected"

    def raise_for_status(self) -> None:
        return None


class _RedirectSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.allow_redirects: bool | None = None

    def post(self, *_args, **kwargs):
        self.allow_redirects = kwargs.get("allow_redirects")
        return _RedirectResponse()


class _SnapshotClient:
    def __init__(self, token: str) -> None:
        self.project_uuid = PROJECT_UUID
        self.password = None
        self.token = token

    def login(self) -> str:
        return self.token

    def post(self, path: str, _payload: dict) -> dict:
        if path == "/models/get-with-datasets":
            return {"data": [{"uuid": "model-1", "name": self.token}]}
        if path == "/integrator/get-sources-list":
            return {
                "data": [
                    {
                        "uuid": "source-1",
                        "name": "Source",
                        "connectionParams": {
                            "host": "internal.example",
                            "login": "operator",
                        },
                    }
                ]
            }
        return {"data": []}


class ReadonlyClientTests(unittest.TestCase):
    def test_smoke_check_inherits_redirect_rejection_from_shared_client(self) -> None:
        client = KSClient(
            base_url="https://example.test/api",
            project_uuid=PROJECT_UUID,
            token="synthetic-token",
        )
        session = _RedirectSession()
        client.session = session  # type: ignore[assignment]

        with mock.patch.object(ks_smoke_check.KSClient, "from_env", return_value=client):
            with self.assertRaises(KSAPIError):
                ks_smoke_check.main()

        self.assertFalse(session.allow_redirects)

    def test_snapshot_uses_atomic_outputs_and_redacts_exact_credentials(self) -> None:
        token = "snapshot-secret-value"
        client = _SnapshotClient(token)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path = root / "nested" / "snapshot.json"
            map_path = root / "nested" / "project_map.md"
            argv = [
                "ks_project_snapshot.py",
                "--out",
                str(snapshot_path),
                "--map-out",
                str(map_path),
            ]
            with (
                mock.patch.object(
                    ks_project_snapshot.KSClient,
                    "from_env",
                    return_value=client,
                ),
                mock.patch.object(sys, "argv", argv),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(ks_project_snapshot.main(), 0)

            snapshot_text = snapshot_path.read_text(encoding="utf-8")
            map_text = map_path.read_text(encoding="utf-8")
            snapshot = json.loads(snapshot_text)

            self.assertNotIn(token, snapshot_text)
            self.assertNotIn(token, map_text)
            self.assertEqual(snapshot["sections"]["models"]["items"][0]["name"], "<redacted>")
            source = snapshot["sections"]["integrationSources"]["raw"]["data"][0]
            self.assertEqual(source["connectionParams"]["host"], "<redacted>")
            self.assertNotIn("/auth/login", snapshot["callSummary"]["paths"])
            self.assertEqual(stat.S_IMODE(snapshot_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(map_path.stat().st_mode), 0o600)

    def test_snapshot_atomic_output_refuses_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("unchanged", encoding="utf-8")
            link = root / "snapshot.json"
            os.symlink(outside, link)

            with self.assertRaises(SafePathError):
                ks_project_snapshot.write_text_atomic(link, "replacement")

            self.assertEqual(outside.read_text(encoding="utf-8"), "unchanged")

    def test_optional_endpoint_errors_are_credential_redacted(self) -> None:
        secret = "endpoint-password"

        class FailingClient:
            password = secret
            token = None

            def post(self, _path: str, _payload: dict) -> dict:
                raise RuntimeError(f"password={secret}")

        calls: list[str] = []
        body = ks_project_snapshot.try_post(
            FailingClient(),  # type: ignore[arg-type]
            "/optional/get-list",
            [{}],
            calls,
        )

        rendered = json.dumps(body)
        self.assertNotIn(secret, rendered)
        self.assertIn("<redacted>", rendered)
        self.assertEqual(calls, ["/optional/get-list"])


if __name__ == "__main__":
    unittest.main()
