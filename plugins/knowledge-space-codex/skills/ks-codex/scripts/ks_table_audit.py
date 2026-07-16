#!/usr/bin/env python3
"""Audit KS data table constructor structure from a read-only project snapshot.

This tool is intentionally offline: it never calls KS. It helps diagnose table
blocks that render empty because constructor rows/columns/filters reference the
wrong class, indicator, dictionary, model, or unsupported relation path.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


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


def section_items(snapshot: dict[str, Any], section: str) -> list[dict[str, Any]]:
    items = snapshot.get("sections", {}).get(section, {}).get("items", [])
    return [item for item in items if isinstance(item, dict)]


def named_map(snapshot: dict[str, Any], section: str) -> dict[str, str]:
    out = {}
    for item in section_items(snapshot, section):
        uuid = get_id(item)
        if uuid:
            out[uuid] = get_name(item) or "<unnamed>"
    return out


def raw_named_map(snapshot: dict[str, Any], section: str) -> dict[str, str]:
    raw = snapshot.get("sections", {}).get(section, {}).get("raw", {}).get("data")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for uuid, item in raw.items():
            if isinstance(uuid, str) and UUID_RE.match(uuid) and isinstance(item, dict):
                out[uuid] = get_name(item) or "<unnamed>"
    elif isinstance(raw, list):
        for item in raw:
            uuid = get_id(item)
            if uuid:
                out[uuid] = get_name(item) or "<unnamed>"
    return out


def build_known(snapshot: dict[str, Any]) -> dict[str, dict[str, str]]:
    known = {
        "models": named_map(snapshot, "models") | raw_named_map(snapshot, "models"),
        "classes": named_map(snapshot, "classes") | raw_named_map(snapshot, "classes"),
        "indicators": named_map(snapshot, "indicators") | raw_named_map(snapshot, "indicators"),
        "dictionaries": named_map(snapshot, "dictionaries") | raw_named_map(snapshot, "dictionaries"),
        "dataTables": named_map(snapshot, "dataTables") | raw_named_map(snapshot, "dataTables"),
        "objects": named_map(snapshot, "objects") | raw_named_map(snapshot, "objects"),
    }
    return known


def data_table_details(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details = snapshot.get("sections", {}).get("dataTables", {}).get("details", {})
    return {k: v for k, v in details.items() if isinstance(k, str) and isinstance(v, dict)}


def constructor(table: dict[str, Any]) -> dict[str, Any]:
    data = table.get("data")
    if isinstance(data, dict):
        value = data.get("constructorData")
        if isinstance(value, dict):
            return value
    return {}


def iter_nodes(node: Any, axis: str, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    rows = []
    if path:
        rows.append({"axis": axis, "path": ".".join(path), "node": node})
    children = node.get("children")
    if isinstance(children, list):
        for index, child in enumerate(children):
            rows.extend(iter_nodes(child, axis, (*path, str(index))))
    return rows


def all_constructor_nodes(table: dict[str, Any]) -> list[dict[str, Any]]:
    cd = constructor(table)
    nodes = []
    for axis in ("rows", "columns", "filters"):
        nodes.extend(iter_nodes(cd.get(axis), axis))
    return nodes


def values_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def classify_node_ref(node: dict[str, Any], value: str) -> tuple[str | None, str]:
    field_type = node.get("fieldType")
    entity_type = node.get("entityType")
    if field_type == "indicators" or entity_type == "indicator":
        return "indicators", "indicator value"
    if field_type == "objects":
        return "objects", "object value"
    if field_type in {"classObjects", "relatedObjectsClass"} or entity_type == "object":
        return "classes", "class/object selector value"
    if field_type == "dictionaryTime":
        return None, "system time dimension"
    if field_type == "dictionary" or entity_type == "dictionary":
        data = node.get("data")
        if isinstance(data, dict) and data.get("dictionaryUuid") == value:
            return "dictionaries", "dictionaryUuid"
        return None, "dictionary element or time value"
    if field_type == "dataset" or entity_type == "dataset":
        return None, "dataset value; datasets may be absent from snapshot registry"
    return None, "unclassified node value"


def check_uuid(
    *,
    uuid: str,
    section: str | None,
    label: str,
    known: dict[str, dict[str, str]],
    risks: list[str],
    refs: list[str],
) -> None:
    if not UUID_RE.match(uuid) or uuid == ZERO_UUID:
        return
    if section is None:
        refs.append(f"{label}: {uuid} (unvalidated)")
        return
    if uuid in known.get(section, {}):
        refs.append(f"{label}: {known[section][uuid]} [{section}]")
        return
    if section == "classes" and label.startswith("class/object selector"):
        if uuid in known.get("objects", {}):
            refs.append(f"{label}: {known['objects'][uuid]} [objects]")
            return
        if not known.get("objects"):
            refs.append(f"{label}: {uuid} (unvalidated; object registry absent)")
            return
    if section == "objects" and not known.get("objects"):
        refs.append(f"{label}: {uuid} (unvalidated; object registry absent)")
        return
    risks.append(f"unknown {label}: {uuid} expected in {section}")


def collect_node_refs(
    node: dict[str, Any],
    known: dict[str, dict[str, str]],
    risks: list[str],
    refs: list[str],
) -> None:
    for value in values_list(node.get("value")):
        if isinstance(value, str) and UUID_RE.match(value):
            section, label = classify_node_ref(node, value)
            check_uuid(uuid=value, section=section, label=label, known=known, risks=risks, refs=refs)

    data = node.get("data")
    if not isinstance(data, dict):
        return
    direct_refs = (
        ("modelUuid", "models", "modelUuid"),
        ("classUuid", "classes", "classUuid"),
        ("indicatorUuid", "indicators", "indicatorUuid"),
        ("dictionaryUuid", "dictionaries", "dictionaryUuid"),
        ("datasetUuid", None, "datasetUuid"),
    )
    for key, section, label in direct_refs:
        value = data.get(key)
        if isinstance(value, str) and UUID_RE.match(value):
            if key == "dictionaryUuid" and node.get("fieldType") == "dictionaryTime":
                section = None
                label = "system time dimension"
            check_uuid(uuid=value, section=section, label=label, known=known, risks=risks, refs=refs)
    classes_path = data.get("classesPath")
    if isinstance(classes_path, list):
        for value in classes_path:
            if isinstance(value, str) and UUID_RE.match(value):
                check_uuid(
                    uuid=value,
                    section="classes",
                    label="classesPath",
                    known=known,
                    risks=risks,
                    refs=refs,
                )


def display_settings(table: dict[str, Any]) -> dict[str, Any]:
    cd = constructor(table)
    value = cd.get("displaySettings")
    return value if isinstance(value, dict) else {}


def audit_table(table: dict[str, Any], known: dict[str, dict[str, str]]) -> dict[str, Any]:
    name = get_name(table) or "<unnamed>"
    table_uuid = get_id(table) or ""
    risks: list[str] = []
    infos: list[str] = []
    refs: list[str] = []
    cd = constructor(table)
    if not cd:
        risks.append("missing data.constructorData")

    model_uuid = table.get("modelUuid")
    if isinstance(model_uuid, str) and UUID_RE.match(model_uuid):
        check_uuid(
            uuid=model_uuid,
            section="models",
            label="table.modelUuid",
            known=known,
            risks=risks,
            refs=refs,
        )
    else:
        risks.append("missing table.modelUuid")

    nodes = all_constructor_nodes(table)
    axis_counts = Counter(item["axis"] for item in nodes)
    type_counts = Counter(
        str(item["node"].get("fieldType") or item["node"].get("entityType") or "<unknown>")
        for item in nodes
    )
    for axis in ("rows", "columns"):
        if axis_counts[axis] == 0:
            risks.append(f"no constructor {axis}")
    for item in nodes:
        collect_node_refs(item["node"], known, risks, refs)

    ds = display_settings(table)
    if ds.get("showTable") is False:
        infos.append("displaySettings.showTable=false")
    if ds.get("skipEmpty") is True:
        infos.append("displaySettings.skipEmpty=true can hide empty rows/columns")
    if ds.get("showLeftHeader") is False:
        infos.append("displaySettings.showLeftHeader=false")
    if ds.get("showTopHeader") is False:
        infos.append("displaySettings.showTopHeader=false")

    return {
        "uuid": table_uuid,
        "name": name,
        "type": table.get("type"),
        "axis_counts": dict(axis_counts),
        "field_type_counts": dict(type_counts),
        "risks": sorted(set(risks)),
        "infos": sorted(set(infos)),
        "refs": sorted(set(refs)),
    }


def format_inline_dict(value: dict[str, Any]) -> str:
    if not value:
        return "none"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def format_list(values: list[str], limit: int = 8) -> str:
    if not values:
        return "none"
    clipped = values[:limit]
    suffix = "" if len(values) <= limit else f"; ... {len(values) - limit} more"
    return "; ".join(clipped) + suffix


def write_markdown(reports: list[dict[str, Any]]) -> str:
    risk_count = sum(1 for report in reports if report["risks"])
    lines = [
        "# KS Data Table Audit",
        "",
        f"- Tables checked: {len(reports)}",
        f"- Tables with risks: {risk_count}",
        "",
        "## Tables",
        "",
    ]
    for report in sorted(reports, key=lambda item: item["name"].casefold()):
        risk_label = "risk" if report["risks"] else "ok"
        lines.extend(
            [
                f"### {report['name']}",
                "",
                f"- UUID: `{report['uuid']}`",
                f"- Type: `{report['type']}`",
                f"- Constructor axes: {format_inline_dict(report['axis_counts'])}",
                f"- Field types: {format_inline_dict(report['field_type_counts'])}",
                f"- Status: `{risk_label}`",
                f"- Risks: {format_list(report['risks'])}",
                f"- Notes: {format_list(report['infos'])}",
                f"- External refs: {format_list(report['refs'])}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    snapshot = load_json(args.snapshot)
    known = build_known(snapshot)
    reports = [audit_table(table, known) for table in data_table_details(snapshot).values()]
    text = write_markdown(reports)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
