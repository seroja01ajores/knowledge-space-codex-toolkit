#!/usr/bin/env python3
"""Read-only KS project smoke check.

Environment:
  KS_BASE_URL       e.g. https://<host>/api
  KS_PROJECT_UUID
  KS_TOKEN           or KS_LOGIN + KS_PASSWORD
"""

from __future__ import annotations

import sys
from collections import Counter

from ks_api_client import KSAPIError, KSClient
from ks_secret_safety import redact_text


def arr(body):
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    data = body.get("data", body)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "objects", "list", "models", "dashboards", "publications"):
            if isinstance(data.get(key), list):
                return data[key]
        if all(isinstance(item, dict) for item in data.values()):
            out = []
            for key, item in data.items():
                copied = dict(item)
                copied.setdefault("uuid", str(key))
                out.append(copied)
            return out
    return []


def current_project_items(items: list[dict], project_uuid: str) -> list[dict]:
    out = []
    for item in items:
        item_project_uuid = item.get("projectUuid") or item.get("ProjectUUID")
        if not item_project_uuid or item_project_uuid == project_uuid:
            out.append(item)
    return out


def safe_line(client: KSClient, value: str) -> str:
    """Redact configured credentials and embedded secret representations."""
    return redact_text(value, (client.password or "", client.token or ""))


def main() -> int:
    client = KSClient.from_env(require_project=True)
    client.login()
    project_uuid = client.project_uuid
    if not project_uuid:  # Kept explicit for type-checkers and fail-closed CLI behavior.
        raise KSAPIError("KS_PROJECT_UUID is required for project-scoped KS work")

    models_payload = client.post("/models/get-with-datasets", {})
    models = arr(models_payload)
    print(f"models: {len(models)}")
    for model in models[:20]:
        print(
            safe_line(
                client,
                f"- {model.get('name') or model.get('Name')} "
                f"{model.get('uuid') or model.get('UUID')}",
            )
        )

    classes = arr(client.post("/classes/get-list", {}))
    print(f"classes: {len(classes)}")

    objects = arr(client.post("/objects/get-list", {}))
    by_class = Counter(item.get("classUuid") for item in objects)
    print(f"objects: {len(objects)}")
    for class_uuid, count in by_class.most_common(20):
        print(safe_line(client, f"- class {class_uuid}: {count}"))

    tables = arr(client.post("/data-tables/get-list", {}))
    print(f"data_tables: {len(tables)}")
    for table in tables[:30]:
        print(safe_line(client, f"- {table.get('name')} {table.get('uuid')}"))

    dashboards = arr(client.post("/dashboards/get-list", {}))
    print(f"dashboards: {len(dashboards)}")
    for dashboard in dashboards[:30]:
        print(safe_line(client, f"- {dashboard.get('name')} {dashboard.get('uuid')}"))

    all_publications = arr(client.post("/publications/get-list", {}))
    publications = current_project_items(all_publications, project_uuid)
    filtered_out = len(all_publications) - len(publications)
    print(f"publications: {len(publications)} filtered_out_other_projects: {filtered_out}")
    for publication in publications[:30]:
        print(
            safe_line(
                client,
                f"- {publication.get('name')} {publication.get('uuid')} "
                f"access={publication.get('accessType')} link={publication.get('link')}",
            )
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KSAPIError as exc:
        print(f"KS API error: {redact_text(str(exc))}", file=sys.stderr)
        raise
