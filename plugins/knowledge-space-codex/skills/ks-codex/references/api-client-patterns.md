# API Client Patterns

Use this reference for every KS automation script before reads or writes.

## Base URL And Headers

Use the API base URL, not the UI root:

```text
KS_BASE_URL=https://<host>/api
```

Login outside project context:

```http
POST /auth/login
{"login":"<login>","password":"<password>"}
```

For all project work after login, send at least:

```http
Authorization: Bearer <token>
Content-Type: application/json
X-Project-UUID: <project_uuid>
X-Lang: ru_RU
X-Project-Locales: ru_RU
```

UI captures may include cookies, CSRF tokens, tab session IDs, and browser location headers. Do not ask users to paste those secrets into chat. Token auth plus `X-Project-UUID` is usually enough for API work.

## Required Error Handling

Treat all of these as failures:

- non-2xx HTTP status;
- response JSON has an `error` field;
- write endpoint returns success but follow-up read does not show the change;
- endpoint returns an empty structure where the entity must exist.

Recommended Python wrapper:

```python
import requests

session = requests.Session()

def ks(path, payload=None, project=True):
    headers = {"X-Lang": "ru_RU", "X-Project-Locales": "ru_RU"}
    if project:
        headers["X-Project-UUID"] = PROJECT_UUID
    response = session.post(BASE_URL + path, json=payload or {}, headers=headers, timeout=90)
    response.raise_for_status()
    data = response.json() if response.text else {}
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data["error"])
    return data
```

After login:

```python
auth_value = login_response.get("token") or login_response.get("accessToken") or login_response.get("data", {}).get("token")
session.headers.update({"Authorization": f"Bearer {auth_value}"})
```

## Payload Casing

KS endpoints use mixed casing. When an endpoint is finicky, inspect an observed UI payload or OpenAPI. Known examples:

- `/dashboards/get-by-id`: `{"UUID":"<dashboard_uuid>", "uuid":"<dashboard_uuid>"}` is a safe read pattern.
- `/dashboards/update`: send the raw dashboard object returned from `/dashboards/get-by-id`, after patching it. Do not send `{"dashboard": dashboard}`; that wrapper can return HTTP 200 with `{}` but not persist the dashboard changes.
- `/data-tables/get-by-id`: expects `UUID`; `TableUUID` can fail.
- `/data-tables/get-table-settings`: expects `TableUUID`.
- `/gantts/get-structure`: commonly needs `UUID`, `ModelUUID`, `ShowEmptyTasks`.
- data rows use compact keys: `d`, `o`, `i`, `m`, `v`, plus `ModelUUID`.

## Pagination And Lists

Do not assume defaults include all entities. Use explicit pagination where supported:

```json
{"Pagination":{"Page":1,"PerPage":5000}}
```

or endpoint-specific lowercase variants:

```json
{"pagination":{"page":1,"perPage":500}}
```

Use helper functions that accept both response shapes:

```python
def arr(body):
    data = body.get("data", body) if isinstance(body, dict) else body
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
```

## Project-Scoped List Verification

Do not assume every list endpoint is fully scoped by `X-Project-UUID`. Verified behavior: `/publications/get-list` can return publications from other projects visible to the current user, even when `projectUuid` is sent in the request body. After reading publications, filter client-side before reporting, auditing, or calling `/publications/get-by-ids`:

```python
publications = [
    item for item in arr(response)
    if not item.get("projectUuid") or item.get("projectUuid") == PROJECT_UUID
]
```

If a similar endpoint returns `projectUuid` / `ProjectUUID`, apply the same check and record how many other-project items were discarded.


## Project Creation And User Access

Create a new project node only when the user explicitly asks for a new project:

```http
POST /projects/create-node
```

```json
{
  "name": "Project name",
  "type": "project",
  "parentUuid": null,
  "previousUuid": null,
  "sourceUuid": ""
}
```

The response may expose the project UUID as `referenceUuid` / `ReferenceUUID`, not the tree node UUID. Use the reference UUID for all project-scoped work.

Find a user with `POST /users/get-user-by-login` or `POST /users/get`; then grant project access with:

```http
POST /project-access/create
```

OpenAPI casing can be required on some stands:

```json
{
  "ReferenceUUID": "<project_uuid>",
  "UserUUID": "<user_uuid>",
  "CanRead": true,
  "CanEdit": true,
  "CanReadUser": true,
  "CanEditUser": true
}
```

Verify with `POST /project-access/get` and `{"referenceUuids":["<project_uuid>"]}`.

## Write Discipline

Before write:

1. Confirm target project UUID and name.
2. Read current entity.
3. Prepare a minimal payload.
4. Print or summarize dry-run changes for broad writes.
5. Write through the official endpoint.
6. Read back and verify exact fields/counts.

Never use SQL writes, Docker, filesystem edits on the server, or backup restore for ordinary project content.

## Browser Verification

API success is necessary but not sufficient for UI work. For interfaces, also verify:

- cell layout has no overlaps;
- referenced dashboard/table/Gantt UUIDs exist;
- frontend cache is refreshed;
- widgets show real values, not skeletons or blank cards;
- publication includes modals that are opened from buttons or Gantt controls.
