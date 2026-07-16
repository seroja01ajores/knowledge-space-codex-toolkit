# Safe Writes

Use this file before any create/update/save call.

## Write Guardrails

1. Confirm target `KS_PROJECT_UUID`.
2. Read current entity through API.
3. Prepare a minimal patch in memory.
4. Print a dry-run summary unless the user already authorized execution.
5. Use official API write endpoint.
6. Verify by reading the same entity again.
7. Record changed UUIDs and fields in the final response.

Never use database `insert`, `update`, `delete`, or manual JSONB edits for project content.

## API Error Handling

Treat these as failures:

- non-2xx HTTP;
- JSON body contains `error`;
- response is empty when an entity update should be visible;
- follow-up read does not reflect the intended change.

Recommended helper:

```python
def api(session, base, path, payload):
    r = session.post(base + path, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json() if r.text else {}
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(data["error"])
    return data
```


## Safe Patch Plans

For non-trivial changes, generated patches, batch work, runtime actions, destructive actions, or anything learned from UI/API capture, create a safe patch plan first. See `safe-patch-workflow.md`.

Safe patch is a risk gate, not a permanent ban. Integration runs, BPMS starts, imports/exports, deletes, and access changes can be valid work when intentionally requested, scoped to the right project/stand, and approved at the matching risk level. Generic continuation instructions are not enough for those actions.

Use `scripts/ks_safe_patch_lint.py` offline to classify the plan before execution. A valid lint report means the plan is structured enough to review; it does not execute anything and does not grant approval for runtime/destructive/server actions.

## Data Saves

Use `/data/save`.

Prefer compact `Data` rows:

```json
{
  "Data": [
    {
      "ModelUUID": "<model>",
      "d": "<dataset>",
      "i": "<indicator>",
      "o": "<object>",
      "v": {"type": "number", "data": 10}
    }
  ],
  "IsManual": true,
  "SkipGetPreviousData": false
}
```

For dimensional indicators:

```json
"m": {"<dictionary_uuid>": "<dictionary_element_uuid>"}
```

Verify with `/data/get-list` using the exact same model, dataset, objects, indicators, and dimensions.

## Data Table Updates

Read:

```json
POST /data-tables/get-by-id
{"UUID": "<table_uuid>"}
```

If editing constructor data:

- mutate only `data.constructorData`;
- keep unrelated table data/settings unchanged;
- try `/data-tables/update-constructor-data` if available;
- fallback to `/data-tables/update`.

Fallback payload:

```json
{
  "UUID": "<table_uuid>",
  "Name": "<existing name>",
  "Data": "<existing data with modified constructorData>",
  "ConstructorData": "<modified constructorData>"
}
```

## Dashboard Updates

Read:

```json
POST /dashboards/get-by-id
{"UUID": "<dashboard_uuid>"}
```

Update:

```json
POST /dashboards/update
{
  "uuid": "<dashboard_uuid>",
  "name": "<existing name>",
  "description": "<existing description>",
  "height": 800,
  "width": 1200,
  "type": "dashboard",
  "configuration": "<modified configuration>"
}
```

Only mutate the target cells or events. Preserve unrelated config fields.

## Publications

Use publication APIs to add dashboards to apps. For modal dashboards:

- add the modal dashboard to `innerTree`;
- set it hidden if it should not appear in navigation;
- keep the main dashboard visible.

Do not modify publication access beyond the user-requested scope.

## SSH And DB Diagnostics


Use SSH/DB diagnostics only when API evidence is insufficient. Redact environment values, connection strings, tokens, and passwords from logs and responses.

Allowed read-only diagnostics:

- `docker ps`;
- `printenv` only when needed for DB connection diagnostics;
- `psql SELECT` queries against schema/table metadata or project-scoped data;
- logs when diagnosing server/API errors.

Forbidden during project work:

- SQL writes;
- container restarts;
- migrations;
- backup restore/load;
- role/user/global access edits;
- file edits on the server.

