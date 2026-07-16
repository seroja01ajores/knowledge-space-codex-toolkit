#!/usr/bin/env python3
"""Shared fail-closed text redaction helpers for KS tooling reports/errors."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote, quote_plus


SENSITIVE_KEY_PATTERN = (
    r"password|passwd|passphrase|token|secret|authorization|cookie|csrf|jwt|"
    r"api[_-]?key|access[_-]?key|credential(?:s)?|private[_-]?key|ssh[_-]?key"
)
AUTH_INLINE_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[^\s,;|\"']+")
INLINE_SECRET_RE = re.compile(
    rf"(?i)\b({SENSITIVE_KEY_PATTERN})\s*([:=])\s*"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;|]+)"
)
STRUCTURED_SECRET_KEY_RE = re.compile(
    rf"(?i)[\"'](?:{SENSITIVE_KEY_PATTERN})[\"']\s*:"
)
STRUCTURED_PARAMETER_SECRET_RE = re.compile(
    rf"(?is)[\"'](?:name|key|field|parameter|header)[\"']\s*:\s*"
    rf"[\"'](?:{SENSITIVE_KEY_PATTERN})[\"']"
)
XML_SECRET_RE = re.compile(
    rf"(?is)<\s*(?:{SENSITIVE_KEY_PATTERN})\b[^>]*>.*?"
    rf"</\s*(?:{SENSITIVE_KEY_PATTERN})\s*>"
)
XML_PARAMETER_SECRET_RE = re.compile(
    rf"(?is)<\s*(?:name|key|field|parameter|header)\b[^>]*>\s*"
    rf"(?:{SENSITIVE_KEY_PATTERN})\s*</"
)
URI_USERINFO_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/?#]*@")
PRIVATE_KEY_MARKER_RE = re.compile(
    r"-----BEGIN (?:ENCRYPTED )?(?:(?:OPENSSH|RSA|EC|DSA) )?PRIVATE KEY-----",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(
    rf"(?:{SENSITIVE_KEY_PATTERN})",
    re.I,
)
KNOWN_TOKEN_RE = re.compile(
    r"(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"(?:sk|rk)_live_[A-Za-z0-9]{16,}|"
    r"AIza[0-9A-Za-z_-]{35}"
    r")"
)

SEMANTIC_SECRET_DISCRIMINATORS = {"name", "key", "field", "parameter", "header"}
SEMANTIC_SECRET_VALUES = {"value", "data", "content"}


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def semantic_secret_value_keys(value: dict[Any, Any]) -> set[Any]:
    """Return value keys paired with a name/key discriminator naming a secret."""
    has_sensitive_discriminator = any(
        _normalized_key(key) in SEMANTIC_SECRET_DISCRIMINATORS
        and isinstance(item, str)
        and is_sensitive_key(item)
        for key, item in value.items()
    )
    if not has_sensitive_discriminator:
        return set()
    return {
        key
        for key in value
        if _normalized_key(key) in SEMANTIC_SECRET_VALUES
    }


def sensitive_value_paths(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[str, ...]]:
    """Locate direct and semantic secret value fields in nested containers."""
    paths: list[tuple[str, ...]] = []
    if isinstance(value, dict):
        semantic_keys = semantic_secret_value_keys(value)
        for key, item in value.items():
            current = (*path, str(key))
            if is_sensitive_key(key) or key in semantic_keys:
                paths.append(current)
            paths.extend(sensitive_value_paths(item, current))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(sensitive_value_paths(item, (*path, str(index))))
    return paths


def _normalized_structured_text(value: str) -> str:
    """Expose JSON escaped keys for fail-closed secret recognition."""
    def replace_unicode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    exposed = re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode, value)
    return exposed.replace(r'\"', '"').replace(r"\'", "'")


def is_sensitive_key(value: object) -> bool:
    return bool(SENSITIVE_KEY_RE.search(str(value)))


def redact_text(value: str, secret_values: Iterable[str] = ()) -> str:
    """Redact explicit values and common embedded credential representations."""
    if PRIVATE_KEY_MARKER_RE.search(value):
        return "<redacted-private-key>"
    structured = _normalized_structured_text(value)
    if (
        STRUCTURED_SECRET_KEY_RE.search(structured)
        or STRUCTURED_PARAMETER_SECRET_RE.search(structured)
        or XML_SECRET_RE.search(structured)
        or XML_PARAMETER_SECRET_RE.search(structured)
    ):
        return "<redacted-structured-secret>"
    secrets = sorted(
        {secret for secret in secret_values if isinstance(secret, str) and secret},
        key=len,
        reverse=True,
    )
    encoded_secrets: set[str] = set()
    for secret in secrets:
        encoded_secrets.update(
            {
                secret,
                json.dumps(secret, ensure_ascii=False)[1:-1],
                quote(secret, safe=""),
                quote_plus(secret, safe=""),
            }
        )
    for secret in sorted(encoded_secrets, key=len, reverse=True):
        if secret:
            value = value.replace(secret, "<redacted>")
    value = KNOWN_TOKEN_RE.sub("<redacted>", value)
    value = AUTH_INLINE_RE.sub(lambda match: f"{match.group(1)} <redacted>", value)
    value = INLINE_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        value,
    )
    value = URI_USERINFO_RE.sub(r"\1<redacted>@", value)
    if value.count(".") == 2 and len(value) > 80 and not any(character.isspace() for character in value):
        return "<redacted>"
    return value


def text_contains_secret(value: str) -> bool:
    """Return whether shared redaction recognizes a concrete secret representation."""
    return redact_text(value) != value
