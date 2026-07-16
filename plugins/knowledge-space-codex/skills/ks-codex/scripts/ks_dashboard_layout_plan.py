#!/usr/bin/env python3
"""Create an offline KS dashboard layout patch plan from a project snapshot.

The tool never calls KS. It is meant for tasks such as "align this dashboard
section to the left", "show what would move", and "prepare a safe patch plan".
It outputs a markdown report and, optionally, a JSON safe patch plan that can be
reviewed before any `/dashboards/update` call is made.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

DEFAULT_EXCLUDED_TYPES = {"<blank>", "dashboard"}


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
    if not isinstance(detail, dict):
        return {}
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


def dashboards(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    details = snapshot.get("sections", {}).get("dashboards", {}).get("details", {})
    if isinstance(details, dict) and details:
        return [dashboard for dashboard in (unwrap_dashboard(item) for item in details.values()) if dashboard]
    items = snapshot.get("sections", {}).get("dashboards", {}).get("items", [])
    return [item for item in items if isinstance(item, dict)]


def cells(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    config = dashboard.get("configuration")
    if isinstance(config, dict) and isinstance(config.get("cells"), list):
        return [cell for cell in config["cells"] if isinstance(cell, dict)]
    return []


def value_at(value: Any, path: tuple[str, ...]) -> Any:
    cur = value
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def rect(cell: dict[str, Any]) -> tuple[float, float, float, float] | None:
    size = value_at(cell, ("settings", "sizeAndContent"))
    if not isinstance(size, dict):
        return None
    left = number(value_at(size, ("left", "value")))
    top = number(value_at(size, ("top", "value")))
    width = number(value_at(size, ("width", "value")))
    height = number(value_at(size, ("height", "value")))
    if left is None or top is None or width is None or height is None:
        return None
    return left, top, width, height


def entity_type(cell: dict[str, Any]) -> str:
    value = value_at(cell, ("entity", "type"))
    return value if isinstance(value, str) and value else "<blank>"


def cell_title(cell: dict[str, Any]) -> str:
    for path in (("settings", "name", "value"), ("entity", "value", "name"), ("entity", "ganttModel", "name")):
        value = value_at(cell, path)
        if isinstance(value, str) and value:
            return value
    return get_id(cell) or "<cell>"


def is_hidden(cell: dict[str, Any]) -> bool:
    if value_at(cell, ("entity", "hide")) is True:
        return True
    if value_at(cell, ("settings", "hide")) is True:
        return True
    return False


def match_dashboard(dashboard: dict[str, Any], selector: str | None) -> bool:
    if not selector:
        return True
    uuid = get_id(dashboard) or ""
    name = get_name(dashboard)
    return selector == uuid or selector.casefold() in name.casefold()


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return aw > 0 and ah > 0 and bw > 0 and bh > 0 and ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    out.append("| " + " | ".join(rows[0][i].ljust(widths[i]) for i in range(len(widths))) + " |")
    out.append("| " + " | ".join("-" * widths[i] for i in range(len(widths))) + " |")
    for row in rows[1:]:
        out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(widths))) + " |")
    return "\n".join(out)


def select_cells(
    dashboard: dict[str, Any],
    *,
    include_types: set[str] | None,
    exclude_types: set[str],
    top_min: float | None,
    top_max: float | None,
    min_width: float,
    min_height: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected = []
    skipped = []
    for cell in cells(dashboard):
        ctype = entity_type(cell)
        crect = rect(cell)
        title = cell_title(cell)
        if crect is None:
            skipped.append(f"{title}: missing sizeAndContent")
            continue
        left, top, width, height = crect
        if is_hidden(cell):
            skipped.append(f"{title}: hidden")
            continue
        if include_types and ctype not in include_types:
            skipped.append(f"{title}: type {ctype} not in include-types")
            continue
        if ctype in exclude_types:
            skipped.append(f"{title}: type {ctype} excluded")
            continue
        if width < min_width or height < min_height:
            skipped.append(f"{title}: too small/service-like ({width:g}x{height:g})")
            continue
        if top_min is not None and top < top_min:
            skipped.append(f"{title}: above top-min")
            continue
        if top_max is not None and top > top_max:
            skipped.append(f"{title}: below top-max")
            continue
        selected.append(cell)
    return selected, skipped


def build_report_and_plan(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    snapshot = load_json(args.snapshot)
    include_types = set(args.include_type or []) or None
    exclude_types = set(DEFAULT_EXCLUDED_TYPES)
    if args.exclude_type:
        exclude_types.update(args.exclude_type)
    if args.include_nested_dashboards:
        exclude_types.discard("dashboard")

    reports: list[str] = ["# KS Dashboard Layout Plan", ""]
    operations: list[dict[str, Any]] = []
    project_uuid = snapshot.get("projectUuid") or "<project_uuid>"

    matched = [dashboard for dashboard in dashboards(snapshot) if match_dashboard(dashboard, args.dashboard)]
    if not matched:
        reports.append(f"No dashboard matched selector `{args.dashboard}`.")
    for dashboard in matched:
        dashboard_uuid = get_id(dashboard) or ""
        dashboard_name = get_name(dashboard) or dashboard_uuid or "<dashboard>"
        selected, skipped = select_cells(
            dashboard,
            include_types=include_types,
            exclude_types=exclude_types,
            top_min=args.top_min,
            top_max=args.top_max,
            min_width=args.min_width,
            min_height=args.min_height,
        )
        reports.append(f"## {dashboard_name}")
        reports.append("")
        reports.append(f"Dashboard UUID: `{dashboard_uuid}`")
        reports.append(f"Selected cells: {len(selected)}")
        reports.append(f"Skipped cells: {len(skipped)}")
        reports.append("")
        if not selected:
            reports.append("No cells selected for layout planning.")
            reports.append("")
            continue
        target_left = float(args.left) if args.left is not None else min(rect(cell)[0] for cell in selected if rect(cell))
        changes = []
        warnings = []
        rows = [["Cell", "Type", "UUID", "Before", "After", "Changed"]]
        planned_rects: list[tuple[str, tuple[float, float, float, float]]] = []
        for cell in selected:
            crect = rect(cell)
            if crect is None:
                continue
            left, top, width, height = crect
            new_left = target_left
            if new_left + width > 10000:
                warnings.append(f"{cell_title(cell)}: target left {new_left:g} would exceed right edge with width {width:g}; left unchanged")
                new_left = left
            changed = abs(new_left - left) > 0.0001
            before = {"left": left, "top": top, "width": width, "height": height}
            after = {"left": new_left, "top": top, "width": width, "height": height}
            planned_rects.append((cell_title(cell), (new_left, top, width, height)))
            if changed:
                changes.append({
                    "cellUuid": get_id(cell),
                    "cellTitle": cell_title(cell),
                    "entityType": entity_type(cell),
                    "before": before,
                    "after": after,
                    "fieldChanges": ["settings.sizeAndContent.left.value"],
                })
            rows.append([
                cell_title(cell),
                entity_type(cell),
                get_id(cell) or "",
                f"left={left:g}; top={top:g}; width={width:g}; height={height:g}",
                f"left={new_left:g}; top={top:g}; width={width:g}; height={height:g}",
                "yes" if changed else "no",
            ])
        for index, (a_name, a_rect) in enumerate(planned_rects):
            for b_name, b_rect in planned_rects[index + 1:]:
                if overlap(a_rect, b_rect):
                    warnings.append(f"planned selected-cell overlap: {a_name} <> {b_name}")
        reports.append(f"Operation: `{args.operation}`")
        reports.append(f"Target left: `{target_left:g}`")
        reports.append("")
        reports.append(markdown_table(rows))
        reports.append("")
        if warnings:
            reports.append("### Warnings")
            reports.append("")
            reports.extend(f"- {item}" for item in warnings)
            reports.append("")
        if args.show_skipped and skipped:
            reports.append("### Skipped")
            reports.append("")
            reports.extend(f"- {item}" for item in skipped[:80])
            if len(skipped) > 80:
                reports.append(f"- ... {len(skipped) - 80} more")
            reports.append("")
        if changes:
            operations.append({
                "id": f"align-left-{dashboard_uuid or len(operations) + 1}",
                "endpoint": "/dashboards/update",
                "method": "POST",
                "risk": "project_write",
                "entityType": "dashboard",
                "entityUuid": dashboard_uuid,
                "entityName": dashboard_name,
                "summary": f"Align selected visible dashboard cells to left={target_left:g}; change only sizeAndContent.left.value",
                "readBefore": {"endpoint": "/dashboards/get-by-id", "payload": {"UUID": dashboard_uuid}},
                "changes": changes,
                "payloadBuildHint": "Read full dashboard, update only listed cells' settings.sizeAndContent.left.value, then send raw dashboard object to /dashboards/update.",
                "readBack": {
                    "endpoint": "/dashboards/get-by-id",
                    "manualChecks": [
                        "listed cells have the planned left.value",
                        "top/width/height/events/entity refs are unchanged for listed cells",
                        "run ks_dashboard_cell_report.py and browser-check user-facing dashboard",
                    ],
                },
                "executionReady": False,
                "blockingReason": "Build and review a full dashboard payload, then add response-shape-specific machine checks before approval.",
                "rollback": "Restore dashboard JSON captured by readBefore.",
            })
    plan = {
        "metadata": {
            "task": "dashboard layout alignment dry-run",
            "targetProjectUuid": project_uuid,
            "mode": "dry_run",
            "sourceSnapshot": str(args.snapshot),
        },
        "approval": {"userApproved": False, "approvedOperationIds": [], "approvedEndpoints": []},
        "operations": operations,
    }
    if not operations:
        reports.append("No patch operations were generated.")
    return "\n".join(reports).rstrip() + "\n", plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline KS dashboard layout patch planner")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--dashboard", help="Dashboard UUID or case-insensitive name substring")
    parser.add_argument("--operation", default="align-left", choices=["align-left"])
    parser.add_argument("--left", type=float, help="Explicit target left. Defaults to minimum selected left")
    parser.add_argument("--include-type", action="append", help="Only include these entity types; repeatable")
    parser.add_argument("--exclude-type", action="append", help="Exclude these entity types in addition to defaults; repeatable")
    parser.add_argument("--include-nested-dashboards", action="store_true", help="Include dashboard cells that are excluded by default")
    parser.add_argument("--top-min", type=float)
    parser.add_argument("--top-max", type=float)
    parser.add_argument("--min-width", type=float, default=100.0)
    parser.add_argument("--min-height", type=float, default=100.0)
    parser.add_argument("--show-skipped", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-output", type=Path)
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
