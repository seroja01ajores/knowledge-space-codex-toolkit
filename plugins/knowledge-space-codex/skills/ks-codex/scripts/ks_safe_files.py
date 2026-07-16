#!/usr/bin/env python3
"""Fail-closed local JSON input and atomic output helpers for KS plans."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


MAX_JSON_PAYLOAD_BYTES = 64 * 1024 * 1024


class SafePathError(RuntimeError):
    """Raised when an input/output path escapes its declared local root."""


def _reject_constant(value: str) -> None:
    raise SafePathError(f"non-standard JSON constant is forbidden: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SafePathError("duplicate JSON object key is forbidden")
        value[key] = item
    return value


def strict_json_loads(text: str) -> Any:
    """Parse standard JSON while rejecting duplicate object keys."""
    try:
        return json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except SafePathError:
        raise
    except json.JSONDecodeError as exc:
        raise SafePathError(f"invalid JSON: {exc}") from exc


def _relative_path(value: str | Path, *, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise SafePathError(f"{label} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute():
        raise SafePathError(f"{label} must be relative to its declared root")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SafePathError(f"{label} contains a forbidden path component")
    return path


def _root(path: Path, *, create: bool) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise SafePathError(f"root path must not be a symlink: {raw}")
    if create:
        raw.mkdir(parents=True, exist_ok=True)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise SafePathError(f"root path is unavailable: {raw}: {exc}") from exc
    if not resolved.is_dir():
        raise SafePathError(f"root path is not a directory: {resolved}")
    return resolved


def _assert_within(candidate: Path, root: Path, *, label: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafePathError(f"{label} escapes its declared root") from exc


def _walk_without_symlinks(root: Path, relative: Path, *, create_parents: bool) -> Path:
    current = root
    parts = relative.parts
    for index, part in enumerate(parts):
        current = current / part
        is_final = index == len(parts) - 1
        if current.is_symlink():
            raise SafePathError(f"symlink path component is forbidden: {current}")
        if not is_final and not current.exists():
            if not create_parents:
                raise SafePathError(f"path component does not exist: {current}")
            current.mkdir()
        if not is_final and not current.is_dir():
            raise SafePathError(f"path component is not a directory: {current}")
    return current


def read_json_relative(
    base_dir: Path,
    relative_value: str | Path,
    *,
    label: str = "payloadPath",
    max_bytes: int = MAX_JSON_PAYLOAD_BYTES,
) -> Any:
    """Read a regular, non-symlink JSON file strictly below base_dir."""
    root = _root(base_dir, create=False)
    relative = _relative_path(relative_value, label=label)
    candidate = _walk_without_symlinks(root, relative, create_parents=False)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SafePathError(f"{label} is unavailable: {candidate}: {exc}") from exc
    _assert_within(resolved, root, label=label)

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise SafePathError(f"cannot open {label}: {candidate}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SafePathError(f"{label} must reference a regular file")
        if info.st_size > max_bytes:
            raise SafePathError(
                f"{label} exceeds the {max_bytes}-byte local safety limit"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise SafePathError(
                f"{label} exceeds the {max_bytes}-byte local safety limit"
            )
    finally:
        os.close(descriptor)
    try:
        text = raw.decode("utf-8")
        return strict_json_loads(text)
    except SafePathError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafePathError(f"{label} is not valid UTF-8 JSON: {exc}") from exc


def prepare_output_root(out_dir: Path) -> Path:
    """Create and return a non-symlink output root."""
    return _root(out_dir, create=True)


def prepare_output_subdir(out_dir: Path, relative_value: str | Path) -> Path:
    """Create a symlink-free child directory before any external side effect."""
    root = _root(out_dir, create=False)
    relative = _relative_path(relative_value, label="output directory")
    candidate = _walk_without_symlinks(root, relative, create_parents=True)
    if candidate.is_symlink():
        raise SafePathError(f"output directory must not be a symlink: {candidate}")
    if candidate.exists() and not candidate.is_dir():
        raise SafePathError(f"output directory is not a directory: {candidate}")
    candidate.mkdir(exist_ok=True)
    resolved = candidate.resolve(strict=True)
    _assert_within(resolved, root, label="output directory")
    return resolved


def preflight_output_file(out_dir: Path, relative_value: str | Path) -> Path:
    """Reserve a symlink-free regular output target before external effects."""
    root = _root(out_dir, create=False)
    relative = _relative_path(relative_value, label="output path")
    target = _walk_without_symlinks(root, relative, create_parents=True)
    target_parent = target.parent.resolve(strict=True)
    _assert_within(target_parent, root, label="output path")
    if target.is_symlink():
        raise SafePathError(f"output target must not be a symlink: {target}")
    if target.exists():
        if not target.is_file():
            raise SafePathError(f"output target is not a regular file: {target}")
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(target, flags, 0o600)
        except OSError as exc:
            raise SafePathError(f"cannot reserve output target: {target}: {exc}") from exc
        os.close(descriptor)
    probe_path: str | None = None
    probe_descriptor: int | None = None
    try:
        probe_descriptor, probe_path = tempfile.mkstemp(
            prefix=".ks-output-preflight-",
            dir=target_parent,
        )
        os.fsync(probe_descriptor)
        os.close(probe_descriptor)
        probe_descriptor = None
        os.unlink(probe_path)
        probe_path = None
    except OSError as exc:
        raise SafePathError(
            f"output parent cannot create/replace atomic files: {target_parent}: {exc}"
        ) from exc
    finally:
        if probe_descriptor is not None:
            try:
                os.close(probe_descriptor)
            except OSError:
                pass
        if probe_path is not None:
            try:
                os.unlink(probe_path)
            except OSError:
                pass
    return target


def atomic_write_bytes(
    out_dir: Path,
    relative_value: str | Path,
    data: bytes,
    *,
    mode: int = 0o600,
) -> Path:
    """Atomically write below out_dir without following child symlinks."""
    root = _root(out_dir, create=False)
    relative = _relative_path(relative_value, label="output path")
    target = _walk_without_symlinks(root, relative, create_parents=True)
    target_parent = target.parent.resolve(strict=True)
    _assert_within(target_parent, root, label="output path")
    if target.exists() and not target.is_file():
        raise SafePathError(f"output target is not a regular file: {target}")
    if target.is_symlink():
        raise SafePathError(f"output target must not be a symlink: {target}")

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target_parent
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        if target.is_symlink():
            raise SafePathError(f"output target became a symlink: {target}")
        os.replace(temporary_path, target)
        temporary_path = None
        return target
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(
    out_dir: Path,
    relative_value: str | Path,
    text: str,
    *,
    mode: int = 0o600,
) -> Path:
    return atomic_write_bytes(
        out_dir,
        relative_value,
        text.encode("utf-8"),
        mode=mode,
    )
