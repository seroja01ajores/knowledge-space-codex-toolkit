#!/usr/bin/env python3
"""Synthetic tests for private offline KS knowledge retrieval."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import ks_knowledge as knowledge


def card(card_id: str = "iframe-session-refresh") -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": card_id,
        "title": "Refresh an iframe inside one user session",
        "intent": "Update an iframe after a dashboard filter changes",
        "domains": ["dashboard-ui", "browser-diagnostics"],
        "symptoms": ["iframe changes only once", "page reload is required"],
        "ksVersions": ["1.7"],
        "scope": "portable",
        "visibility": "public",
        "status": "verified",
        "confidence": 0.9,
        "sensitivity": "public-safe",
        "preconditions": ["target page permits framing"],
        "solution": {
            "summary": "Use a session bridge and update the nested frame source.",
            "steps": ["Validate the selected route", "Update only the nested frame"],
        },
        "evidence": [
            {
                "type": "synthetic-test",
                "source": "fixture:iframe-session-refresh",
                "sourceHash": "a" * 64,
            }
        ],
        "verification": {
            "apiReadback": False,
            "browserVerified": True,
            "syntheticRegression": True,
            "notes": ["Verified with two synthetic routes"],
        },
        "tags": ["iframe", "session", "filter"],
        "supersededBy": None,
        "updatedAt": "2026-08-19T12:00:00+03:00",
    }


def lifecycle_card(card_id: str = "iframe-session-refresh-v11") -> dict[str, object]:
    value = card(card_id)
    value["schemaVersion"] = "1.1"
    value["updatedAt"] = "2026-08-20T09:00:00+00:00"
    value["applicability"] = {
        "capabilities": ["dashboard-ui", "browser-diagnostics"],
        "endpointFamilies": ["/dashboards"],
        "requiredGate": "read_only",
    }
    value["learning"] = {
        "rejectedHypotheses": [],
        "remainingUnknowns": [],
    }
    value["freshness"] = {
        "verifiedAt": "2026-08-19T09:00:00+00:00",
        "lastCheckedAt": "2026-08-20T09:00:00+00:00",
        "reviewAfter": "2099-01-01T00:00:00+00:00",
    }
    value["promotion"] = {
        "independentReview": True,
        "publicRedactionReview": True,
        "evidenceHashes": ["a" * 64],
    }
    return value


class KnowledgeTests(unittest.TestCase):
    def test_v10_card_requires_lifecycle_migration_before_promotion(self) -> None:
        value = knowledge.validate_card(card())
        report = knowledge.promotion_report(value)
        self.assertFalse(report["publicReady"])
        self.assertEqual(report["freshness"], "unknown")
        self.assertIn(
            "schema 1.1 lifecycle metadata is required",
            report["reasons"],
        )

    def test_secret_representation_is_rejected(self) -> None:
        value = card()
        value["solution"]["summary"] = "token=abcdefghijklmnopqrstuvwxyz123456"
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.validate_card(value)

    def test_build_and_filtered_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cards_root = root / "cards"
            database_root = root / "indexes"
            cards_root.mkdir()
            database_root.mkdir()
            value = card()
            (cards_root / f"{value['id']}.json").write_text(
                json.dumps(value, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                build = knowledge.build_index(
                    cards_root,
                    database_root,
                    "experience.sqlite",
                )
            except knowledge.KnowledgeError as exc:
                if "FTS5" in str(exc):
                    self.skipTest("SQLite build has no FTS5 support")
                raise
            self.assertEqual(build["cardCount"], 1)
            result = knowledge.search_index(
                database_root,
                "experience.sqlite",
                "iframe filter refresh",
                domains=["dashboard-ui"],
            )
            self.assertEqual(result["resultCount"], 1)
            self.assertEqual(result["results"][0]["id"], value["id"])

    def test_v11_lifecycle_columns_match_insert_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cards_root = root / "cards"
            database_root = root / "indexes"
            cards_root.mkdir()
            database_root.mkdir()
            value = lifecycle_card()
            (cards_root / f"{value['id']}.json").write_text(
                json.dumps(value, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                knowledge.build_index(
                    cards_root,
                    database_root,
                    "experience.sqlite",
                )
            except knowledge.KnowledgeError as exc:
                if "FTS5" in str(exc):
                    self.skipTest("SQLite build has no FTS5 support")
                raise

            database = database_root / "experience.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                table_name = None
                columns: set[str] = set()
                for (candidate,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ):
                    candidate_columns = {
                        row[1]
                        for row in connection.execute(
                            f'PRAGMA table_info("{candidate}")'
                        )
                    }
                    if {
                        "schema_version",
                        "required_gate",
                        "review_after",
                        "last_checked_at",
                        "card_sha256",
                        "card_json",
                    }.issubset(candidate_columns):
                        table_name = candidate
                        columns = candidate_columns
                        break

                self.assertIsNotNone(table_name)
                self.assertTrue(columns)
                row = connection.execute(
                    f'SELECT schema_version, required_gate, review_after, '
                    f'last_checked_at, card_sha256, card_json FROM "{table_name}"'
                ).fetchone()

            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], "1.1")
            self.assertEqual(row[1], "read_only")
            self.assertEqual(row[2], "2099-01-01T00:00:00Z")
            self.assertEqual(row[3], "2026-08-20T09:00:00Z")
            self.assertRegex(row[4], r"^[0-9a-f]{64}$")
            self.assertEqual(json.loads(row[5])["schemaVersion"], "1.1")


if __name__ == "__main__":
    unittest.main()
