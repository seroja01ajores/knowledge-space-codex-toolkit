#!/usr/bin/env python3
"""Build a deterministic, validated portable Knowledge Space Codex plugin ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PLUGIN_ROOT = REPO_ROOT / "plugins" / "knowledge-space-codex"
EXPECTED_PLUGIN_NAME = "knowledge-space-codex"
ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
REPORT_FORMAT = "teamvalue.codex-portable-plugin-build"
REPORT_FORMAT_VERSION = "1.0"

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

EXCLUDED_DIRECTORY_NAMES = {"__pycache__"}
EXCLUDED_FILE_NAMES = {".DS_Store"}
FORBIDDEN_DIRECTORY_NAMES = {
    "backups",
    "captures",
    "certificates",
    "certs",
    "keys",
}
FORBIDDEN_FILE_SUFFIXES = {
    ".backup",
    ".bak",
    ".bkp",
    ".cer",
    ".crt",
    ".der",
    ".dump",
    ".har",
    ".jks",
    ".key",
    ".ksbackup",
    ".p12",
    ".pem",
    ".pfx",
    ".zst",
    ".zstd",
}
FORBIDDEN_FILE_NAMES = {
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

CONTENT_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "absolute-user-home-path",
        re.compile(rb"(?<![A-Za-z0-9])/(?:Users|home)(?:/|\b)"),
    ),
    (
        "credentialed-url",
        re.compile(rb"[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+:[^/@\s]+@"),
    ),
    (
        "private-key-block",
        re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "aws-access-key",
        re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    ),
    (
        "github-token",
        re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    ),
    (
        "slack-token",
        re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ),
    (
        "openai-style-secret-key",
        re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    ),
    (
        "live-api-secret-key",
        re.compile(rb"(?:sk|rk)_live_[A-Za-z0-9]{16,}"),
    ),
    (
        "google-api-key",
        re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    ),
    (
        "bearer-token",
        re.compile(rb"Bearer\s+[A-Za-z0-9._~+/-]{24,}={0,2}", re.IGNORECASE),
    ),
)


class ReleaseBuildError(RuntimeError):
    """Raised when portable release validation fails closed."""


@dataclass(frozen=True)
class ReleaseFile:
    relative_path: PurePosixPath
    data: bytes
    mode: int
    sha256: str


@dataclass(frozen=True)
class BuildResult:
    archive_path: Path
    checksum_path: Path
    report_path: Path
    archive_sha256: str
    file_count: int


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalized_mode(relative_path: PurePosixPath, data: bytes) -> int:
    if "scripts" in relative_path.parts and data.startswith(b"#!"):
        return 0o755
    return 0o644


def _path_violation(relative_path: PurePosixPath) -> str | None:
    lowered_parts = tuple(part.lower() for part in relative_path.parts)
    if any(part in FORBIDDEN_DIRECTORY_NAMES for part in lowered_parts[:-1]):
        return "forbidden-directory"

    filename = relative_path.name
    lowered_name = filename.lower()
    if lowered_name == ".env" or lowered_name.startswith(".env."):
        return "environment-file"
    if lowered_name in FORBIDDEN_FILE_NAMES:
        return "private-key-file"
    if any(lowered_name.endswith(suffix) for suffix in FORBIDDEN_FILE_SUFFIXES):
        return "forbidden-sensitive-artifact"
    return None


def _content_violations(data: bytes) -> list[str]:
    violations: list[str] = []
    if data.startswith(ZSTD_MAGIC):
        violations.append("zstd-payload")
    for label, pattern in CONTENT_RULES:
        if pattern.search(data):
            violations.append(label)
    return violations


def _collect_release_files(plugin_root: Path) -> list[ReleaseFile]:
    findings: list[str] = []
    files: list[ReleaseFile] = []

    def fail_on_walk_error(error: OSError) -> None:
        raise ReleaseBuildError(
            f"Cannot scan canonical plugin safely: {error.strerror or error}"
        ) from error

    for current_root, directory_names, file_names in os.walk(
        plugin_root,
        topdown=True,
        onerror=fail_on_walk_error,
        followlinks=False,
    ):
        current = Path(current_root)
        kept_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory_path = current / directory_name
            relative = PurePosixPath(directory_path.relative_to(plugin_root).as_posix())
            if directory_path.is_symlink():
                findings.append(f"{relative}: symlink-directory")
                continue
            if directory_name in EXCLUDED_DIRECTORY_NAMES:
                continue
            violation = _path_violation(relative / "placeholder")
            if violation:
                findings.append(f"{relative}: {violation}")
                continue
            kept_directories.append(directory_name)
        directory_names[:] = kept_directories

        for file_name in sorted(file_names):
            source_path = current / file_name
            relative = PurePosixPath(source_path.relative_to(plugin_root).as_posix())
            if source_path.is_symlink():
                findings.append(f"{relative}: symlink-file")
                continue
            if file_name in EXCLUDED_FILE_NAMES:
                continue
            if not source_path.is_file():
                findings.append(f"{relative}: non-regular-file")
                continue
            path_violation = _path_violation(relative)
            if path_violation:
                findings.append(f"{relative}: {path_violation}")
                continue

            try:
                data = source_path.read_bytes()
            except OSError as exc:
                raise ReleaseBuildError(
                    f"Cannot read canonical plugin file {relative}: "
                    f"{exc.strerror or exc}"
                ) from exc
            for content_violation in _content_violations(data):
                findings.append(f"{relative}: {content_violation}")
            files.append(
                ReleaseFile(
                    relative_path=relative,
                    data=data,
                    mode=_normalized_mode(relative, data),
                    sha256=_sha256_bytes(data),
                )
            )

    if findings:
        rendered = "\n".join(f"- {finding}" for finding in sorted(findings))
        raise ReleaseBuildError(
            "Portable plugin validation rejected sensitive or unsafe content:\n"
            + rendered
        )
    return sorted(files, key=lambda item: item.relative_path.as_posix())


def _parse_frontmatter_value(text: str, key: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", parts[1], re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip("\"'")


def _validate_structure(files: Iterable[ReleaseFile]) -> tuple[dict[str, object], list[str]]:
    by_path = {item.relative_path: item for item in files}
    manifest_path = PurePosixPath(".codex-plugin/plugin.json")
    manifest_file = by_path.get(manifest_path)
    if manifest_file is None:
        raise ReleaseBuildError("Missing .codex-plugin/plugin.json")

    try:
        manifest = json.loads(manifest_file.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError(f"Plugin manifest is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ReleaseBuildError("Plugin manifest must be a JSON object")

    name = manifest.get("name")
    version = manifest.get("version")
    skills_value = manifest.get("skills")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ReleaseBuildError("Plugin manifest name must be lower-case kebab-case")
    if name != EXPECTED_PLUGIN_NAME:
        raise ReleaseBuildError(
            f"Plugin manifest name must remain {EXPECTED_PLUGIN_NAME!r}, got {name!r}"
        )
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        raise ReleaseBuildError("Plugin manifest version must use strict semver")
    if not isinstance(skills_value, str) or not skills_value:
        raise ReleaseBuildError("Plugin manifest must declare a relative skills path")

    skills_path = PurePosixPath(skills_value.removeprefix("./"))
    if skills_path.is_absolute() or ".." in skills_path.parts or not skills_path.parts:
        raise ReleaseBuildError("Plugin manifest skills path must stay inside the plugin")

    skill_files = [
        item
        for path, item in by_path.items()
        if len(path.parts) == len(skills_path.parts) + 2
        and path.parts[: len(skills_path.parts)] == skills_path.parts
        and path.name == "SKILL.md"
    ]
    if not skill_files:
        raise ReleaseBuildError("Plugin must contain at least one skill with SKILL.md")

    skill_names: list[str] = []
    for skill_file in sorted(skill_files, key=lambda item: item.relative_path.as_posix()):
        try:
            text = skill_file.data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReleaseBuildError(f"{skill_file.relative_path} is not UTF-8") from exc
        skill_name = _parse_frontmatter_value(text, "name")
        description = _parse_frontmatter_value(text, "description")
        expected_name = skill_file.relative_path.parent.name
        if skill_name != expected_name:
            raise ReleaseBuildError(
                f"{skill_file.relative_path} name must match its folder {expected_name!r}"
            )
        if not description:
            raise ReleaseBuildError(
                f"{skill_file.relative_path} must declare a nonempty description"
            )
        skill_names.append(expected_name)

    return manifest, skill_names


def _write_archive(archive_path: Path, outer_folder: str, files: list[ReleaseFile]) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{archive_path.name}.",
            suffix=".tmp",
            dir=archive_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for item in files:
                archive_name = f"{outer_folder}/{item.relative_path.as_posix()}"
                info = zipfile.ZipInfo(archive_name, date_time=ARCHIVE_TIMESTAMP)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | item.mode) << 16
                archive.writestr(
                    info,
                    item.data,
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary_path, archive_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_portable_plugin(plugin_root: Path, output_dir: Path) -> BuildResult:
    plugin_root = plugin_root.resolve()
    output_dir = output_dir.resolve()
    if not plugin_root.is_dir():
        raise ReleaseBuildError(f"Canonical plugin directory does not exist: {plugin_root}")
    if plugin_root.name != EXPECTED_PLUGIN_NAME:
        raise ReleaseBuildError(
            f"Canonical plugin directory must be named {EXPECTED_PLUGIN_NAME!r}"
        )
    if _is_within(output_dir, plugin_root):
        raise ReleaseBuildError("Output directory must be outside the canonical plugin directory")

    files = _collect_release_files(plugin_root)
    manifest, skill_names = _validate_structure(files)
    name = str(manifest["name"])
    version = str(manifest["version"])
    archive_name = f"{name}-{version}.zip"
    checksum_name = f"{archive_name}.sha256"
    report_name = f"{name}-{version}.report.json"
    archive_path = output_dir / archive_name
    checksum_path = output_dir / checksum_name
    report_path = output_dir / report_name

    _write_archive(archive_path, EXPECTED_PLUGIN_NAME, files)
    archive_data = archive_path.read_bytes()
    archive_sha256 = _sha256_bytes(archive_data)
    checksum_data = f"{archive_sha256}  {archive_name}\n".encode("ascii")
    _atomic_write(checksum_path, checksum_data)
    report = {
        "format": REPORT_FORMAT,
        "formatVersion": REPORT_FORMAT_VERSION,
        "plugin": {
            "name": name,
            "version": version,
            "outerFolder": EXPECTED_PLUGIN_NAME,
            "skills": sorted(skill_names),
        },
        "archive": {
            "file": archive_name,
            "checksumFile": checksum_name,
            "bytes": len(archive_data),
            "sha256": archive_sha256,
            "fileCount": len(files),
        },
        "files": [
            {
                "path": f"{EXPECTED_PLUGIN_NAME}/{item.relative_path.as_posix()}",
                "bytes": len(item.data),
                "mode": f"{item.mode:04o}",
                "sha256": item.sha256,
            }
            for item in files
        ],
        "validation": {
            "valid": True,
            "excluded": ["**/__pycache__/**", "**/.DS_Store"],
            "sourceScope": "plugins/knowledge-space-codex only",
        },
    }
    report_data = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write(report_path, report_data)
    return BuildResult(
        archive_path=archive_path,
        checksum_path=checksum_path,
        report_path=report_path,
        archive_sha256=archive_sha256,
        file_count=len(files),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic portable Knowledge Space Codex plugin ZIP."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for the ZIP, SHA-256 checksum, and JSON build report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = build_portable_plugin(CANONICAL_PLUGIN_ROOT, args.output_dir)
    except ReleaseBuildError as exc:
        raise SystemExit(f"release build failed: {exc}") from exc
    print(
        json.dumps(
            {
                "archive": str(result.archive_path),
                "checksum": str(result.checksum_path),
                "report": str(result.report_path),
                "sha256": result.archive_sha256,
                "fileCount": result.file_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
