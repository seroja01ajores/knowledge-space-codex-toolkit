#!/usr/bin/env python3
"""Generate a dashboard cell-level report from a KS project snapshot.

The report is offline/read-only. It is meant to identify concrete cells before
layout or event changes are made through the KS API.
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
    value = item.get("l10n")
    if isinstance(value, dict):
        return str(value.get("name") or value.get("Name") or "")
    return ""


def get_dashboard(detail: Any) -> dict[str, Any]:
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


def dashboard_details(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    details = snapshot.get("sections", {}).get("dashboards", {}).get("details", {})
    if not isinstance(details, dict):
        return []
    return [dashboard for dashboard in (get_dashboard(detail) for detail in details.values()) if dashboard]


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


def rect_text(rect: tuple[float, float, float, float] | None) -> str:
    if rect is None:
        return "missing"
    return "left={:.2f}; top={:.2f}; width={:.2f}; height={:.2f}".format(*rect)


def entity_type(cell: dict[str, Any]) -> str:
    value = value_at_path(cell, ("entity", "type"))
    return value if isinstance(value, str) and value else "<blank>"


def cell_title(cell: dict[str, Any]) -> str:
    for path in (
        ("settings", "name", "value"),
        ("entity", "value", "name"),
        ("entity", "ganttModel", "name"),
    ):
        value = value_at_path(cell, path)
        if isinstance(value, str) and value:
            return value
    return get_id(cell) or "<cell>"


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def walk(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    out = [(path, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            out.extend(walk(item, (*path, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(walk(item, (*path, str(index))))
    return out


def relevant_refs(cell: dict[str, Any]) -> list[str]:
    refs = []
    for path, value in walk(cell.get("entity", {})):
        if not isinstance(value, str) or not UUID_RE.match(value):
            continue
        path_text = ".".join(path)
        lower = path_text.lower()
        if any(
            marker in lower
            for marker in (
                "tabletable",
                "tablemodel",
                "ganttmodel",
                "dashboard",
                "entity.value.uuid",
                "buttons",
                "icons",
                "widget",
            )
        ):
            refs.append(f"{path_text}={value}")
    return sorted(set(refs))


def event_summaries(cell: dict[str, Any]) -> list[str]:
    summaries = []
    entity = cell.get("entity", {})
    if isinstance(entity, dict):
        for setting_name, label_prefix in (
            ("clickEventSettings", "tableClick"),
            ("dblClickEventSettings", "tableDblClick"),
        ):
            settings = entity.get(setting_name)
            if not isinstance(settings, dict):
                continue
            event_types = settings.get("tableEventTypes")
            if not isinstance(event_types, list):
                continue
            tags = settings.get("tags")
            tag_suffix = f":{tags}" if isinstance(tags, str) and tags else ""
            for event_type in event_types:
                if isinstance(event_type, str) and event_type:
                    summaries.append(f"{label_prefix}:{event_type}{tag_suffix}")
    for path, value in walk(cell):
        if not isinstance(value, dict):
            continue
        event_type = value.get("type")
        if not isinstance(event_type, str) or not event_type:
            continue
        if "events" not in ".".join(path) and path[-1:] != ("events",):
            # Keep regular cell entity type out of the event list.
            if path[-1:] != ("0",) and "Elements" not in ".".join(path):
                continue
        action = value.get("action")
        label = event_type if not action else f"{event_type}:{action}"
        summaries.append(label)
    return sorted(Counter(summaries).elements())


def format_list(values: list[str], limit: int = 6) -> str:
    if not values:
        return "none"
    clipped = values[:limit]
    suffix = "" if len(values) <= limit else f"; ... {len(values) - limit} more"
    return "; ".join(clipped) + suffix


def dashboard_rows(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    rows = []
    overlaps_by_dashboard: dict[str, list[str]] = defaultdict(list)
    for dashboard in dashboard_details(snapshot):
        dashboard_name = get_name(dashboard) or get_id(dashboard) or "<dashboard>"
        dashboard_uuid = get_id(dashboard) or ""
        dashboard_cells = cells(dashboard)
        rects: list[tuple[str, tuple[float, float, float, float]]] = []
        for cell in dashboard_cells:
            rect = cell_rect(cell)
            title = cell_title(cell)
            ctype = entity_type(cell)
            risks = []
            if rect is None:
                risks.append("missing sizeAndContent")
            else:
                _, _, width, height = rect
                if width <= 0 or height <= 0:
                    risks.append("non-positive size")
                rects.append((title, rect))
            if ctype == "<blank>":
                risks.append("blank entity type")
            rows.append(
                {
                    "dashboard": dashboard_name,
                    "dashboard_uuid": dashboard_uuid,
                    "cell": title,
                    "cell_uuid": get_id(cell) or "",
                    "type": ctype,
                    "rect": rect_text(rect),
                    "zIndex": value_at_path(cell, ("settings", "cellStyle", "zIndex")),
                    "refs": relevant_refs(cell),
                    "events": event_summaries(cell),
                    "risks": risks,
                }
            )
        for index, (title_a, rect_a) in enumerate(rects):
            for title_b, rect_b in rects[index + 1 :]:
                if overlap(rect_a, rect_b):
                    overlaps_by_dashboard[dashboard_name].append(f"{title_a} <-> {title_b}")
    return rows, overlaps_by_dashboard


def render_markdown(snapshot: dict[str, Any]) -> str:
    rows, overlaps_by_dashboard = dashboard_rows(snapshot)
    lines = [
        "# Dashboard Cell Report",
        "",
        f"- projectUuid: `{snapshot.get('projectUuid')}`",
        f"- snapshotCreatedAt: `{snapshot.get('createdAt')}`",
        f"- dashboards: `{len({row['dashboard'] for row in rows})}`",
        f"- cells: `{len(rows)}`",
        "",
    ]
    by_dashboard: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_dashboard[row["dashboard"]].append(row)

    lines.append("## Dashboard Summary")
    lines.append("| Dashboard | Cells | Types | Overlaps |")
    lines.append("| --- | ---: | --- | --- |")
    for dashboard in sorted(by_dashboard):
        type_counts = Counter(row["type"] for row in by_dashboard[dashboard])
        lines.append(
            f"| {dashboard} | {len(by_dashboard[dashboard])} | {dict(type_counts)} | "
            f"{format_list(overlaps_by_dashboard.get(dashboard, []), 5)} |"
        )
    lines.append("")

    for dashboard in sorted(by_dashboard):
        lines.append(f"## {dashboard}")
        lines.append("")
        lines.append("| Cell | Type | Rect | zIndex | Refs | Events | Risks |")
        lines.append("| --- | --- | --- | ---: | --- | --- | --- |")
        for row in by_dashboard[dashboard]:
            lines.append(
                f"| {row['cell']} | {row['type']} | {row['rect']} | {row['zIndex']} | "
                f"{format_list(row['refs'], 4)} | {format_list(row['events'], 5)} | {format_list(row['risks'], 5)} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    snapshot = load_json(args.snapshot)
    report = render_markdown(snapshot)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)
    if args.json_out:
        rows, overlaps = dashboard_rows(snapshot)
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({"rows": rows, "overlaps": overlaps}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
