#!/usr/bin/env python3
"""Machine-evaluable, fail-closed checks for KS read-back responses."""

from __future__ import annotations

from typing import Any


CHECK_OPERATORS = ("equals", "notEquals", "exists", "contains", "length")
CHECK_METADATA_KEYS = {"id", "description"}
MISSING = object()


class ReadBackCheckError(RuntimeError):
    """Raised when declared read-back checks are invalid or do not match."""


def _path_tokens(path: str) -> list[str]:
    if path == "$" or path == "":
        return []
    if path.startswith("/"):
        return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    if path.startswith("$."):
        path = path[2:]
    return path.split(".")


def _resolve_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for token in _path_tokens(path):
        if isinstance(current, dict):
            if token not in current:
                return False, MISSING
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit():
                return False, MISSING
            index = int(token)
            if index >= len(current):
                return False, MISSING
            current = current[index]
            continue
        return False, MISSING
    return True, current


def _json_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
    if (
        isinstance(actual, (int, float))
        and isinstance(expected, (int, float))
        and not isinstance(actual, bool)
        and not isinstance(expected, bool)
    ):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            _json_equal(left, right) for left, right in zip(actual, expected)
        )
    if isinstance(actual, dict):
        return set(actual) == set(expected) and all(
            _json_equal(actual[key], expected[key]) for key in actual
        )
    return actual == expected


def _json_contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, list):
        return any(_json_equal(item, expected) for item in actual)
    if isinstance(actual, str):
        return isinstance(expected, str) and expected in actual
    if isinstance(actual, dict):
        return isinstance(expected, str) and expected in actual
    return False


def validate_readback_checks(checks: Any) -> list[str]:
    """Return definition errors without inspecting or exposing response values."""
    if not isinstance(checks, list) or not checks:
        return ["checks must be a non-empty list of machine-readable objects"]

    errors: list[str] = []
    allowed_keys = {"path", *CHECK_OPERATORS, *CHECK_METADATA_KEYS}
    for index, check in enumerate(checks, start=1):
        prefix = f"check #{index}"
        if not isinstance(check, dict):
            errors.append(f"{prefix} must be an object, not descriptive text")
            continue
        path = check.get("path")
        if not isinstance(path, str):
            errors.append(f"{prefix} path must be a string")
        elif path not in {"", "$"} and (path.endswith(".") or ".." in path):
            errors.append(f"{prefix} path is malformed")

        operators = [name for name in CHECK_OPERATORS if name in check]
        if len(operators) != 1:
            errors.append(f"{prefix} must declare exactly one operator: {', '.join(CHECK_OPERATORS)}")
        elif operators[0] == "exists" and not isinstance(check["exists"], bool):
            errors.append(f"{prefix} exists value must be boolean")
        elif operators[0] == "length" and (
            not isinstance(check["length"], int)
            or isinstance(check["length"], bool)
            or check["length"] < 0
        ):
            errors.append(f"{prefix} length value must be a non-negative integer")

        unknown = sorted(str(key) for key in check if key not in allowed_keys)
        if unknown:
            errors.append(f"{prefix} has unsupported keys: {', '.join(unknown)}")
    return errors


def evaluate_readback_checks(response: Any, checks: Any) -> dict[str, Any]:
    """Evaluate checks and return a value-free report safe to persist in logs."""
    definition_errors = validate_readback_checks(checks)
    if definition_errors:
        return {
            "valid": False,
            "definitionErrors": definition_errors,
            "results": [],
        }

    results: list[dict[str, Any]] = []
    for index, check in enumerate(checks, start=1):
        path = check["path"]
        operator = next(name for name in CHECK_OPERATORS if name in check)
        expected = check[operator]
        found, actual = _resolve_path(response, path)

        passed = False
        reason = "mismatch"
        if operator == "exists":
            passed = found is expected
            reason = "matched" if passed else "existence_mismatch"
        elif not found:
            reason = "path_missing"
        elif operator == "equals":
            passed = _json_equal(actual, expected)
            reason = "matched" if passed else "value_mismatch"
        elif operator == "notEquals":
            passed = not _json_equal(actual, expected)
            reason = "matched" if passed else "value_mismatch"
        elif operator == "contains":
            passed = _json_contains(actual, expected)
            reason = "matched" if passed else "contains_mismatch"
        elif operator == "length":
            try:
                passed = len(actual) == expected
            except TypeError:
                passed = False
            reason = "matched" if passed else "length_mismatch"

        result = {
            "index": index,
            "path": path,
            "operator": operator,
            "passed": passed,
            "reason": reason,
        }
        if isinstance(check.get("id"), str):
            result["id"] = check["id"]
        results.append(result)

    return {
        "valid": all(result["passed"] for result in results),
        "definitionErrors": [],
        "results": results,
    }


def require_readback_checks(report: dict[str, Any]) -> None:
    """Raise a concise error when a persisted check report is not valid."""
    if report.get("valid") is True:
        return
    failures = []
    for result in report.get("results") or []:
        if not result.get("passed"):
            failures.append(f"#{result.get('index')} {result.get('path')} ({result.get('reason')})")
    if report.get("definitionErrors"):
        failures.append("invalid check definition")
    detail = "; ".join(failures) or "no valid checks"
    raise ReadBackCheckError(f"readBack checks failed closed: {detail}")
