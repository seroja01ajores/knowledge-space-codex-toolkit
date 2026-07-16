#!/usr/bin/env python3
"""Audit KS analyst descriptions/comments from a read-only project snapshot.

The tool never calls KS. It identifies where ordinary `description` fields are
observed, where comments are unsupported/uncertain, and can create a dry-run
safe patch plan for dashboard descriptions.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SECRET_RE = re.compile(r"(password|парол|token|secret|authorization|cookie|jwt|ssh|private key|connection string|dsn)", re.I)

SUPPORTED_WRITE = {
    "dashboards": {
        "read": "/dashboards/get-by-id",
        "write": "/dashboards/update",
        "strategy": "read full dashboard, change top-level description, send raw dashboard object",
    },
    "processes": {
        "read": "/processes/get-by-ids",
        "write": "/processes/update",
        "strategy": "verify exact process update payload on the stand, preserve enabled/settings/model/diagram",
    },
}

OBSERVED_DESCRIPTION_SECTIONS = {
    "dashboards",
    "classes",
    "indicators",
    "dictionaries",
    "dataTables",
    "processes",
    "tasks",
    "integrations",
    "integrationSources",
    "integrationTables",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    l10n = item.get("l10n")
    if isinstance(l10n, dict):
        value = l10n.get("name") or l10n.get("Name")
        if isinstance(value, str) and value:
            return value
    return ""


def unwrap_dashboard(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        if isinstance(detail.get("dashboard"), dict):
            return detail["dashboard"]
        data = detail.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("dashboard"), dict):
                return data["dashboard"]
            if "configuration" in data:
                return data
        if "configuration" in detail:
            return detail
    return {}


def section_items(snapshot: dict[str, Any], section: str) -> list[dict[str, Any]]:
    sec = snapshot.get("sections", {}).get(section, {})
    if not isinstance(sec, dict):
        return []
    if section == "dashboards" and isinstance(sec.get("details"), dict) and sec["details"]:
        return [item for item in (unwrap_dashboard(value) for value in sec["details"].values()) if item]
    if section == "dataTables" and isinstance(sec.get("details"), dict) and sec["details"]:
        return [value for value in sec["details"].values() if isinstance(value, dict)]
    raw = sec.get("raw")
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            rows = []
            for uuid, item in data.items():
                if isinstance(item, dict):
                    copied = dict(item)
                    copied.setdefault("uuid", uuid)
                    rows.append(copied)
            return rows
        for key in ("integrations", "sources", "integrationTables"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    items = sec.get("items", [])
    return [item for item in items if isinstance(item, dict)]


def description_state(item: dict[str, Any]) -> tuple[str, str]:
    if "description" not in item:
        return "absent", ""
    value = item.get("description")
    if value is None:
        return "empty", ""
    if isinstance(value, str):
        return ("present" if value.strip() else "empty"), value
    return "non_string", str(value)


def suggested_description(section: str, name: str) -> str:
    base = name or "элемент KS"
    if section == "dashboards":
        return f"Назначение интерфейса: {base}. Описание добавлено для аналитиков; перед изменениями проверяйте связанные таблицы, события и публикацию."
    if section == "processes":
        return f"Назначение бизнес-процесса: {base}. Перед запуском проверьте задачи, интеграции, модель/набор данных и ожидаемые записи."
    return f"Назначение элемента: {base}. Уточните бизнес-смысл, источники данных и ограничения перед использованием."


def has_secret(text: str) -> bool:
    return bool(SECRET_RE.search(text))


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = ["| " + " | ".join(rows[0][i].ljust(widths[i]) for i in range(len(widths))) + " |"]
    out.append("| " + " | ".join("-" * widths[i] for i in range(len(widths))) + " |")
    for row in rows[1:]:
        out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(widths))) + " |")
    return "\n".join(out)


def build_report_and_plan(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    snapshot = load_json(args.snapshot)
    project_uuid = snapshot.get("projectUuid") or "<project_uuid>"
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    rows = [["Section", "Name", "UUID", "State", "Write support", "Note"]]
    findings: list[str] = []
    operations: list[dict[str, Any]] = []
    suggestions_left = args.max_suggestions

    for section in sorted(OBSERVED_DESCRIPTION_SECTIONS):
        for item in section_items(snapshot, section):
            uuid = get_id(item) or ""
            name = get_name(item) or "<unnamed>"
            state, description = description_state(item)
            counts[section][state] += 1
            write = SUPPORTED_WRITE.get(section)
            support = "verified" if section == "dashboards" else ("needs stand verification" if write else "read-only/uncertain")
            note = ""
            if state == "absent":
                note = "ordinary description field not observed; do not invent custom storage"
            elif state == "empty":
                note = "candidate for analyst description"
            elif has_secret(description):
                note = "review: description may contain secret-like wording"
                findings.append(f"{section} {name} ({uuid}) has secret-like wording in description")
            rows.append([section, name, uuid, state, support, note])
            if args.plan_output and suggestions_left > 0 and state == "empty" and section in SUPPORTED_WRITE:
                suggestion = suggested_description(section, name)
                if has_secret(suggestion):
                    findings.append(f"suggestion for {section} {name} contains secret-like wording; skipped")
                    continue
                read_payload = {"UUID": uuid} if section == "dashboards" else {"uuids": [uuid]}
                operations.append({
                    "id": f"describe-{section}-{uuid}",
                    "endpoint": SUPPORTED_WRITE[section]["write"],
                    "method": "POST",
                    "risk": "project_write",
                    "entityType": section.rstrip("s"),
                    "entityUuid": uuid,
                    "entityName": name,
                    "summary": "Add analyst-facing description without changing runtime labels or data bindings",
                    "readBefore": {"endpoint": SUPPORTED_WRITE[section]["read"], "payload": read_payload},
                    "descriptionDraft": suggestion,
                    "payloadBuildHint": SUPPORTED_WRITE[section]["strategy"],
                    "readBack": {
                        "endpoint": SUPPORTED_WRITE[section]["read"],
                        "manualChecks": [
                            "description equals the approved text",
                            "name/labels/events/data bindings are unchanged",
                            "description contains no credentials, tokens, connection strings, or personal secrets",
                        ],
                    },
                    "executionReady": False,
                    "blockingReason": "Build and review the full entity payload, then add response-shape-specific machine checks before approval.",
                    "rollback": "Restore the pre-read entity JSON or previous description value.",
                })
                suggestions_left -= 1

    reports = ["# KS Comment/Description Audit", ""]
    reports.append(f"Snapshot: `{args.snapshot}`")
    reports.append(f"Project UUID: `{project_uuid}`")
    reports.append("")
    reports.append("## Summary")
    reports.append("")
    summary_rows = [["Section", "present", "empty", "absent", "non_string"]]
    for section in sorted(counts):
        summary_rows.append([
            section,
            str(counts[section]["present"]),
            str(counts[section]["empty"]),
            str(counts[section]["absent"]),
            str(counts[section]["non_string"]),
        ])
    reports.append(markdown_table(summary_rows))
    reports.append("")
    reports.append("## Entity Details")
    reports.append("")
    reports.append(markdown_table(rows))
    reports.append("")
    reports.append("## Rules")
    reports.append("")
    reports.append("- Use verified `description` fields for analyst-facing rationale; do not write long notes into visible labels.")
    reports.append("- Dashboard descriptions can be patched by reading the full dashboard and sending `/dashboards/update` with only top-level `description` changed.")
    reports.append("- For classes, indicators, dictionaries, data tables, cells, integrations, and tasks, verify the update endpoint on the current stand before writing descriptions.")
    reports.append("- Do not store passwords, tokens, cookies, source connection strings, SSH keys, customer secrets, or personal data in comments/descriptions.")
    reports.append("")
    reports.append("## Findings")
    reports.append("")
    if findings:
        reports.extend(f"- {item}" for item in findings)
    else:
        reports.append("No secret-like descriptions found by the offline scan.")
    reports.append("")
    if args.plan_output:
        reports.append(f"Generated plan operations: {len(operations)}")
        reports.append("")
    plan = {
        "metadata": {
            "task": "analyst descriptions dry-run",
            "targetProjectUuid": project_uuid,
            "mode": "dry_run",
            "sourceSnapshot": str(args.snapshot),
        },
        "approval": {"userApproved": False, "approvedOperationIds": [], "approvedEndpoints": []},
        "operations": operations,
    }
    return "\n".join(reports).rstrip() + "\n", plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline KS comments/descriptions audit")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--max-suggestions", type=int, default=12)
    args = parser.parse_args()
    report, plan = build_report_and_plan(args)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    if args.plan_output:
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        args.plan_output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
