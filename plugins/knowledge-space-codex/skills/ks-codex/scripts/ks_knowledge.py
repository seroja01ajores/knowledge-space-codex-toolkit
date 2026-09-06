#!/usr/bin/env python3
"""Validate and search private KS knowledge cards without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from ks_safe_files import SafePathError, preflight_output_file, strict_json_loads
from ks_secret_safety import redact_text, text_contains_secret


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
PLUGIN_ROOT = SKILL_ROOT.parents[1]
MAX_CARD_BYTES = 1024 * 1024
MAX_CARDS = 10_000
MAX_RESULTS = 5
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSIONS = {"1.0", "1.1"}
STATUSES = {"observation", "candidate", "verified", "promoted", "superseded"}
SCOPES = {"portable", "organization", "stand", "project"}
VISIBILITIES = {"public", "private"}
SENSITIVITIES = {"public-safe", "internal", "restricted"}
RISK_CLASSES = {
    "read_only",
    "local_artifact_write",
    "project_write",
    "external_or_runtime",
    "destructive_or_global",
    "server_or_db",
}
INDEX_VERSION = "1.1"


class KnowledgeError(RuntimeError):
    """Raised when private knowledge cannot be handled safely."""


def _safe_root(value: Path, *, create: bool = False) -> Path:
    raw = value.expanduser()
    if raw.is_symlink():
        raise KnowledgeError("root path must not be a symlink")
    if create:
        raw.mkdir(parents=True, exist_ok=True)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise KnowledgeError("root path is unavailable") from exc
    if not resolved.is_dir():
        raise KnowledgeError("root path must be a directory")
    return resolved


def _relative(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts:
        raise KnowledgeError(f"{label} must be a relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise KnowledgeError(f"{label} contains a forbidden path component")
    return path


def _resolve_file(root: Path, relative_value: str | Path, *, label: str) -> Path:
    relative = _relative(relative_value, label=label)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise KnowledgeError(f"{label} must not traverse a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise KnowledgeError(f"{label} is unavailable") from exc
    if not resolved.is_file():
        raise KnowledgeError(f"{label} must be a regular file")
    return resolved


def _outside_plugin(root: Path) -> Path:
    resolved = _safe_root(root, create=True)
    plugin = PLUGIN_ROOT.resolve(strict=True)
    try:
        resolved.relative_to(plugin)
    except ValueError:
        return resolved
    raise KnowledgeError("derived knowledge databases must stay outside the plugin")


def _card_files(cards_root: Path) -> list[Path]:
    root = _safe_root(cards_root)
    files: list[Path] = []

    def walk_error(error: OSError) -> None:
        raise KnowledgeError("cannot scan cards root safely") from error

    for current_value, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=walk_error,
        followlinks=False,
    ):
        current = Path(current_value)
        for name in sorted(directory_names):
            if (current / name).is_symlink():
                raise KnowledgeError("cards root contains a symlink directory")
        for name in sorted(file_names):
            candidate = current / name
            if candidate.is_symlink():
                raise KnowledgeError("cards root contains a symlink file")
            if candidate.suffix.casefold() != ".json":
                continue
            files.append(candidate)
            if len(files) > MAX_CARDS:
                raise KnowledgeError("cards root exceeds the card-count limit")
    return sorted(files)


def _read_card(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise KnowledgeError("card must be a regular file")
        if info.st_size > MAX_CARD_BYTES:
            raise KnowledgeError("card exceeds the one-megabyte limit")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MAX_CARD_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_CARD_BYTES:
        raise KnowledgeError("card exceeds the one-megabyte limit")
    try:
        value = strict_json_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, SafePathError) as exc:
        raise KnowledgeError("card is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise KnowledgeError("card must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise KnowledgeError(f"{label} must be a non-empty bounded string")
    return value


def _strings(
    value: Any,
    *,
    label: str,
    minimum: int = 0,
    maximum_items: int = 100,
    maximum_length: int = 4000,
) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum_items:
        raise KnowledgeError(f"{label} must be a bounded string array")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or len(item) > maximum_length
        for item in value
    ):
        raise KnowledgeError(f"{label} contains an invalid string")
    if len(set(value)) != len(value):
        raise KnowledgeError(f"{label} must not contain duplicates")
    return list(value)


def _timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise KnowledgeError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise KnowledgeError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _timestamp_or_none(value: Any, *, label: str) -> datetime | None:
    if value is None:
        return None
    return _timestamp(value, label=label)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_of(value: str | None) -> datetime:
    return (
        _timestamp(value, label="asOf")
        if value is not None
        else datetime.now(timezone.utc)
    )


def _validate_v11(card: dict[str, Any], updated_at: datetime) -> None:
    applicability = card.get("applicability")
    if not isinstance(applicability, dict) or set(applicability) != {
        "capabilities",
        "endpointFamilies",
        "requiredGate",
    }:
        raise KnowledgeError(
            "schema 1.1 applicability shape is invalid"
        )
    capabilities = _strings(
        applicability["capabilities"],
        label="applicability.capabilities",
        minimum=1,
        maximum_items=100,
        maximum_length=100,
    )
    if any(not ID_RE.fullmatch(item) for item in capabilities):
        raise KnowledgeError(
            "applicability.capabilities must contain lowercase slugs"
        )
    _strings(
        applicability["endpointFamilies"],
        label="applicability.endpointFamilies",
        maximum_items=100,
        maximum_length=500,
    )
    if applicability["requiredGate"] not in RISK_CLASSES:
        raise KnowledgeError("applicability.requiredGate is invalid")

    learning = card.get("learning")
    if not isinstance(learning, dict) or set(learning) != {
        "rejectedHypotheses",
        "remainingUnknowns",
    }:
        raise KnowledgeError("schema 1.1 learning shape is invalid")
    _strings(
        learning["rejectedHypotheses"],
        label="learning.rejectedHypotheses",
        maximum_items=100,
    )
    _strings(
        learning["remainingUnknowns"],
        label="learning.remainingUnknowns",
        maximum_items=100,
    )

    freshness = card.get("freshness")
    if not isinstance(freshness, dict) or set(freshness) != {
        "verifiedAt",
        "lastCheckedAt",
        "reviewAfter",
    }:
        raise KnowledgeError("schema 1.1 freshness shape is invalid")
    verified_at = _timestamp_or_none(
        freshness["verifiedAt"], label="freshness.verifiedAt"
    )
    last_checked_at = _timestamp(
        freshness["lastCheckedAt"], label="freshness.lastCheckedAt"
    )
    review_after = _timestamp_or_none(
        freshness["reviewAfter"], label="freshness.reviewAfter"
    )
    if verified_at is not None and verified_at > last_checked_at:
        raise KnowledgeError(
            "freshness.verifiedAt must not be after lastCheckedAt"
        )
    if review_after is not None and review_after <= last_checked_at:
        raise KnowledgeError(
            "freshness.reviewAfter must be after lastCheckedAt"
        )
    if last_checked_at > updated_at:
        raise KnowledgeError(
            "freshness.lastCheckedAt must not be after updatedAt"
        )
    if card["status"] in {"verified", "promoted"} and (
        verified_at is None or review_after is None
    ):
        raise KnowledgeError(
            "verified and promoted cards require verifiedAt and reviewAfter"
        )

    promotion = card.get("promotion")
    if not isinstance(promotion, dict) or set(promotion) != {
        "independentReview",
        "publicRedactionReview",
        "evidenceHashes",
    }:
        raise KnowledgeError("schema 1.1 promotion shape is invalid")
    for field in ("independentReview", "publicRedactionReview"):
        if not isinstance(promotion[field], bool):
            raise KnowledgeError(f"promotion.{field} must be boolean")
    evidence_hashes = _strings(
        promotion["evidenceHashes"],
        label="promotion.evidenceHashes",
        maximum_items=100,
        maximum_length=64,
    )
    if any(not SHA256_RE.fullmatch(item) for item in evidence_hashes):
        raise KnowledgeError(
            "promotion.evidenceHashes must contain lowercase SHA-256 values"
        )
    if card["status"] == "promoted" and (
        not promotion["independentReview"]
        or not promotion["publicRedactionReview"]
        or not evidence_hashes
    ):
        raise KnowledgeError(
            "promoted cards require independent review, redaction review, "
            "and promotion evidence"
        )


def freshness_state(card: dict[str, Any], *, as_of: datetime) -> str:
    if card["status"] == "superseded":
        return "superseded"
    if card["schemaVersion"] == "1.0":
        return "unknown"
    review_after = _timestamp_or_none(
        card["freshness"]["reviewAfter"], label="freshness.reviewAfter"
    )
    if review_after is None:
        return "unverified"
    return "fresh" if review_after >= as_of else "review-due"


def validate_card(card: dict[str, Any], *, filename: str | None = None) -> dict[str, Any]:
    allowed = {
        "schemaVersion",
        "id",
        "title",
        "intent",
        "domains",
        "symptoms",
        "ksVersions",
        "scope",
        "visibility",
        "status",
        "confidence",
        "sensitivity",
        "preconditions",
        "solution",
        "evidence",
        "verification",
        "tags",
        "applicability",
        "learning",
        "freshness",
        "promotion",
        "supersededBy",
        "updatedAt",
    }
    unknown = sorted(set(card) - allowed)
    if unknown:
        raise KnowledgeError(f"card contains unsupported fields: {', '.join(unknown)}")
    schema_version = card.get("schemaVersion")
    if schema_version not in SCHEMA_VERSIONS:
        raise KnowledgeError("unsupported card schemaVersion")
    card_id = card.get("id")
    if not isinstance(card_id, str) or not ID_RE.fullmatch(card_id):
        raise KnowledgeError("card id must use lower-case kebab-case")
    if filename is not None and Path(filename).stem != card_id:
        raise KnowledgeError("card filename must match card id")
    _text(card.get("title"), label="title", maximum=200)
    _text(card.get("intent"), label="intent", maximum=1000)
    _strings(card.get("domains"), label="domains", minimum=1, maximum_length=100)
    _strings(card.get("symptoms"), label="symptoms")
    _strings(
        card.get("ksVersions"),
        label="ksVersions",
        minimum=1,
        maximum_length=100,
    )
    if card.get("scope") not in SCOPES:
        raise KnowledgeError("scope is invalid")
    if card.get("visibility") not in VISIBILITIES:
        raise KnowledgeError("visibility is invalid")
    if card.get("status") not in STATUSES:
        raise KnowledgeError("status is invalid")
    confidence = card.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise KnowledgeError("confidence must be numeric")
    if not 0 <= float(confidence) <= 1:
        raise KnowledgeError("confidence must be between zero and one")
    if card.get("sensitivity") not in SENSITIVITIES:
        raise KnowledgeError("sensitivity is invalid")
    _strings(card.get("preconditions"), label="preconditions")
    _strings(card.get("tags"), label="tags", maximum_length=100)

    solution = card.get("solution")
    if not isinstance(solution, dict) or set(solution) != {"summary", "steps"}:
        raise KnowledgeError("solution requires exactly summary and steps")
    _text(solution.get("summary"), label="solution.summary", maximum=4000)
    _strings(solution.get("steps"), label="solution.steps", maximum_items=50)

    evidence = card.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 100:
        raise KnowledgeError("evidence must be a bounded array")
    for position, item in enumerate(evidence):
        if not isinstance(item, dict) or set(item) != {"type", "source", "sourceHash"}:
            raise KnowledgeError(f"evidence[{position}] shape is invalid")
        if item["type"] not in {
            "synthetic-test",
            "api-readback",
            "browser-check",
            "normalized-capture",
            "documentation",
        }:
            raise KnowledgeError(f"evidence[{position}].type is invalid")
        _text(item["source"], label=f"evidence[{position}].source", maximum=500)
        if not isinstance(item["sourceHash"], str) or not SHA256_RE.fullmatch(
            item["sourceHash"]
        ):
            raise KnowledgeError(f"evidence[{position}].sourceHash is invalid")

    verification = card.get("verification")
    if not isinstance(verification, dict) or set(verification) != {
        "apiReadback",
        "browserVerified",
        "syntheticRegression",
        "notes",
    }:
        raise KnowledgeError("verification shape is invalid")
    for key in ("apiReadback", "browserVerified", "syntheticRegression"):
        if not isinstance(verification[key], bool):
            raise KnowledgeError(f"verification.{key} must be boolean")
    _strings(verification["notes"], label="verification.notes")

    superseded_by = card.get("supersededBy")
    if superseded_by is not None and (
        not isinstance(superseded_by, str) or not ID_RE.fullmatch(superseded_by)
    ):
        raise KnowledgeError("supersededBy must be null or a card id")
    updated_at = _timestamp(card.get("updatedAt"), label="updatedAt")

    if card["status"] == "superseded" and superseded_by is None:
        raise KnowledgeError("superseded cards require supersededBy")
    if card["status"] != "superseded" and superseded_by is not None:
        raise KnowledgeError("supersededBy is allowed only for superseded cards")
    if card["status"] in {"observation", "candidate"} and (
        card["visibility"] != "private"
    ):
        raise KnowledgeError("observation and candidate cards must stay private")
    if schema_version == "1.1":
        _validate_v11(card, updated_at)

    if card["visibility"] == "public" and (
        card["scope"] != "portable" or card["sensitivity"] != "public-safe"
    ):
        raise KnowledgeError("public cards must be portable and public-safe")
    serialized = json.dumps(card, ensure_ascii=False, sort_keys=True)
    if text_contains_secret(serialized):
        raise KnowledgeError("card contains a recognized secret representation")
    return card


def load_cards(cards_root: Path) -> list[dict[str, Any]]:
    root = _safe_root(cards_root)
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in _card_files(root):
        card = validate_card(_read_card(path), filename=path.name)
        if card["id"] in seen:
            raise KnowledgeError(f"duplicate card id: {card['id']}")
        seen.add(card["id"])
        cards.append(card)
    by_id = {card["id"]: card for card in cards}
    for card in cards:
        target = card.get("supersededBy")
        if target is not None and target not in by_id:
            raise KnowledgeError(
                f"superseded card {card['id']} references a missing card"
            )
        if target == card["id"]:
            raise KnowledgeError(f"card {card['id']} supersedes itself")
    for card in cards:
        chain: set[str] = set()
        current = card
        while current.get("supersededBy") is not None:
            if current["id"] in chain:
                raise KnowledgeError(
                    f"supersession cycle includes {current['id']}"
                )
            chain.add(current["id"])
            current = by_id[current["supersededBy"]]
    return cards


def promotion_report(
    card: dict[str, Any], *, as_of: datetime | None = None
) -> dict[str, Any]:
    validate_card(card)
    effective_as_of = as_of or datetime.now(timezone.utc)
    reasons: list[str] = []
    if card["schemaVersion"] != "1.1":
        reasons.append("schema 1.1 lifecycle metadata is required")
    if card["status"] not in {"verified", "promoted"}:
        reasons.append("status must be verified or promoted")
    if card["scope"] != "portable":
        reasons.append("scope must be portable")
    if card["visibility"] != "public":
        reasons.append("visibility must be public")
    if card["sensitivity"] != "public-safe":
        reasons.append("sensitivity must be public-safe")
    if not card["evidence"]:
        reasons.append("at least one evidence item is required")
    verification = card["verification"]
    if not verification["syntheticRegression"]:
        reasons.append("synthetic regression is required")
    if not (verification["apiReadback"] or verification["browserVerified"]):
        reasons.append("API read-back or browser verification is required")
    state = freshness_state(card, as_of=effective_as_of)
    if state != "fresh":
        reasons.append("card freshness must be fresh")
    if card["schemaVersion"] == "1.1":
        promotion = card["promotion"]
        if not promotion["independentReview"]:
            reasons.append("independent review is required")
        if not promotion["publicRedactionReview"]:
            reasons.append("public redaction review is required")
        if not promotion["evidenceHashes"]:
            reasons.append("promotion evidence hashes are required")
        if card["learning"]["remainingUnknowns"]:
            reasons.append("remaining unknowns must be resolved")
    return {
        "id": card["id"],
        "publicReady": not reasons,
        "freshness": state,
        "reasons": reasons,
    }


def _card_search_text(card: dict[str, Any]) -> tuple[str, ...]:
    applicability = card.get("applicability", {})
    learning = card.get("learning", {})
    return (
        card["title"],
        card["intent"],
        " ".join(card["domains"]),
        " ".join(card["symptoms"]),
        " ".join(card["tags"]),
        " ".join([card["solution"]["summary"], *card["solution"]["steps"]]),
        " ".join(applicability.get("capabilities", [])),
        " ".join(applicability.get("endpointFamilies", [])),
        " ".join(learning.get("rejectedHypotheses", [])),
    )


def _canonical_card_json(card: dict[str, Any]) -> str:
    return json.dumps(card, ensure_ascii=False, sort_keys=True)


def _card_sha256(card: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_card_json(card).encode("utf-8")).hexdigest()


def _create_database(path: Path, cards: Iterable[dict[str, Any]]) -> int:
    card_list = list(cards)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE cards (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                intent TEXT NOT NULL,
                scope TEXT NOT NULL,
                visibility TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                sensitivity TEXT NOT NULL,
                solution_summary TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                required_gate TEXT,
                review_after TEXT,
                last_checked_at TEXT,
                card_sha256 TEXT NOT NULL,
                card_json TEXT NOT NULL
            );
            CREATE TABLE card_domains (
                card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                domain TEXT NOT NULL,
                PRIMARY KEY (card_id, domain)
            );
            CREATE TABLE card_versions (
                card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                ks_version TEXT NOT NULL,
                PRIMARY KEY (card_id, ks_version)
            );
            CREATE TABLE card_capabilities (
                card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                capability TEXT NOT NULL,
                PRIMARY KEY (card_id, capability)
            );
            CREATE VIRTUAL TABLE cards_fts USING fts5(
                card_id UNINDEXED,
                title,
                intent,
                domains,
                symptoms,
                tags,
                solution,
                capabilities,
                endpoint_families,
                rejected_hypotheses
            );
            """
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("format", "teamvalue.ks-knowledge-index"),
                ("formatVersion", INDEX_VERSION),
                ("cardCount", str(len(card_list))),
            ),
        )
        for card in sorted(card_list, key=lambda item: item["id"]):
            serialized = _canonical_card_json(card)
            digest = _card_sha256(card)
            applicability = card.get("applicability", {})
            freshness = card.get("freshness", {})
            review_after = freshness.get("reviewAfter")
            last_checked_at = freshness.get("lastCheckedAt")
            connection.execute(
                """
                INSERT INTO cards(
                    id, title, intent, scope, visibility, status, confidence,
                    sensitivity, solution_summary, updated_at, schema_version,
                    required_gate, review_after, last_checked_at, card_sha256,
                    card_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    card["title"],
                    card["intent"],
                    card["scope"],
                    card["visibility"],
                    card["status"],
                    float(card["confidence"]),
                    card["sensitivity"],
                    card["solution"]["summary"],
                    card["updatedAt"],
                    card["schemaVersion"],
                    applicability.get("requiredGate"),
                    (
                        _timestamp_text(
                            _timestamp(review_after, label="freshness.reviewAfter")
                        )
                        if review_after is not None
                        else None
                    ),
                    (
                        _timestamp_text(
                            _timestamp(
                                last_checked_at,
                                label="freshness.lastCheckedAt",
                            )
                        )
                        if last_checked_at is not None
                        else None
                    ),
                    digest,
                    serialized,
                ),
            )
            connection.executemany(
                "INSERT INTO card_domains(card_id, domain) VALUES (?, ?)",
                ((card["id"], domain) for domain in card["domains"]),
            )
            connection.executemany(
                "INSERT INTO card_versions(card_id, ks_version) VALUES (?, ?)",
                ((card["id"], version) for version in card["ksVersions"]),
            )
            connection.executemany(
                "INSERT INTO card_capabilities(card_id, capability) VALUES (?, ?)",
                (
                    (card["id"], capability)
                    for capability in applicability.get("capabilities", [])
                ),
            )
            search_fields = _card_search_text(card)
            connection.execute(
                "INSERT INTO cards_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (card["id"], *search_fields),
            )
        connection.commit()
    except sqlite3.DatabaseError as exc:
        connection.rollback()
        raise KnowledgeError("SQLite FTS5 index build failed") from exc
    finally:
        connection.close()
    return len(card_list)


def build_index(cards_root: Path, database_root: Path, database: str | Path) -> dict[str, Any]:
    cards = load_cards(cards_root)
    root = _outside_plugin(database_root)
    relative = _relative(database, label="database")
    existed = (root / relative).exists()
    target = preflight_output_file(root, relative)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        count = _create_database(temporary, cards)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        temporary = Path()
    except Exception:
        if not existed and target.exists() and target.stat().st_size == 0:
            target.unlink(missing_ok=True)
        raise
    finally:
        if temporary != Path():
            temporary.unlink(missing_ok=True)
    return {
        "format": "teamvalue.ks-knowledge-index-build",
        "formatVersion": "1.0",
        "database": relative.as_posix(),
        "cardCount": count,
        "offlineOnly": True,
    }


def _query_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE):
        if len(token) < 2 or token in tokens:
            continue
        tokens.append(token)
        if len(tokens) == 16:
            break
    if not tokens:
        raise KnowledgeError("query has no searchable terms")
    return tokens


def _connect_index_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        if metadata.get("format") != "teamvalue.ks-knowledge-index":
            raise KnowledgeError("unsupported knowledge database format")
        if metadata.get("formatVersion") != INDEX_VERSION:
            raise KnowledgeError(
                "knowledge database must be rebuilt for index format 1.1"
            )
        return connection
    except KnowledgeError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise KnowledgeError("knowledge database could not be opened safely") from exc


def _reuse_assessment(
    card: dict[str, Any],
    *,
    as_of: datetime,
    ks_version: str | None,
    require_portable: bool,
) -> dict[str, Any]:
    state = freshness_state(card, as_of=as_of)
    blockers: list[str] = []
    if card["schemaVersion"] != "1.1":
        blockers.append("legacy-schema")
    if card["status"] not in {"verified", "promoted"}:
        blockers.append(f"status:{card['status']}")
    if state != "fresh":
        blockers.append(f"freshness:{state}")
    if require_portable and card["scope"] != "portable":
        blockers.append(f"scope:{card['scope']}")
    if ks_version is not None and ks_version not in card["ksVersions"]:
        blockers.append("ks-version-mismatch")
    remaining_unknowns = card.get("learning", {}).get("remainingUnknowns", [])
    if remaining_unknowns:
        blockers.append("remaining-unknowns")
    return {
        "disposition": (
            "requires-live-compatibility-check"
            if not blockers
            else "hypothesis-only"
        ),
        "fastPathBlockers": blockers,
        "freshness": state,
        "requestedKsVersion": ks_version,
        "requiresPortableScope": require_portable,
        "requiredGate": card.get("applicability", {}).get("requiredGate"),
        "livePreconditions": list(card["preconditions"]),
    }


def _full_card_result(
    card: dict[str, Any],
    *,
    digest: str,
    source: str,
    as_of: datetime,
    ks_version: str | None,
    require_portable: bool,
) -> dict[str, Any]:
    return {
        "format": "teamvalue.ks-knowledge-card",
        "formatVersion": "1.0",
        "source": source,
        "cardSha256": digest,
        "reuseAssessment": _reuse_assessment(
            card,
            as_of=as_of,
            ks_version=ks_version,
            require_portable=require_portable,
        ),
        "card": card,
        "offlineOnly": True,
        "authenticatesProvenance": False,
        "authorizesExecution": False,
    }


def inspect_card(
    cards_root: Path,
    card: str | Path,
    *,
    ks_version: str | None = None,
    require_portable: bool = False,
    as_of: str | None = None,
) -> dict[str, Any]:
    root = _safe_root(cards_root)
    path = _resolve_file(root, card, label="card")
    value = validate_card(_read_card(path), filename=path.name)
    return _full_card_result(
        value,
        digest=_card_sha256(value),
        source="card-file",
        as_of=_as_of(as_of),
        ks_version=ks_version,
        require_portable=require_portable,
    )


def _validated_index_card(row: sqlite3.Row, card_id: str) -> dict[str, Any]:
    try:
        raw = strict_json_loads(row["card_json"])
    except SafePathError as exc:
        raise KnowledgeError("indexed knowledge card is not strict JSON") from exc
    if not isinstance(raw, dict):
        raise KnowledgeError("indexed knowledge card must be a JSON object")
    value = validate_card(raw)
    if value["id"] != card_id:
        raise KnowledgeError("indexed knowledge card id is inconsistent")
    if _card_sha256(value) != row["card_sha256"]:
        raise KnowledgeError("indexed knowledge card content hash is inconsistent")
    return value


def get_index_card(
    database_root: Path,
    database: str | Path,
    card_id: str,
    expected_sha256: str,
    *,
    ks_version: str | None = None,
    require_portable: bool = False,
    as_of: str | None = None,
) -> dict[str, Any]:
    if not ID_RE.fullmatch(card_id):
        raise KnowledgeError("card id must use lower-case kebab-case")
    if not SHA256_RE.fullmatch(expected_sha256):
        raise KnowledgeError("expected card SHA-256 is invalid")
    root = _safe_root(database_root)
    path = _resolve_file(root, database, label="database")
    connection = _connect_index_readonly(path)
    try:
        row = connection.execute(
            "SELECT card_sha256, card_json FROM cards WHERE id = ?",
            (card_id,),
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise KnowledgeError("knowledge database card lookup failed") from exc
    finally:
        connection.close()
    if row is None:
        raise KnowledgeError("knowledge card was not found")
    if row["card_sha256"] != expected_sha256:
        raise KnowledgeError("knowledge card hash does not match search evidence")
    value = _validated_index_card(row, card_id)
    return _full_card_result(
        value,
        digest=row["card_sha256"],
        source="knowledge-index",
        as_of=_as_of(as_of),
        ks_version=ks_version,
        require_portable=require_portable,
    )


def search_index(
    database_root: Path,
    database: str | Path,
    query: str,
    *,
    domains: list[str] | None = None,
    capabilities: list[str] | None = None,
    ks_versions: list[str] | None = None,
    scopes: list[str] | None = None,
    statuses: list[str] | None = None,
    include_review_due: bool = False,
    ready_only: bool = False,
    as_of: str | None = None,
    limit: int = MAX_RESULTS,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise KnowledgeError("query must be non-empty")
    if text_contains_secret(query):
        raise KnowledgeError("query contains a recognized secret representation")
    if not 1 <= limit <= MAX_RESULTS:
        raise KnowledgeError(f"limit must be between 1 and {MAX_RESULTS}")
    root = _safe_root(database_root)
    path = _resolve_file(root, database, label="database")
    requested_statuses = statuses or ["verified", "promoted"]
    if any(status not in STATUSES for status in requested_statuses):
        raise KnowledgeError("status filter is invalid")
    if scopes and any(scope not in SCOPES for scope in scopes):
        raise KnowledgeError("scope filter is invalid")
    if capabilities and any(
        not isinstance(capability, str) or not ID_RE.fullmatch(capability)
        for capability in capabilities
    ):
        raise KnowledgeError("capability filter is invalid")
    effective_as_of = _as_of(as_of)
    effective_as_of_text = _timestamp_text(effective_as_of)

    tokens = _query_tokens(query)
    match = " OR ".join(f'"{token}"' for token in tokens)
    where = [
        "cards_fts MATCH ?",
        f"c.status IN ({','.join('?' for _ in requested_statuses)})",
    ]
    parameters: list[Any] = [match, *requested_statuses]
    for domain in domains or []:
        where.append(
            "EXISTS (SELECT 1 FROM card_domains d WHERE d.card_id = c.id AND d.domain = ?)"
        )
        parameters.append(domain)
    for capability in capabilities or []:
        where.append(
            "EXISTS (SELECT 1 FROM card_capabilities k "
            "WHERE k.card_id = c.id AND k.capability = ?)"
        )
        parameters.append(capability)
    for version in ks_versions or []:
        where.append(
            "EXISTS (SELECT 1 FROM card_versions v WHERE v.card_id = c.id AND v.ks_version = ?)"
        )
        parameters.append(version)
    if scopes:
        where.append(f"c.scope IN ({','.join('?' for _ in scopes)})")
        parameters.extend(scopes)
    if not include_review_due:
        where.append("(c.review_after IS NULL OR c.review_after >= ?)")
        parameters.append(effective_as_of_text)
    if not ready_only:
        parameters.append(limit)
    statement = f"""
        SELECT
            c.id,
            c.title,
            c.scope,
            c.status,
            c.confidence,
            c.sensitivity,
            c.solution_summary,
            c.updated_at,
            c.schema_version,
            c.required_gate,
            c.review_after,
            c.card_sha256,
            {'c.card_json,' if ready_only else ''}
            bm25(cards_fts) AS relevance
        FROM cards_fts
        JOIN cards c ON c.id = cards_fts.card_id
        WHERE {' AND '.join(where)}
        ORDER BY
            CASE WHEN c.schema_version = '1.1' THEN 0 ELSE 1 END ASC,
            relevance ASC,
            c.confidence DESC,
            c.id ASC
        {'' if ready_only else 'LIMIT ?'}
    """
    connection = _connect_index_readonly(path)
    try:
        rows = []
        for row in connection.execute(statement, parameters):
            if ready_only:
                card = _validated_index_card(row, row["id"])
                if any(
                    _reuse_assessment(
                        card,
                        as_of=effective_as_of,
                        ks_version=version,
                        require_portable=set(scopes or []) == {"portable"},
                    )["fastPathBlockers"]
                    for version in ks_versions or [None]
                ):
                    continue
            rows.append(row)
            if len(rows) == limit:
                break
    except sqlite3.DatabaseError as exc:
        raise KnowledgeError("knowledge database search failed") from exc
    finally:
        connection.close()
    return {
        "format": "teamvalue.ks-knowledge-search",
        "formatVersion": "1.0",
        "querySha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "filters": {
            "domains": domains or [],
            "capabilities": capabilities or [],
            "ksVersions": ks_versions or [],
            "scopes": scopes or [],
            "statuses": requested_statuses,
            "includeReviewDue": include_review_due,
            "readyOnly": ready_only,
            "asOf": effective_as_of_text,
        },
        "resultCount": len(rows),
        "results": [
            {
                "id": row["id"],
                "title": row["title"],
                "scope": row["scope"],
                "status": row["status"],
                "confidence": row["confidence"],
                "sensitivity": row["sensitivity"],
                "summary": row["solution_summary"],
                "updatedAt": row["updated_at"],
                "schemaVersion": row["schema_version"],
                "requiredGate": row["required_gate"],
                "reviewAfter": row["review_after"],
                "freshness": (
                    "unknown"
                    if row["schema_version"] == "1.0"
                    else (
                        "unverified"
                        if row["review_after"] is None
                        else (
                            "fresh"
                            if row["review_after"] >= effective_as_of_text
                            else "review-due"
                        )
                    )
                ),
                "cardSha256": row["card_sha256"],
                "relevance": round(float(row["relevance"]), 6),
            }
            for row in rows
        ],
        "offlineOnly": True,
        "authenticatesProvenance": False,
        "authorizesExecution": False,
    }


def lifecycle_report(
    cards: list[dict[str, Any]], *, as_of: datetime
) -> dict[str, Any]:
    states = {
        card["id"]: freshness_state(card, as_of=as_of) for card in cards
    }
    status_counts = {
        status: sum(card["status"] == status for card in cards)
        for status in sorted(STATUSES)
    }
    freshness_counts = {
        state: sum(value == state for value in states.values())
        for state in (
            "fresh",
            "review-due",
            "unknown",
            "unverified",
            "superseded",
        )
    }
    promotion = [
        promotion_report(card, as_of=as_of)
        for card in cards
        if card["status"] in {"candidate", "verified", "promoted"}
    ]
    return {
        "format": "teamvalue.ks-knowledge-lifecycle",
        "formatVersion": "1.0",
        "asOf": _timestamp_text(as_of),
        "cardCount": len(cards),
        "statusCounts": status_counts,
        "freshnessCounts": freshness_counts,
        "reviewDue": sorted(
            card_id
            for card_id, state in states.items()
            if state == "review-due"
        ),
        "migrationRequired": sorted(
            card["id"] for card in cards if card["schemaVersion"] == "1.0"
        ),
        "promotionReady": sorted(
            item["id"] for item in promotion if item["publicReady"]
        ),
        "promotionBlocked": [
            item for item in promotion if not item["publicReady"]
        ],
        "offlineOnly": True,
        "authorizesExecution": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and search private KS knowledge cards offline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--cards-root", type=Path, required=True)

    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--cards-root", type=Path, required=True)
    index_parser.add_argument("--database-root", type=Path, required=True)
    index_parser.add_argument("--database", required=True)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--database-root", type=Path, required=True)
    search_parser.add_argument("--database", required=True)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--domain", action="append", default=[])
    search_parser.add_argument("--capability", action="append", default=[])
    search_parser.add_argument("--ks-version", action="append", default=[])
    search_parser.add_argument("--scope", action="append", default=[])
    search_parser.add_argument("--status", action="append", default=[])
    search_parser.add_argument("--include-review-due", action="store_true")
    search_parser.add_argument("--ready-only", action="store_true")
    search_parser.add_argument("--as-of")
    search_parser.add_argument("--limit", type=int, default=MAX_RESULTS)

    inspect_parser = subparsers.add_parser("inspect-card")
    inspect_parser.add_argument("--cards-root", type=Path, required=True)
    inspect_parser.add_argument("--card", required=True)
    inspect_parser.add_argument("--ks-version")
    inspect_parser.add_argument("--require-portable", action="store_true")
    inspect_parser.add_argument("--as-of")

    get_parser = subparsers.add_parser("get-card")
    get_parser.add_argument("--database-root", type=Path, required=True)
    get_parser.add_argument("--database", required=True)
    get_parser.add_argument("--card-id", required=True)
    get_parser.add_argument("--expected-sha256", required=True)
    get_parser.add_argument("--ks-version")
    get_parser.add_argument("--require-portable", action="store_true")
    get_parser.add_argument("--as-of")

    promotion_parser = subparsers.add_parser("promotion-check")
    promotion_parser.add_argument("--cards-root", type=Path, required=True)
    promotion_parser.add_argument("--card", required=True)
    promotion_parser.add_argument("--as-of")

    lifecycle_parser = subparsers.add_parser("lifecycle-report")
    lifecycle_parser.add_argument("--cards-root", type=Path, required=True)
    lifecycle_parser.add_argument("--as-of")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            cards = load_cards(args.cards_root)
            result = {
                "format": "teamvalue.ks-knowledge-validation",
                "formatVersion": "1.0",
                "valid": True,
                "cardCount": len(cards),
                "offlineOnly": True,
            }
        elif args.command == "index":
            result = build_index(args.cards_root, args.database_root, args.database)
        elif args.command == "search":
            result = search_index(
                args.database_root,
                args.database,
                args.query,
                domains=args.domain,
                capabilities=args.capability,
                ks_versions=args.ks_version,
                scopes=args.scope,
                statuses=args.status or None,
                include_review_due=args.include_review_due,
                ready_only=args.ready_only,
                as_of=args.as_of,
                limit=args.limit,
            )
        elif args.command == "inspect-card":
            result = inspect_card(
                args.cards_root,
                args.card,
                ks_version=args.ks_version,
                require_portable=args.require_portable,
                as_of=args.as_of,
            )
        elif args.command == "get-card":
            result = get_index_card(
                args.database_root,
                args.database,
                args.card_id,
                args.expected_sha256,
                ks_version=args.ks_version,
                require_portable=args.require_portable,
                as_of=args.as_of,
            )
        elif args.command == "promotion-check":
            root = _safe_root(args.cards_root)
            path = _resolve_file(root, args.card, label="card")
            card = validate_card(_read_card(path), filename=path.name)
            result = promotion_report(card, as_of=_as_of(args.as_of))
        else:
            cards = load_cards(args.cards_root)
            result = lifecycle_report(cards, as_of=_as_of(args.as_of))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("publicReady", True) else 3
    except (KnowledgeError, SafePathError, OSError, ValueError) as exc:
        message = redact_text(str(exc)).replace(str(Path.home()), "~")
        raise SystemExit(f"knowledge operation failed: {message}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
