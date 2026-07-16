#!/usr/bin/env python3
"""Run a bundled read-only KS project audit.

The runner either consumes an existing snapshot JSON or creates one with the
adjacent ks_project_snapshot.py script. It does not execute write, runtime,
integration run, BPMS start/complete, import/export, or server operations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def get_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("uuid", "UUID", "id", "ID", "referenceUuid", "ReferenceUUID"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def get_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("name", "Name", "title", "Title"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    value = item.get("l10n")
    if isinstance(value, dict):
        name = value.get("name") or value.get("Name")
        if isinstance(name, str):
            return name
    return ""


def section(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    value = snapshot.get("sections", {}).get(name, {})
    return value if isinstance(value, dict) else {}


def section_items(snapshot: dict[str, Any], name: str) -> list[dict[str, Any]]:
    items = section(snapshot, name).get("items", [])
    return [item for item in items if isinstance(item, dict)]


def section_count(snapshot: dict[str, Any], name: str) -> int:
    current = section(snapshot, name)
    if "items" in current:
        return len(section_items(snapshot, name))
    count = current.get("count")
    return int(count) if isinstance(count, int) else 0


def raw_data(snapshot: dict[str, Any], name: str) -> list[dict[str, Any]]:
    raw = section(snapshot, name).get("raw")
    if not isinstance(raw, dict):
        return []
    data = raw.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        rows = []
        for uuid, item in data.items():
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("uuid", uuid)
                rows.append(row)
        return rows
    for key in ("integrations", "sources", "integrationTables", "items", "list"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def detail_count(snapshot: dict[str, Any], name: str) -> int:
    details = section(snapshot, name).get("details")
    return len(details) if isinstance(details, dict) else 0


def run_command(command: list[str], *, log_path: Path) -> tuple[int, str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(command),
                "",
                "## stdout",
                result.stdout,
                "",
                "## stderr",
                result.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return result.returncode, result.stdout + result.stderr


def require_script(name: str) -> Path:
    path = script_dir() / name
    if not path.exists():
        raise SystemExit(f"Missing bundled script: {path}")
    return path


def create_snapshot(args: argparse.Namespace, out_dir: Path) -> Path:
    snapshot_script = require_script("ks_project_snapshot.py")
    snapshot = out_dir / "snapshot.json"
    command = [
        sys.executable,
        str(snapshot_script),
        "--out",
        str(snapshot),
        "--map-out",
        str(out_dir / "project_map.md"),
        "--details-limit",
        str(args.details_limit),
    ]
    if args.include_object_samples:
        command.append("--include-object-samples")
    code, output = run_command(command, log_path=out_dir / "logs" / "snapshot.log")
    if code != 0:
        raise SystemExit(f"Snapshot failed; see {out_dir / 'logs' / 'snapshot.log'}\n{output}")
    return snapshot


def run_report(script_name: str, snapshot: Path, out_dir: Path, *extra: str) -> bool:
    script = require_script(script_name)
    command = [sys.executable, str(script), str(snapshot), *extra]
    code, output = run_command(command, log_path=out_dir / "logs" / f"{script_name}.log")
    if code != 0:
        (out_dir / "logs" / f"{script_name}.failed.txt").write_text(output, encoding="utf-8")
        return False
    return True


def dashboard_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    body = load_json(path)
    rows = body.get("rows") if isinstance(body.get("rows"), list) else []
    overlaps = body.get("overlaps") if isinstance(body.get("overlaps"), dict) else {}
    risky = [row for row in rows if isinstance(row, dict) and row.get("risks")]
    overlap_count = sum(len(value) for value in overlaps.values() if isinstance(value, list))
    return {
        "available": True,
        "cells": len(rows),
        "riskyCells": len(risky),
        "overlaps": overlap_count,
    }


def table_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    text = path.read_text(encoding="utf-8")
    return {
        "available": True,
        "tablesWithRisks": text.count("- Status: `risk`"),
        "tablesOk": text.count("- Status: `ok`"),
    }


def integration_summary(snapshot: dict[str, Any], out_path: Path) -> dict[str, Any]:
    integrations = {item.get("uuid"): item for item in section_items(snapshot, "integrations") if item.get("uuid")}
    operations_root = section(snapshot, "integrations").get("operations", {})
    rules_root = section(snapshot, "integrations").get("fieldRules", {})
    conditions_root = section(snapshot, "integrations").get("outputSamplingConditions", {})
    rows = []
    total_operations = 0
    total_rules = 0
    total_conditions = 0
    disabled_operations = 0
    for uuid, integration in sorted(integrations.items(), key=lambda item: get_name(item[1]).casefold()):
        operations_body = operations_root.get(uuid, {}) if isinstance(operations_root, dict) else {}
        operations = operations_body.get("operations", []) if isinstance(operations_body, dict) else []
        operations = [op for op in operations if isinstance(op, dict)]
        operation_ids = {op.get("uuid") for op in operations}
        rules_body = rules_root.get(uuid, {}) if isinstance(rules_root, dict) else {}
        rules = rules_body.get("fieldsRules", []) if isinstance(rules_body, dict) else []
        rules = [rule for rule in rules if isinstance(rule, dict) and rule.get("operationUuid") in operation_ids]
        conditions_body = conditions_root.get(uuid, {}) if isinstance(conditions_root, dict) else {}
        conditions = []
        if isinstance(conditions_body, dict):
            raw_conditions = conditions_body.get("outputSamplingConditions") or conditions_body.get("samplingConditions")
            if isinstance(raw_conditions, list):
                conditions = [
                    item for item in raw_conditions if isinstance(item, dict) and item.get("operationUuid") in operation_ids
                ]
        disabled = sum(1 for op in operations if op.get("disabled"))
        total_operations += len(operations)
        total_rules += len(rules)
        total_conditions += len(conditions)
        disabled_operations += disabled
        rows.append(
            [
                get_name(integration) or "<unnamed>",
                uuid,
                str(len(operations)),
                str(len(rules)),
                str(len(conditions)),
                str(disabled),
            ]
        )
    lines = [
        "# KS Integration Read-Only Summary",
        "",
        "| Integration | UUID | Operations | Field rules | Output sampling | Disabled ops |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    if not rows:
        lines.append("| none | - | 0 | 0 | 0 | 0 |")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "available": True,
        "integrations": len(integrations),
        "operations": total_operations,
        "fieldRules": total_rules,
        "outputSamplingConditions": total_conditions,
        "disabledOperations": disabled_operations,
    }


def bpms_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "processes": section_count(snapshot, "processes"),
        "tasks": section_count(snapshot, "tasks"),
    }


def write_summary(
    *,
    snapshot: Path,
    snapshot_body: dict[str, Any],
    out_dir: Path,
    dashboard: dict[str, Any],
    tables: dict[str, Any],
    integrations: dict[str, Any],
) -> Path:
    errors = snapshot_body.get("errors")
    errors = errors if isinstance(errors, list) else []
    sections = [
        "models",
        "classes",
        "indicators",
        "dictionaries",
        "objects",
        "dataTables",
        "dashboards",
        "publications",
        "integrations",
        "integrationSources",
        "integrationTables",
        "processes",
        "tasks",
    ]
    project_map = out_dir / "project_map.md"
    project_map_cell = f"`{project_map}`" if project_map.exists() else "not generated; existing snapshot was used"
    lines = [
        "# KS Read-Only Audit Summary",
        "",
        f"- generatedAt: `{utc_now()}`",
        f"- mode: `read_only`",
        f"- projectUuid: `{snapshot_body.get('projectUuid')}`",
        f"- snapshotCreatedAt: `{snapshot_body.get('createdAt')}`",
        f"- snapshot: `{snapshot}`",
        f"- snapshotErrors: `{len(errors)}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Path |",
        "| --- | --- |",
        f"| Snapshot JSON | `{snapshot}` |",
        f"| Project map | {project_map_cell} |",
        f"| Dashboard cell report | `{out_dir / 'dashboard_cell_report.md'}` |",
        f"| Dashboard cell JSON | `{out_dir / 'dashboard_cell_report.json'}` |",
        f"| Data table audit | `{out_dir / 'table_audit.md'}` |",
        f"| BPMS audit | `{out_dir / 'bpms_audit.md'}` |",
        f"| Integration summary | `{out_dir / 'integration_summary.md'}` |",
        "",
        "## Project Counts",
        "",
        "| Section | Count | Details |",
        "| --- | ---: | ---: |",
    ]
    for name in sections:
        lines.append(f"| {name} | {section_count(snapshot_body, name)} | {detail_count(snapshot_body, name)} |")
    lines.extend(
        [
            "",
            "## Audit Signals",
            "",
            f"- Dashboard cells: `{dashboard.get('cells', 'n/a')}`",
            f"- Dashboard risky cells: `{dashboard.get('riskyCells', 'n/a')}`",
            f"- Dashboard overlaps: `{dashboard.get('overlaps', 'n/a')}`",
            f"- Data tables with risks: `{tables.get('tablesWithRisks', 'n/a')}`",
            f"- Data tables OK: `{tables.get('tablesOk', 'n/a')}`",
            f"- Integrations: `{integrations.get('integrations', 'n/a')}`",
            f"- Integration operations: `{integrations.get('operations', 'n/a')}`",
            f"- Integration field rules: `{integrations.get('fieldRules', 'n/a')}`",
            f"- Integration output sampling conditions: `{integrations.get('outputSamplingConditions', 'n/a')}`",
            f"- Disabled integration operations: `{integrations.get('disabledOperations', 'n/a')}`",
            f"- BPMS processes: `{bpms_summary(snapshot_body)['processes']}`",
            f"- BPMS tasks: `{bpms_summary(snapshot_body)['tasks']}`",
            "",
        ]
    )
    if errors:
        lines.extend(["## Snapshot Errors", ""])
        for error in errors[:50]:
            lines.append(f"- `{json.dumps(error, ensure_ascii=False)}`")
        if len(errors) > 50:
            lines.append(f"- ... {len(errors) - 50} more")
        lines.append("")
    lines.extend(
        [
            "## Safety Notes",
            "",
            "- This runner is read-only by design.",
            "- Do not treat this report as approval to write, run integrations, start BPMS, import/export, delete, or change access.",
            "- For any repair, create a safe patch plan, read current state first, apply only project-scoped changes, and verify read-back.",
            "",
            "## Suggested Next Triage",
            "",
            "1. Inspect snapshot errors first; missing optional endpoints can be acceptable, but auth/project-scope failures are blockers.",
            "2. Inspect dashboard risks/overlaps before changing layouts or events.",
            "3. Inspect table risks before blaming dashboard cells for blank table rendering.",
            "4. Inspect integration/BPMS summaries in read-only mode; execute runtime actions only after exact approval.",
        ]
    )
    summary = out_dir / "audit_summary.md"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Existing read-only project snapshot JSON")
    parser.add_argument("--out-dir", type=Path, default=Path("ks_readonly_audit_out"))
    parser.add_argument("--details-limit", type=int, default=300, help="Max details when creating a snapshot")
    parser.add_argument("--include-object-samples", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = args.snapshot.resolve() if args.snapshot else create_snapshot(args, out_dir).resolve()
    if not snapshot.exists():
        raise SystemExit(f"Snapshot does not exist: {snapshot}")

    run_report(
        "ks_dashboard_cell_report.py",
        snapshot,
        out_dir,
        "--out",
        str(out_dir / "dashboard_cell_report.md"),
        "--json-out",
        str(out_dir / "dashboard_cell_report.json"),
    )
    run_report("ks_table_audit.py", snapshot, out_dir, "--output", str(out_dir / "table_audit.md"))
    run_report("ks_bpms_audit.py", snapshot, out_dir, "--output", str(out_dir / "bpms_audit.md"))

    snapshot_body = load_json(snapshot)
    integrations = integration_summary(snapshot_body, out_dir / "integration_summary.md")
    summary = write_summary(
        snapshot=snapshot,
        snapshot_body=snapshot_body,
        out_dir=out_dir.resolve(),
        dashboard=dashboard_summary(out_dir / "dashboard_cell_report.json"),
        tables=table_summary(out_dir / "table_audit.md"),
        integrations=integrations,
    )
    print(f"summary: {summary}")
    print(f"outDir: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
