#!/usr/bin/env python3
"""Synthetic tests for the deterministic portable plugin release builder."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from tools import build_portable_plugin as builder
except ModuleNotFoundError:  # supports unittest discovery with tools on sys.path
    import build_portable_plugin as builder


class PortablePluginBuilderTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        plugin = root / "knowledge-space-codex"
        manifest_dir = plugin / ".codex-plugin"
        skill_dir = plugin / "skills" / "demo-skill"
        script_dir = skill_dir / "scripts"
        manifest_dir.mkdir(parents=True)
        script_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "knowledge-space-codex",
                    "version": "1.2.3+codex.test",
                    "description": "Synthetic portable plugin fixture.",
                    "author": {"name": "Test"},
                    "skills": "./skills/",
                    "interface": {
                        "displayName": "Test",
                        "shortDescription": "Test plugin",
                        "longDescription": "Synthetic test plugin.",
                        "developerName": "Test",
                        "category": "Productivity",
                        "capabilities": ["Read"],
                        "defaultPrompt": ["Run the synthetic test."],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: demo-skill\n"
            'description: "Use for deterministic builder tests."\n'
            "---\n\n"
            "# Demo skill\n",
            encoding="utf-8",
        )
        script = script_dir / "run.py"
        script.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
        script.chmod(0o700)
        ignored_cache = skill_dir / "__pycache__"
        ignored_cache.mkdir()
        (ignored_cache / "ignored.pyc").write_bytes(b"ignored")
        (skill_dir / ".DS_Store").write_bytes(b"ignored")
        return plugin

    def test_builds_minimal_valid_portable_zip_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin = self._fixture(root)
            output = root / "out"
            result = builder.build_portable_plugin(plugin, output)

            self.assertEqual(
                result.archive_path.name,
                "knowledge-space-codex-1.2.3+codex.test.zip",
            )
            self.assertEqual(
                result.checksum_path.read_text(encoding="ascii"),
                f"{result.archive_sha256}  {result.archive_path.name}\n",
            )
            self.assertTrue(result.report_path.is_file())
            with zipfile.ZipFile(result.archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, sorted(names))
                self.assertEqual(
                    names,
                    [
                        "knowledge-space-codex/.codex-plugin/plugin.json",
                        "knowledge-space-codex/skills/demo-skill/SKILL.md",
                        "knowledge-space-codex/skills/demo-skill/scripts/run.py",
                    ],
                )
                for info in archive.infolist():
                    self.assertEqual(info.date_time, builder.ARCHIVE_TIMESTAMP)
                script_info = archive.getinfo(
                    "knowledge-space-codex/skills/demo-skill/scripts/run.py"
                )
                self.assertEqual((script_info.external_attr >> 16) & 0o777, 0o755)
                manifest_info = archive.getinfo(
                    "knowledge-space-codex/.codex-plugin/plugin.json"
                )
                self.assertEqual((manifest_info.external_attr >> 16) & 0o777, 0o644)

            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["validation"]["valid"])
            self.assertEqual(report["plugin"]["skills"], ["demo-skill"])
            self.assertEqual(report["archive"]["fileCount"], 3)
            self.assertEqual(
                report["archive"]["checksumFile"], result.checksum_path.name
            )
            self.assertEqual(
                report["archive"]["sha256"],
                hashlib.sha256(result.archive_path.read_bytes()).hexdigest(),
            )

    def test_build_is_deterministic_across_output_directories_and_mtimes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin = self._fixture(root)
            first = builder.build_portable_plugin(plugin, root / "out-one")
            first_archive = first.archive_path.read_bytes()
            first_checksum = first.checksum_path.read_bytes()
            first_report = first.report_path.read_bytes()

            for path in plugin.rglob("*"):
                if path.is_file():
                    os.utime(path, (1_800_000_000, 1_800_000_000))
            second = builder.build_portable_plugin(plugin, root / "out-two")

            self.assertEqual(first_archive, second.archive_path.read_bytes())
            self.assertEqual(first_checksum, second.checksum_path.read_bytes())
            self.assertEqual(first_report, second.report_path.read_bytes())
            self.assertEqual(first.archive_sha256, second.archive_sha256)

    def test_forbidden_sensitive_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin = self._fixture(root)
            (plugin / ".env.production").write_text(
                "TOKEN=must-not-be-packaged\n",
                encoding="utf-8",
            )
            output = root / "out"

            with self.assertRaisesRegex(builder.ReleaseBuildError, "environment-file"):
                builder.build_portable_plugin(plugin, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
