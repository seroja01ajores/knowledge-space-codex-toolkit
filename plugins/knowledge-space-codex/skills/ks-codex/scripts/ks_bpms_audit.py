#!/usr/bin/env python3
"""Audit KS BPMS/process configuration from a read-only project snapshot.

This tool is intentionally offline: it never calls KS. It inspects snapshot JSON
created by ks_project_snapshot.py and reports business processes, tasks,
process-triggered integrations, unresolved references, and run-safety warnings.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ZERO_UUID = "00000000-0000-0000-0000-000000000000"

RUN_LIKE_CRITERIA = {
    "run_integration",
    "autocomplete_data",
    "set_interface_event",
    "change_dataset",
    "approval",
    "file_upload",
    "manual_input",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def get_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in ("uuid", "UUID", "id", "ID", "referenceUuid", "ReferenceUUID"):
        value = item.get(key)
        if isinstance(value, str) and value and value != ZERO_UUID:
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
    for key in ("integrations", "sources", "integrationTables"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def section_records(snapshot: dict[str, Any], name: str) -> list[dict[str, Any]]:
    raw = raw_data(snapshot, name)
    return raw if raw else section_items(snapshot, name)


def named_index(snapshot: dict[str, Any], name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in section_records(snapshot, name):
        uuid = get_id(item)
        if uuid:
            out[uuid] = get_name(item) or "<unnamed>"
    return out


def value_ci(item: dict[str, Any], *names: str) -> Any:
    if not isinstance(item, dict):
        return None
    for name in names:
        if name in item:
            return item[name]
    lowered = {str(key).lower(): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return None


def param_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("paramValue", "ParamValue", "value", "Value"):
            if key in value:
                return value[key]
    return value


def as_uuid_list(value: Any) -> list[str]:
    value = param_value(value)
    if isinstance(value, str):
        return [value] if UUID_RE.match(value) and value != ZERO_UUID else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and UUID_RE.match(item) and item != ZERO_UUID]
    return []


def collect_datasets(snapshot: dict[str, Any]) -> dict[str, str]:
    datasets = named_index(snapshot, "datasets")
    for model in section_records(snapshot, "models"):
        raw_datasets = model.get("datasets")
        if not isinstance(raw_datasets, list):
            continue
        for dataset in raw_datasets:
            if not isinstance(dataset, dict):
                continue
            uuid = get_id(dataset)
            if uuid:
                datasets[uuid] = get_name(dataset) or "<dataset>"
    return datasets


def resolve(uuid: str | None, names: dict[str, str]) -> str:
    if not uuid:
        return "-"
    name = names.get(uuid)
    return f"{name} (`{uuid}`)" if name else f"UNKNOWN (`{uuid}`)"


def task_summary(
    task: dict[str, Any],
    *,
    processes: dict[str, str],
    integrations: dict[str, str],
    models: dict[str, str],
    datasets: dict[str, str],
) -> dict[str, Any]:
    task_uuid = get_id(task) or ""
    name = get_name(task) or "<unnamed>"
    process_uuid = value_ci(task, "processUuid", "ProcessUUID")
    completion = value_ci(task, "completionCriteria", "CompletionCriteria") or ""
    next_uuid = value_ci(task, "nextElementUuid", "NextElementUUID")
    next_type = value_ci(task, "nextElementType", "NextElementType")
    settings = value_ci(task, "integrationSettings", "IntegrationSettings")
    settings = settings if isinstance(settings, dict) else {}
    integration_uuid = value_ci(settings, "integrationUuid", "IntegrationUUID")
    model_uuid = as_uuid_list(value_ci(settings, "modelUuid", "ModelUUID"))
    dataset_uuids = as_uuid_list(value_ci(settings, "datasetUuids", "DatasetUUIDs"))

    issues: list[str] = []
    warnings: list[str] = []
    if process_uuid and process_uuid not in processes:
        issues.append(f"task processUuid is not present in processes: {process_uuid}")
    if completion == "run_integration" and not integration_uuid:
        issues.append("completionCriteria is run_integration but integrationSettings.integrationUuid is empty")
    if integration_uuid and integration_uuid not in integrations:
        issues.append(f"integrationUuid is not present in integrations: {integration_uuid}")
    for uuid in model_uuid:
        if models and uuid not in models:
            issues.append(f"model UUID is not present in models: {uuid}")
    for uuid in dataset_uuids:
        if datasets and uuid not in datasets:
            issues.append(f"dataset UUID is not present in datasets: {uuid}")
        if not datasets:
            warnings.append(f"dataset UUID is unvalidated because snapshot has no dataset registry: {uuid}")
    if completion in RUN_LIKE_CRITERIA or integration_uuid:
        warnings.append("task can mutate data or UI when executed; do not start/complete without explicit approval")

    return {
        "uuid": task_uuid,
        "name": name,
        "processUuid": process_uuid,
        "process": processes.get(process_uuid or "", "UNKNOWN" if process_uuid else "-"),
        "completionCriteria": completion or "-",
        "integrationUuid": integration_uuid or "",
        "integration": integrations.get(integration_uuid or "", "UNKNOWN" if integration_uuid else "-"),
        "modelUuids": model_uuid,
        "datasetUuids": dataset_uuids,
        "next": f"{next_type or '-'}:{next_uuid or '-'}",
        "issues": issues,
        "warnings": warnings,
    }


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    header = rows[0]
    out.append("| " + " | ".join(header[i].ljust(widths[i]) for i in range(len(header))) + " |")
    out.append("| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |")
    for row in rows[1:]:
        out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(row))) + " |")
    return "\n".join(out)


def generate_report(snapshot: dict[str, Any], snapshot_path: Path) -> str:
    processes = named_index(snapshot, "processes")
    integrations = named_index(snapshot, "integrations")
    models = named_index(snapshot, "models")
    datasets = collect_datasets(snapshot)
    process_records = section_records(snapshot, "processes")
    task_records = section_records(snapshot, "tasks")
    tasks = [
        task_summary(task, processes=processes, integrations=integrations, models=models, datasets=datasets)
        for task in task_records
    ]

    issue_count = sum(len(task["issues"]) for task in tasks)
    warning_count = sum(len(task["warnings"]) for task in tasks)
    run_integration_count = sum(1 for task in tasks if task["completionCriteria"] == "run_integration")
    enabled_count = sum(1 for p in process_records if p.get("enabled") is True)

    lines: list[str] = []
    lines.append("# KS BPMS Read-Only Audit")
    lines.append("")
    lines.append(f"Snapshot: `{snapshot_path}`")
    lines.append(f"Project UUID: `{snapshot.get('projectUuid', '-')}`")
    lines.append(f"Snapshot created: `{snapshot.get('createdAt', '-')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Processes: {len(process_records)} ({enabled_count} enabled)")
    lines.append(f"- Tasks: {len(task_records)}")
    lines.append(f"- Run-integration tasks: {run_integration_count}")
    lines.append(f"- Reference issues: {issue_count}")
    lines.append(f"- Safety warnings: {warning_count}")
    lines.append(f"- Integration registry: {len(integrations)}")
    lines.append(f"- Model registry: {len(models)}")
    lines.append(f"- Dataset registry: {len(datasets)}")
    lines.append("")
    lines.append("## Processes")
    lines.append("")
    if process_records:
        rows = [["Name", "UUID", "Enabled", "Model", "Diagram"]]
        for process in process_records:
            uuid = get_id(process) or ""
            model_uuid = value_ci(process, "modelUuid", "ModelUUID")
            diagram_uuid = value_ci(process, "diagramUuid", "DiagramUUID")
            rows.append([
                get_name(process) or "<unnamed>",
                uuid,
                str(process.get("enabled", "-")),
                resolve(model_uuid, models) if isinstance(model_uuid, str) and model_uuid != ZERO_UUID else "-",
                diagram_uuid if isinstance(diagram_uuid, str) and diagram_uuid != ZERO_UUID else "-",
            ])
        lines.append(markdown_table(rows))
    else:
        lines.append("No processes found in snapshot.")
    lines.append("")
    lines.append("## Tasks")
    lines.append("")
    if tasks:
        rows = [["Task", "Process", "Completion", "Integration", "Model UUIDs", "Dataset UUIDs", "Next"]]
        for task in tasks:
            model_text = ", ".join(resolve(uuid, models) for uuid in task["modelUuids"]) or "-"
            if datasets:
                dataset_text = ", ".join(resolve(uuid, datasets) for uuid in task["datasetUuids"]) or "-"
            else:
                dataset_text = ", ".join(f"unvalidated (`{uuid}`)" for uuid in task["datasetUuids"]) or "-"
            rows.append([
                f"{task['name']} (`{task['uuid']}`)",
                f"{task['process']} (`{task['processUuid'] or '-'}`)",
                task["completionCriteria"],
                resolve(task["integrationUuid"], integrations),
                model_text,
                dataset_text,
                task["next"],
            ])
        lines.append(markdown_table(rows))
    else:
        lines.append("No tasks found in snapshot.")
    lines.append("")

    findings = []
    for task in tasks:
        for issue in task["issues"]:
            findings.append(("Issue", task["name"], issue))
        for warning in task["warnings"]:
            findings.append(("Warning", task["name"], warning))
    lines.append("## Findings")
    lines.append("")
    if findings:
        for kind, task_name, message in findings:
            lines.append(f"- {kind}: `{task_name}` - {message}")
    else:
        lines.append("No broken BPMS references or run-safety warnings found.")
    lines.append("")
    lines.append("## Safe-Work Notes")
    lines.append("")
    lines.append("- This report is generated offline from a snapshot and does not prove that a process is safe to run.")
    lines.append("- Do not start processes, complete tasks, clear history, create/sync diagrams, or run integration tasks without explicit approval.")
    lines.append("- For `run_integration`, verify source, target model/dataset, field mappings, output sampling conditions, and expected writes before any run.")
    lines.append("- Dataset references can remain unvalidated when the snapshot has no dataset registry; read model/dataset details before editing tasks.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline/read-only BPMS audit for a KS project snapshot")
    parser.add_argument("snapshot", type=Path, help="Path to snapshot.json")
    parser.add_argument("--output", type=Path, help="Write markdown report to this path")
    args = parser.parse_args()

    snapshot = load_json(args.snapshot)
    report = generate_report(snapshot, args.snapshot)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
