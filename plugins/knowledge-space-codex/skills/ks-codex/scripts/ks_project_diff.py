#!/usr/bin/env python3
"""Compare two KS read-only project snapshots.

The report is intentionally conservative: it highlights structural gaps and UI
risks, but it does not call KS and does not generate write payloads.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


NAMED_SECTIONS = (
    "models",
    "classes",
    "indicators",
    "dictionaries",
    "dataTables",
    "dashboards",
    "publications",
    "integrations",
    "integrationTables",
    "processes",
    "tasks",
)


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


def named_counter(snapshot: dict[str, Any], section: str) -> Counter[str]:
    return Counter(get_name(item) or "<unnamed>" for item in section_items(snapshot, section))


def named_ids(snapshot: dict[str, Any], section: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for item in section_items(snapshot, section):
        out[get_name(item) or "<unnamed>"].append(get_id(item) or "")
    return dict(out)


def known_uuid_sets(snapshot: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for section in NAMED_SECTIONS:
        out[section] = {uuid for ids in named_ids(snapshot, section).values() for uuid in ids if uuid}
    return out


def get_dashboard(detail: Any) -> dict[str, Any]:
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


def dashboard_details(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    details = snapshot.get("sections", {}).get("dashboards", {}).get("details", {})
    out = []
    if isinstance(details, dict):
        for detail in details.values():
            dashboard = get_dashboard(detail)
            if dashboard:
                out.append(dashboard)
    return out


def dashboard_by_name(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for dashboard in dashboard_details(snapshot):
        out[get_name(dashboard) or get_id(dashboard) or "<unnamed>"] = dashboard
    return out


def cells(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    config = dashboard.get("configuration")
    if isinstance(config, dict) and isinstance(config.get("cells"), list):
        return [cell for cell in config["cells"] if isinstance(cell, dict)]
    if isinstance(dashboard.get("cells"), list):
        return [cell for cell in dashboard["cells"] if isinstance(cell, dict)]
    return []


def value_at_path(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            return None
        return result if math.isfinite(result) else None
    return None


def cell_rect(cell: dict[str, Any]) -> tuple[float, float, float, float] | None:
    size = value_at_path(cell, ("settings", "sizeAndContent"))
    if not isinstance(size, dict):
        return None
    left = number(value_at_path(size, ("left", "value")))
    top = number(value_at_path(size, ("top", "value")))
    width = number(value_at_path(size, ("width", "value")))
    height = number(value_at_path(size, ("height", "value")))
    if left is None or top is None or width is None or height is None:
        return None
    return left, top, width, height


def entity_type(cell: dict[str, Any]) -> str:
    entity = cell.get("entity")
    if isinstance(entity, dict):
        value = entity.get("type")
        if isinstance(value, str) and value:
            return value
    return "<blank>"


def cell_title(cell: dict[str, Any]) -> str:
    name_value = value_at_path(cell, ("settings", "name", "value"))
    if isinstance(name_value, str) and name_value:
        return name_value
    entity_name = value_at_path(cell, ("entity", "value", "name"))
    if isinstance(entity_name, str) and entity_name:
        return entity_name
    return get_id(cell) or "<cell>"


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def walk_uuid_refs(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    refs: list[tuple[tuple[str, ...], str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            refs.extend(walk_uuid_refs(item, (*path, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            refs.extend(walk_uuid_refs(item, (*path, str(index))))
    elif isinstance(value, str) and UUID_RE.match(value):
        refs.append((path, value))
    return refs


def likely_target_for_path(path: tuple[str, ...], cell_type: str) -> str | None:
    path_text = ".".join(path).lower()
    if "tabletable" in path_text:
        return "dataTables"
    if "tablemodel" in path_text or "ganttmodel" in path_text:
        return "models"
    if "dashboard" in path_text and path[-1].lower() in {"uuid", "value"}:
        return "dashboards"
    if cell_type == "dashboard" and path_text.endswith("entity.value.uuid"):
        return "dashboards"
    if cell_type == "table" and path_text.endswith("entity.value.uuid"):
        return "dataTables"
    if cell_type == "gantt" and path_text.endswith("entity.value.uuid"):
        return "gantts"
    return None


def dashboard_audit(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    known = known_uuid_sets(snapshot)
    known["all"] = set().union(*(values for values in known.values())) if known else set()
    out = {}
    for dashboard in dashboard_details(snapshot):
        dashboard_name = get_name(dashboard) or get_id(dashboard) or "<unnamed>"
        dashboard_cells = cells(dashboard)
        type_counts = Counter(entity_type(cell) for cell in dashboard_cells)
        risks: list[str] = []
        rects: list[tuple[str, tuple[float, float, float, float]]] = []
        for cell in dashboard_cells:
            title = cell_title(cell)
            rect = cell_rect(cell)
            if rect is None:
                risks.append(f"cell `{title}` has no complete settings.sizeAndContent")
            else:
                _, _, width, height = rect
                if width <= 0 or height <= 0:
                    risks.append(f"cell `{title}` has non-positive size {width:g}x{height:g}")
                rects.append((title, rect))

            ctype = entity_type(cell)
            if ctype == "<blank>":
                risks.append(f"cell `{title}` has no entity.type")
            for path, uuid in walk_uuid_refs(cell.get("entity", {})):
                target = likely_target_for_path(path, ctype)
                if target == "gantts":
                    continue
                if target and uuid not in known.get(target, set()):
                    risks.append(
                        f"cell `{title}` references missing {target} uuid `{uuid}` at `{'.'.join(path)}`"
                    )

        for index, (title_a, rect_a) in enumerate(rects):
            for title_b, rect_b in rects[index + 1 :]:
                if overlap(rect_a, rect_b):
                    risks.append(f"cells may overlap: `{title_a}` and `{title_b}`")

        out[dashboard_name] = {
            "uuid": get_id(dashboard),
            "cell_count": len(dashboard_cells),
            "entity_types": dict(type_counts),
            "risks": sorted(set(risks)),
        }
    return out


def data_table_details(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = named_ids(snapshot, "dataTables")
    uuid_to_name = {uuid: name for name, ids in items.items() for uuid in ids}
    details = snapshot.get("sections", {}).get("dataTables", {}).get("details", {})
    out = {}
    if not isinstance(details, dict):
        return out
    for uuid, detail in details.items():
        if not isinstance(detail, dict):
            continue
        name = get_name(detail) or uuid_to_name.get(uuid) or uuid
        rows = detail.get("rows")
        columns = detail.get("columns")
        filters = detail.get("filters")
        out[name] = {
            "uuid": uuid,
            "rows": len(rows) if isinstance(rows, list) else None,
            "columns": len(columns) if isinstance(columns, list) else None,
            "filters": len(filters) if isinstance(filters, list) else None,
            "isReadOnly": detail.get("isReadOnly"),
            "type": detail.get("type"),
        }
    return out


def publication_details(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dashboard_ids = known_uuid_sets(snapshot).get("dashboards", set())
    details = snapshot.get("sections", {}).get("publications", {}).get("details", {})
    out = {}
    if not isinstance(details, dict):
        return out
    for detail in details.values():
        publications = detail.get("publications") if isinstance(detail, dict) else None
        if not isinstance(publications, list):
            continue
        for publication in publications:
            if not isinstance(publication, dict):
                continue
            tree = publication.get("innerTree") if isinstance(publication.get("innerTree"), list) else []
            missing_refs = []
            visible = []
            hidden = []
            for node in tree:
                if not isinstance(node, dict) or node.get("type") != "dashboard":
                    continue
                name = get_name(node) or get_id(node) or "<node>"
                if node.get("isHidden"):
                    hidden.append(name)
                else:
                    visible.append(name)
                ref = node.get("referenceUuid")
                if isinstance(ref, str) and ref and ref not in dashboard_ids:
                    missing_refs.append(f"{name}: {ref}")
            out[get_name(publication) or get_id(publication) or "<publication>"] = {
                "uuid": get_id(publication),
                "isActive": publication.get("isActive"),
                "accessType": publication.get("accessType"),
                "innerTree": len(tree),
                "visibleDashboards": visible,
                "hiddenDashboards": hidden,
                "missingDashboardRefs": missing_refs,
            }
    return out


def integration_detail_counts(snapshot: dict[str, Any]) -> dict[str, dict[str, int]]:
    ids = named_ids(snapshot, "integrations")
    uuid_to_name = {uuid: name for name, uuid_list in ids.items() for uuid in uuid_list}
    section = snapshot.get("sections", {}).get("integrations", {})
    out: dict[str, dict[str, int]] = {}
    for key in ("operations", "fieldRules", "outputSamplingConditions", "variables"):
        data = section.get(key, {})
        if not isinstance(data, dict):
            continue
        for uuid, detail in data.items():
            name = uuid_to_name.get(uuid, uuid)
            out.setdefault(name, {})
            if isinstance(detail, dict):
                if isinstance(detail.get(key), list):
                    out[name][key] = len(detail[key])
                elif isinstance(detail.get("data"), list):
                    out[name][key] = len(detail["data"])
                elif isinstance(detail.get("operations"), list):
                    out[name][key] = len(detail["operations"])
                else:
                    out[name][key] = len(detail)
            else:
                out[name][key] = 0
    return out


def counter_missing(reference: Counter[str], candidate: Counter[str]) -> list[str]:
    missing = []
    for name, count in sorted(reference.items()):
        diff = count - candidate.get(name, 0)
        if diff > 0:
            missing.append(f"{name}" if diff == 1 else f"{name} x{diff}")
    return missing


def counter_extra(reference: Counter[str], candidate: Counter[str]) -> list[str]:
    return counter_missing(candidate, reference)


def format_list(values: list[str], limit: int = 20) -> str:
    if not values:
        return "none"
    clipped = values[:limit]
    suffix = "" if len(values) <= limit else f"; ... {len(values) - limit} more"
    return "; ".join(clipped) + suffix


def section_diff(reference: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for section in NAMED_SECTIONS:
        ref_counter = named_counter(reference, section)
        cand_counter = named_counter(candidate, section)
        rows.append(
            {
                "section": section,
                "reference": sum(ref_counter.values()),
                "candidate": sum(cand_counter.values()),
                "missing": counter_missing(ref_counter, cand_counter),
                "extra": counter_extra(ref_counter, cand_counter),
            }
        )
    ref_objects = reference.get("sections", {}).get("objects", {}).get("count", 0)
    cand_objects = candidate.get("sections", {}).get("objects", {}).get("count", 0)
    rows.append(
        {
            "section": "objects",
            "reference": ref_objects,
            "candidate": cand_objects,
            "missing": [],
            "extra": [],
        }
    )
    return rows


def render_report(reference: dict[str, Any], candidate: dict[str, Any], title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"- referenceProjectUuid: `{reference.get('projectUuid')}`",
        f"- candidateProjectUuid: `{candidate.get('projectUuid')}`",
        f"- referenceCreatedAt: `{reference.get('createdAt')}`",
        f"- candidateCreatedAt: `{candidate.get('createdAt')}`",
        f"- referenceSnapshotErrors: `{len(reference.get('errors', []))}`",
        f"- candidateSnapshotErrors: `{len(candidate.get('errors', []))}`",
        "",
    ]

    rows = section_diff(reference, candidate)
    blockers = []
    for row in rows:
        if row["missing"] and row["section"] in {"classes", "indicators", "dataTables", "dashboards", "integrations", "processes", "tasks"}:
            blockers.append(f"{row['section']}: missing {format_list(row['missing'], 8)}")
    ref_objects = reference.get("sections", {}).get("objects", {}).get("count", 0)
    cand_objects = candidate.get("sections", {}).get("objects", {}).get("count", 0)
    if ref_objects and cand_objects < ref_objects:
        blockers.append(f"objects: candidate has {cand_objects}, reference has {ref_objects}")

    candidate_dashboards = dashboard_audit(candidate)
    ui_risks = sum(len(item["risks"]) for item in candidate_dashboards.values())
    if ui_risks:
        blockers.append(f"dashboard UI risks: {ui_risks}")
    structural_blockers = any(
        row["missing"] and row["section"] in {"classes", "indicators", "dataTables", "dashboards", "integrations", "processes", "tasks"}
        for row in rows
    ) or (bool(ref_objects) and cand_objects < ref_objects)

    lines.append("## Summary")
    if blockers:
        for item in blockers[:30]:
            lines.append(f"- {item}")
    else:
        lines.append("- No high-level structural blockers found by this offline diff.")
    lines.append("")

    lines.append("## Section Counts")
    lines.append("| Section | Reference | Candidate | Missing Names | Extra Names |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    for row in rows:
        lines.append(
            f"| {row['section']} | {row['reference']} | {row['candidate']} | "
            f"{format_list(row['missing'], 10)} | {format_list(row['extra'], 10)} |"
        )
    lines.append("")

    lines.append("## Data Tables")
    ref_tables = data_table_details(reference)
    cand_tables = data_table_details(candidate)
    shared_tables = sorted(set(ref_tables) & set(cand_tables))
    if not shared_tables and not ref_tables and not cand_tables:
        lines.append("- No data table details in either snapshot.")
    else:
        lines.append("| Table | Reference rows/cols | Candidate rows/cols | Notes |")
        lines.append("| --- | ---: | ---: | --- |")
        for name in shared_tables[:80]:
            ref = ref_tables[name]
            cand = cand_tables[name]
            notes = []
            if ref.get("rows") != cand.get("rows"):
                notes.append("row count differs")
            if ref.get("columns") != cand.get("columns"):
                notes.append("column count differs")
            if cand.get("rows") == 0 and cand.get("columns") == 0:
                notes.append("candidate table shape is empty")
            lines.append(
                f"| {name} | {ref.get('rows')}/{ref.get('columns')} | "
                f"{cand.get('rows')}/{cand.get('columns')} | {format_list(notes, 5)} |"
            )
        missing_tables = sorted(set(ref_tables) - set(cand_tables))
        extra_tables = sorted(set(cand_tables) - set(ref_tables))
        if missing_tables:
            lines.append(f"- Missing table details: {format_list(missing_tables)}")
        if extra_tables:
            lines.append(f"- Extra table details: {format_list(extra_tables)}")
    lines.append("")

    lines.append("## Dashboards")
    ref_dashboards = dashboard_audit(reference)
    cand_dashboards = candidate_dashboards
    shared_dashboards = sorted(set(ref_dashboards) & set(cand_dashboards))
    if shared_dashboards:
        lines.append("| Dashboard | Reference cells/types | Candidate cells/types | Candidate risks |")
        lines.append("| --- | --- | --- | --- |")
        for name in shared_dashboards[:80]:
            ref = ref_dashboards[name]
            cand = cand_dashboards[name]
            lines.append(
                f"| {name} | {ref['cell_count']} {ref['entity_types']} | "
                f"{cand['cell_count']} {cand['entity_types']} | {format_list(cand['risks'], 6)} |"
            )
    missing_dashboards = sorted(set(ref_dashboards) - set(cand_dashboards))
    extra_dashboards = sorted(set(cand_dashboards) - set(ref_dashboards))
    if missing_dashboards:
        lines.append(f"- Missing dashboard details: {format_list(missing_dashboards)}")
    if extra_dashboards:
        lines.append(f"- Extra dashboard details: {format_list(extra_dashboards)}")
    for name in extra_dashboards[:30]:
        risks = cand_dashboards[name]["risks"]
        if risks:
            lines.append(f"- Extra dashboard `{name}` risks: {format_list(risks, 8)}")
    lines.append("")

    lines.append("## Publications")
    ref_pubs = publication_details(reference)
    cand_pubs = publication_details(candidate)
    if ref_pubs or cand_pubs:
        lines.append("| Publication | Reference visible/hidden | Candidate visible/hidden | Candidate node diff | Candidate missing refs |")
        lines.append("| --- | --- | --- | --- | --- |")
        for name in sorted(set(ref_pubs) | set(cand_pubs))[:80]:
            ref = ref_pubs.get(name, {})
            cand = cand_pubs.get(name, {})
            ref_nodes = set(ref.get("visibleDashboards", []) + ref.get("hiddenDashboards", [])) if ref else set()
            cand_nodes = set(cand.get("visibleDashboards", []) + cand.get("hiddenDashboards", [])) if cand else set()
            ref_v = (
                f"{len(ref.get('visibleDashboards', []))}/{len(ref.get('hiddenDashboards', []))}: "
                f"{format_list(ref.get('visibleDashboards', []) + ref.get('hiddenDashboards', []), 5)}"
                if ref
                else "missing"
            )
            cand_v = (
                f"{len(cand.get('visibleDashboards', []))}/{len(cand.get('hiddenDashboards', []))}: "
                f"{format_list(cand.get('visibleDashboards', []) + cand.get('hiddenDashboards', []), 5)}"
                if cand
                else "missing"
            )
            node_diff = []
            missing_nodes = sorted(ref_nodes - cand_nodes)
            extra_nodes = sorted(cand_nodes - ref_nodes)
            if missing_nodes:
                node_diff.append(f"missing: {format_list(missing_nodes, 5)}")
            if extra_nodes:
                node_diff.append(f"extra: {format_list(extra_nodes, 5)}")
            lines.append(
                f"| {name} | {ref_v} | {cand_v} | {format_list(node_diff, 4)} | "
                f"{format_list(cand.get('missingDashboardRefs', []), 8)} |"
            )
    else:
        lines.append("- No publication details in either snapshot.")
    lines.append("")

    lines.append("## Integrations")
    ref_integrations = integration_detail_counts(reference)
    cand_integrations = integration_detail_counts(candidate)
    if ref_integrations or cand_integrations:
        lines.append("| Integration | Reference details | Candidate details |")
        lines.append("| --- | --- | --- |")
        for name in sorted(set(ref_integrations) | set(cand_integrations))[:80]:
            lines.append(f"| {name} | {ref_integrations.get(name, {})} | {cand_integrations.get(name, {})} |")
    else:
        lines.append("- No integration details in either snapshot.")
    lines.append("")

    lines.append("## Recommended Next Actions")
    if structural_blockers:
        lines.append("- Resolve missing structural sections before fine UI polishing.")
    if ui_risks:
        lines.append("- Inspect dashboard risks in browser or with a focused cell-layout patch plan before writing changes.")
    if not structural_blockers and not ui_risks:
        lines.append("- Use the diff as a baseline and move to targeted task verification.")
    lines.append("- Treat this report as offline evidence only; any KS write still needs a targeted preflight and project UUID check.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--title", default="KS Project Diff")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    reference = load_json(args.reference)
    candidate = load_json(args.candidate)
    report = render_report(reference, candidate, args.title)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
