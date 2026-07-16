#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def items_by_uuid(snapshot: dict, section: str) -> dict[str, dict]:
    return {
        item["uuid"]: item
        for item in snapshot.get("sections", {}).get(section, {}).get("items", [])
        if isinstance(item, dict) and item.get("uuid")
    }


def summarize(snapshot: dict) -> dict[str, dict]:
    integrations = items_by_uuid(snapshot, "integrations")
    field_rules_root = snapshot.get("sections", {}).get("integrations", {}).get("fieldRules", {})
    ops_root = snapshot.get("sections", {}).get("integrations", {}).get("operations", {})
    output_conditions_root = snapshot.get("sections", {}).get("integrations", {}).get(
        "outputSamplingConditions", {}
    )

    out: dict[str, dict] = {}
    for integration_uuid, integration in integrations.items():
        operations = ops_root.get(integration_uuid, {}).get("operations", [])
        operation_uuids = {op.get("uuid") for op in operations if isinstance(op, dict)}
        raw_rules = field_rules_root.get(integration_uuid, {}).get("fieldsRules", [])
        rules = [
            rule
            for rule in raw_rules
            if isinstance(rule, dict) and rule.get("operationUuid") in operation_uuids
        ]
        output_conditions = output_conditions_root.get(integration_uuid, {})
        conditions = output_conditions.get("outputSamplingConditions")
        if conditions is None:
            conditions = output_conditions.get("samplingConditions")
        if not isinstance(conditions, list):
            conditions = []
        conditions = [
            condition
            for condition in conditions
            if isinstance(condition, dict) and condition.get("operationUuid") in operation_uuids
        ]
        out[integration["name"]] = {
            "uuid": integration_uuid,
            "operation_count": len(operations),
            "routes": [op.get("routename") for op in operations if isinstance(op, dict)],
            "previous_link_count": sum(
                len(op.get("previousUuids") or []) for op in operations if isinstance(op, dict)
            ),
            "field_rule_count": len(rules),
            "rule_outputs": dict(Counter(rule.get("output", {}).get("type") for rule in rules)),
            "rule_id_count": sum(1 for rule in rules if rule.get("isId")),
            "rule_indicator_count": sum(1 for rule in rules if rule.get("isIndicator")),
            "rule_dimension_count": sum(1 for rule in rules if rule.get("isDimension")),
            "output_sampling_count": len(conditions),
            "custom_query_count": sum(
                1
                for op in operations
                if isinstance(op, dict) and isinstance(op.get("customQuery"), list) and op["customQuery"]
            ),
            "disabled_operation_count": sum(
                1 for op in operations if isinstance(op, dict) and op.get("disabled")
            ),
        }
    return out


def process_summary(snapshot: dict) -> list[dict]:
    tasks = snapshot.get("sections", {}).get("tasks", {}).get("raw", {}).get("data", [])
    processes = snapshot.get("sections", {}).get("processes", {}).get("raw", {}).get("data", [])
    processes_by_uuid = {p.get("uuid"): p for p in processes if isinstance(p, dict)}
    result = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        process = processes_by_uuid.get(task.get("processUuid"), {})
        result.append(
            {
                "process": process.get("name"),
                "process_enabled": process.get("enabled"),
                "task": task.get("name"),
                "completion": task.get("completionCriteria"),
                "integration": task.get("integrationSettings", {}).get("integrationUuid"),
                "datasets": task.get("integrationSettings", {}).get("datasetUuids", {}).get("paramValue"),
            }
        )
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: ks_integration_audit.py TEMPLATE_SNAPSHOT SCRATCH_SNAPSHOT", file=sys.stderr)
        return 2

    template = load(sys.argv[1])
    scratch = load(sys.argv[2])
    template_summary = summarize(template)
    scratch_summary = summarize(scratch)

    print("# Integration course read-only audit")
    print()
    print("## Integration topology by name")
    for name in sorted(set(template_summary) | set(scratch_summary), key=str.casefold):
        t = template_summary.get(name)
        s = scratch_summary.get(name)
        print(f"- {name}")
        print(f"  - template: {t}")
        print(f"  - scratch:  {s}")
    print()
    print("## BPMS")
    print(f"- template: {process_summary(template)}")
    print(f"- scratch:  {process_summary(scratch)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
