#!/usr/bin/env python3
"""Create a dry-run publication inner-node patch plan from a KS snapshot.

This tool does not call KS. It only prepares candidate payloads for review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def item_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("Name") or "")


def item_uuid(item: dict[str, Any]) -> str:
    return str(item.get("uuid") or item.get("UUID") or item.get("referenceUuid") or item.get("ReferenceUUID") or "")


def dashboards_by_name(snapshot: dict[str, Any]) -> dict[str, str]:
    out = {}
    for item in snapshot.get("sections", {}).get("dashboards", {}).get("items", []):
        if isinstance(item, dict) and item_name(item) and item_uuid(item):
            out[item_name(item)] = item_uuid(item)
    return out


def publication_by_name(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    details = snapshot.get("sections", {}).get("publications", {}).get("details", {})
    if not isinstance(details, dict):
        return {}
    for detail in details.values():
        publications = detail.get("publications") if isinstance(detail, dict) else None
        if not isinstance(publications, list):
            continue
        for publication in publications:
            if isinstance(publication, dict) and item_name(publication) == name:
                return publication
    return {}


def node_by_name(publication: dict[str, Any]) -> dict[str, Any]:
    tree = publication.get("innerTree")
    if not isinstance(tree, list):
        return {}
    return {item_name(node): node for node in tree if isinstance(node, dict) and item_name(node)}


def render_plan(snapshot: dict[str, Any], publication_name: str, parent_name: str, after_name: str, visible: list[str], hidden: list[str]) -> str:
    publication = publication_by_name(snapshot, publication_name)
    dashboards = dashboards_by_name(snapshot)
    nodes = node_by_name(publication)
    lines = [
        f"# Publication Patch Dry Run: {publication_name}",
        "",
        "This is a dry-run plan only. Do not execute without explicit approval and read-back verification.",
        "",
    ]
    if not publication:
        lines.append(f"- ERROR: publication `{publication_name}` not found in snapshot.")
        return "\n".join(lines)
    publication_uuid = item_uuid(publication)
    parent_uuid = item_uuid(nodes.get(parent_name, {})) if parent_name else None
    previous_uuid = item_uuid(nodes.get(after_name, {})) if after_name else None
    lines.extend(
        [
            f"- publicationUuid: `{publication_uuid}`",
            f"- parent: `{parent_name}` -> `{parent_uuid}`",
            f"- initial previous: `{after_name}` -> `{previous_uuid}`",
            "",
            "## Candidate Calls",
        ]
    )
    planned_previous_label = None
    for name, is_hidden in [(name, False) for name in visible] + [(name, True) for name in hidden]:
        if name in nodes:
            lines.append(f"- SKIP `{name}`: node already exists.")
            previous_uuid = item_uuid(nodes[name])
            planned_previous_label = None
            continue
        dashboard_uuid = dashboards.get(name)
        if not dashboard_uuid:
            lines.append(f"- ERROR `{name}`: dashboard not found in snapshot.")
            continue
        payload = {
            "publicationUuid": publication_uuid,
            "parentUuid": parent_uuid,
            "previousUuid": previous_uuid or (f"<new node uuid for {planned_previous_label}>" if planned_previous_label else None),
            "referenceUuid": dashboard_uuid,
            "type": "dashboard",
            "name": name,
            "customName": "",
            "isHidden": is_hidden,
            "iconUuid": None,
            "iconName": "",
        }
        lines.append("")
        lines.append(f"### POST /publications/create-inner-node - {name}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
        lines.append("```")
        previous_uuid = None
        planned_previous_label = name
    lines.extend(
        [
            "",
            "## Required Verification",
            "",
            "- Read `/publications/get-list`, then filter by the active `projectUuid`.",
            "- Read `/publications/get-by-ids` for the changed publication.",
            "- Confirm every new node exists with the expected `parentUuid`, `previousUuid`, `referenceUuid`, and `isHidden`.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--publication", required=True)
    parser.add_argument("--parent", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--visible", action="append", default=[])
    parser.add_argument("--hidden", action="append", default=[])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    snapshot = load_json(args.snapshot)
    report = render_plan(snapshot, args.publication, args.parent, args.after, args.visible, args.hidden)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
