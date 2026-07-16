#!/usr/bin/env python3
"""Create a read-only KS project snapshot.

Environment:
  KS_BASE_URL       e.g. https://<host>/api
  KS_PROJECT_UUID
  KS_TOKEN           or KS_LOGIN + KS_PASSWORD

This tool intentionally avoids runtime/external actions:
  - no source connection checks;
  - no integration runs;
  - no integration-table refresh/update/export;
  - no BPMS process starts;
  - no writes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ks_api_client import KSAPIError, KSClient
from ks_safe_files import atomic_write_text, prepare_output_root
from ks_secret_safety import (
    is_sensitive_key,
    redact_text,
    semantic_secret_value_keys,
)

REDACT_SOURCE_KEYS = {
    "host",
    "login",
    "dbname",
    "productname",
    "database",
    "url",
    "uri",
}

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def lower_key(key: Any) -> str:
    return str(key).replace("_", "").replace("-", "").lower()


def should_redact_key(key: Any, source_context: bool = False) -> bool:
    lk = lower_key(key)
    if is_sensitive_key(key) or "connectionstring" in lk:
        return True
    if source_context and lk in REDACT_SOURCE_KEYS:
        return True
    return False


def sanitize(
    value: Any,
    source_context: bool = False,
    secret_values: Iterable[str] = (),
) -> Any:
    if isinstance(value, dict):
        next_source_context = source_context or any(
            lower_key(k) in {"source", "sources", "connectionparam", "connectionparams"}
            for k in value.keys()
        )
        semantic_keys = semantic_secret_value_keys(value)
        out: dict[str, Any] = {}
        for key, item in value.items():
            if should_redact_key(key, next_source_context) or key in semantic_keys:
                out[str(key)] = "<redacted>"
            else:
                out[str(key)] = sanitize(item, next_source_context, secret_values)
        return out
    if isinstance(value, list):
        return [sanitize(item, source_context, secret_values) for item in value]
    if isinstance(value, str):
        return redact_text(value, secret_values)
    return value


def compact(value: Any, limit: int = 5) -> Any:
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": sanitize(value[:limit]),
        }
    return sanitize(value)


def arr(body: Any) -> list[Any]:
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    data = body.get("data", body)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in (
            "items",
            "objects",
            "list",
            "models",
            "classes",
            "indicators",
            "dashboards",
            "publications",
            "integrations",
            "sources",
            "tasks",
            "processes",
            "integrationTables",
        ):
            if isinstance(data.get(key), list):
                return data[key]
        if all(isinstance(item, dict) for item in data.values()):
            out = []
            for key, item in data.items():
                if get_id(item):
                    out.append(item)
                else:
                    copied = dict(item)
                    copied["uuid"] = str(key)
                    out.append(copied)
            return out
    return []


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


def try_post(
    client: KSClient,
    path: str,
    payloads: list[dict[str, Any]] | None,
    call_paths: list[str],
) -> dict[str, Any]:
    """Try endpoint payload shapes while delegating transport to shared KSClient."""
    errors: list[str] = []
    for payload in payloads or [{}]:
        call_paths.append(path)
        try:
            return client.post(path, payload)
        except Exception as exc:  # noqa: BLE001 - optional endpoint gaps belong in the snapshot.
            detail = redact_text(
                str(exc),
                (client.password or "", client.token or ""),
            )
            errors.append(f"{type(exc).__name__}: {detail}")
    return {"_snapshot_error": errors}


def summarize_objects(objects: list[Any], include_samples: bool) -> dict[str, Any]:
    by_class = Counter()
    for item in objects:
        if isinstance(item, dict):
            by_class[item.get("classUuid") or item.get("ClassUUID") or "<unknown>"] += 1
    out: dict[str, Any] = {
        "count": len(objects),
        "byClassUuid": dict(by_class.most_common()),
    }
    if include_samples:
        out["sample"] = sanitize(objects[:20])
    return out


def summarize_named(items: list[Any]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "uuid": get_id(item),
                "name": get_name(item),
                "rawType": item.get("type") or item.get("Type"),
            }
        )
    return out


def keep_current_project_items(items: list[Any], project_uuid: str) -> list[Any]:
    """Keep endpoint items scoped to the active project.

    Some KS endpoints rely on headers, but `/publications/get-list` can still
    return publications from every project visible to the current user. Snapshot
    files must not mix entities from neighboring projects.
    """
    out = []
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        item_project_uuid = item.get("projectUuid") or item.get("ProjectUUID")
        if not item_project_uuid or item_project_uuid == project_uuid:
            out.append(item)
    return out


def collect_by_ids(
    client: KSClient,
    path: str,
    ids: list[str],
    payload_shapes: list[dict[str, Any]],
    limit: int | None,
    call_paths: list[str],
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    selected = ids[:limit] if limit else ids
    project_uuid = client.project_uuid
    if not project_uuid:
        raise KSAPIError("KS_PROJECT_UUID is required for project-scoped KS work")
    for uuid in selected:
        if not uuid:
            continue
        payloads = []
        for shape in payload_shapes:
            text = json.dumps(shape)
            text = text.replace("<uuid>", uuid).replace("<project_uuid>", project_uuid)
            payloads.append(json.loads(text))
        details[uuid] = sanitize(try_post(client, path, payloads, call_paths))
    return details


def write_text_atomic(path: Path, text: str) -> None:
    """Write one CLI-selected output atomically without following target symlinks."""
    output_root = prepare_output_root(path.parent)
    atomic_write_text(output_root, path.name, text)


def build_map(snapshot: dict[str, Any]) -> str:
    sections = snapshot.get("sections", {})
    lines = [
        f"# KS Project Map",
        "",
        f"- createdAt: `{snapshot.get('createdAt')}`",
        f"- projectUuid: `{snapshot.get('projectUuid')}`",
        "",
    ]

    def add_named(title: str, key: str) -> None:
        section = sections.get(key, {})
        items = section.get("items", [])
        lines.append(f"## {title} ({len(items)})")
        filtered_out = section.get("filteredOutOtherProjects")
        if filtered_out:
            lines.append(f"- filteredOutOtherProjects: `{filtered_out}`")
        for item in items[:80]:
            lines.append(f"- {item.get('name') or '<unnamed>'} `{item.get('uuid')}`")
        if len(items) > 80:
            lines.append(f"- ... {len(items) - 80} more")
        lines.append("")

    add_named("Models", "models")
    add_named("Classes", "classes")
    add_named("Indicators", "indicators")
    add_named("Dictionaries", "dictionaries")
    add_named("Data Tables", "dataTables")
    add_named("Dashboards", "dashboards")
    add_named("Publications", "publications")
    add_named("Integrations", "integrations")
    add_named("Integration Tables", "integrationTables")
    add_named("BPMS Processes", "processes")
    add_named("BPMS Tasks", "tasks")

    objects = sections.get("objects", {})
    if objects:
        lines.append(f"## Objects ({objects.get('count', 0)})")
        for class_uuid, count in list(objects.get("byClassUuid", {}).items())[:80]:
            lines.append(f"- class `{class_uuid}`: {count}")
        lines.append("")

    errors = snapshot.get("errors", [])
    lines.append(f"## Snapshot Errors ({len(errors)})")
    for error in errors[:80]:
        lines.append(f"- `{error.get('section')}` `{error.get('path')}`: {error.get('error')}")
    if len(errors) > 80:
        lines.append(f"- ... {len(errors) - 80} more")
    lines.append("")

    return "\n".join(lines)


def endpoint_error(section: str, path: str, body: Any) -> dict[str, str] | None:
    if isinstance(body, dict) and body.get("_snapshot_error"):
        return {"section": section, "path": path, "error": " | ".join(body["_snapshot_error"])}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="Snapshot JSON output path")
    parser.add_argument("--map-out", help="Optional Markdown project map output path")
    parser.add_argument("--include-object-samples", action="store_true", help="Include a small object sample")
    parser.add_argument("--details-limit", type=int, default=300, help="Max dashboard/table details to read")
    args = parser.parse_args()

    client = KSClient.from_env(require_project=True)
    used_configured_token = bool(client.token)
    client.login()
    project_uuid = client.project_uuid
    if not project_uuid:
        raise KSAPIError("KS_PROJECT_UUID is required for project-scoped KS work")
    call_paths = [] if used_configured_token else ["/auth/login"]

    snapshot: dict[str, Any] = {
        "schema": "ks_project_snapshot.v1",
        "createdAt": utc_now(),
        "projectUuid": project_uuid,
        "sections": {},
        "errors": [],
    }

    def read_section(name: str, path: str, payloads: list[dict[str, Any]] | None = None) -> Any:
        body = try_post(client, path, payloads, call_paths)
        error = endpoint_error(name, path, body)
        if error:
            snapshot["errors"].append(error)
        return body

    models_body = read_section("models", "/models/get-with-datasets")
    models = arr(models_body)
    snapshot["sections"]["models"] = {"items": summarize_named(models), "raw": compact(models_body)}

    classes_body = read_section("classes", "/classes/get-list")
    classes = arr(classes_body)
    snapshot["sections"]["classes"] = {"items": summarize_named(classes), "raw": compact(classes_body)}

    indicators_body = read_section("indicators", "/indicators/get-list")
    indicators = arr(indicators_body)
    snapshot["sections"]["indicators"] = {"items": summarize_named(indicators), "raw": compact(indicators_body)}

    dictionaries_body = read_section("dictionaries", "/dictionaries/get-list")
    dictionaries = arr(dictionaries_body)
    snapshot["sections"]["dictionaries"] = {"items": summarize_named(dictionaries), "raw": compact(dictionaries_body)}

    objects_body = read_section("objects", "/objects/get-list")
    objects = arr(objects_body)
    snapshot["sections"]["objects"] = summarize_objects(objects, args.include_object_samples)

    tables_body = read_section("dataTables", "/data-tables/get-list")
    tables = arr(tables_body)
    table_ids = [uuid for uuid in (get_id(item) for item in tables) if uuid]
    snapshot["sections"]["dataTables"] = {
        "items": summarize_named(tables),
        "details": collect_by_ids(
            client,
            "/data-tables/get-by-id",
            table_ids,
            [{"UUID": "<uuid>"}],
            args.details_limit,
            call_paths,
        ),
    }

    dashboards_body = read_section("dashboards", "/dashboards/get-list")
    dashboards = arr(dashboards_body)
    dashboard_ids = [uuid for uuid in (get_id(item) for item in dashboards) if uuid]
    dashboard_tree = read_section(
        "dashboardTree",
        "/dashboards/tree-get-down",
        [
            {
                "perPage": 5000,
                "nodeUuid": None,
                "root": None,
                "nodeNum": 0,
                "sortBy": "createdAt",
                "sortDesc": False,
                "filter": {"nodeTypes": [], "openedNodesUUIDs": []},
            }
        ],
    )
    snapshot["sections"]["dashboards"] = {
        "items": summarize_named(dashboards),
        "tree": sanitize(dashboard_tree),
        "details": collect_by_ids(
            client,
            "/dashboards/get-by-id",
            dashboard_ids,
            [{"UUID": "<uuid>", "uuid": "<uuid>"}],
            args.details_limit,
            call_paths,
        ),
    }

    publications_body = read_section("publications", "/publications/get-list")
    publications = arr(publications_body)
    project_publications = keep_current_project_items(publications, project_uuid)
    filtered_out_publications = len(publications) - len(project_publications)
    snapshot["sections"]["publications"] = {
        "items": summarize_named(project_publications),
        "raw": {
            "count": len(project_publications),
            "sample": sanitize(project_publications[:5]),
        },
        "filteredOutOtherProjects": filtered_out_publications,
        "details": collect_by_ids(
            client,
            "/publications/get-by-ids",
            [uuid for uuid in (get_id(item) for item in project_publications) if uuid],
            [{"uuids": ["<uuid>"]}, {"UUIDs": ["<uuid>"]}],
            args.details_limit,
            call_paths,
        ),
    }

    integration_payloads = [
        {},
        {"projectUuid": project_uuid, "uuids": None},
        {"byProject": project_uuid, "onlyGlobal": False, "page": 1, "perPage": 5000, "term": ""},
    ]
    integrations_body = read_section("integrations", "/integrator/get-list", integration_payloads)
    integrations = arr(integrations_body)
    integration_ids = [uuid for uuid in (get_id(item) for item in integrations) if uuid]
    integration_tree = read_section(
        "integrationTree",
        "/integrator/tree-get-down",
        [
            {
                "perPage": 5000,
                "nodeUuid": None,
                "root": None,
                "nodeNum": 0,
                "sortBy": "createdAt",
                "sortDesc": False,
                "filter": {"nodeTypes": [], "openedNodesUUIDs": []},
            }
        ],
    )
    snapshot["sections"]["integrations"] = {
        "items": summarize_named(integrations),
        "tree": sanitize(integration_tree),
        "raw": compact(integrations_body),
        "operations": collect_by_ids(
            client,
            "/integrator/get-operations-list",
            integration_ids,
            [{"integrationUuid": "<uuid>"}, {"IntegrationUUID": "<uuid>"}],
            None,
            call_paths,
        ),
        "fieldRules": collect_by_ids(
            client,
            "/integrator/get-fields-rules-list",
            integration_ids,
            [{"integrationUuid": "<uuid>"}, {"IntegrationUUID": "<uuid>"}],
            None,
            call_paths,
        ),
        "outputSamplingConditions": collect_by_ids(
            client,
            "/integrator/get-output-sampling-conditions-list",
            integration_ids,
            [{"integrationUuid": "<uuid>"}, {"IntegrationUUID": "<uuid>"}],
            None,
            call_paths,
        ),
        "variables": collect_by_ids(
            client,
            "/integrator/get-variables-by-integration-uuid",
            integration_ids,
            [{"integrationUuid": "<uuid>"}, {"IntegrationUUID": "<uuid>"}],
            None,
            call_paths,
        ),
    }

    sources_body = read_section("integrationSources", "/integrator/get-sources-list", integration_payloads)
    snapshot["sections"]["integrationSources"] = {"items": summarize_named(arr(sources_body)), "raw": compact(sources_body)}

    integration_tables_body = read_section("integrationTables", "/integration-table/get-list", integration_payloads)
    integration_tables = arr(integration_tables_body)
    integration_table_ids = [uuid for uuid in (get_id(item) for item in integration_tables) if uuid]
    snapshot["sections"]["integrationTables"] = {
        "items": summarize_named(integration_tables),
        "raw": compact(integration_tables_body),
        "details": collect_by_ids(
            client,
            "/integration-table/get-by-ids",
            integration_table_ids,
            [{"uuids": ["<uuid>"]}, {"UUIDs": ["<uuid>"]}],
            args.details_limit,
            call_paths,
        ),
        "mappings": collect_by_ids(
            client,
            "/integration-table/get-mappings-list",
            integration_table_ids,
            [{"integrationTableUuid": "<uuid>"}, {"IntegrationTableUUID": "<uuid>"}],
            None,
            call_paths,
        ),
    }

    processes_body = read_section("processes", "/processes/get-list", [{}, {"projectUuid": project_uuid}])
    processes = arr(processes_body)
    process_tree = read_section(
        "processTree",
        "/processes/tree-get-down",
        [
            {
                "perPage": 5000,
                "nodeUuid": None,
                "root": None,
                "nodeNum": 0,
                "sortBy": "createdAt",
                "sortDesc": False,
                "filter": {"nodeTypes": [], "openedNodesUUIDs": []},
            }
        ],
    )
    tasks_body = read_section("tasks", "/tasks/get-list", [{}, {"projectUuid": project_uuid}])
    snapshot["sections"]["processes"] = {
        "items": summarize_named(processes),
        "tree": sanitize(process_tree),
        "raw": compact(processes_body),
    }
    snapshot["sections"]["tasks"] = {"items": summarize_named(arr(tasks_body)), "raw": compact(tasks_body)}

    snapshot["callSummary"] = {
        "count": len(call_paths),
        "paths": dict(Counter(call_paths)),
    }

    out_path = Path(args.out) if args.out else Path("ks_project_snapshot.json")
    safe_snapshot = sanitize(
        snapshot,
        secret_values=(client.password or "", client.token or ""),
    )
    write_text_atomic(
        out_path,
        json.dumps(safe_snapshot, ensure_ascii=False, indent=2),
    )

    if args.map_out:
        map_path = Path(args.map_out)
        write_text_atomic(map_path, build_map(safe_snapshot))

    print(f"snapshot: {out_path}")
    if args.map_out:
        print(f"map: {args.map_out}")
    print(f"errors: {len(snapshot['errors'])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KSAPIError as exc:
        print(f"KS API error: {redact_text(str(exc))}", file=sys.stderr)
        raise
