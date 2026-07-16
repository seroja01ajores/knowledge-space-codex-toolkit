# Safe Patch Workflow

Use this workflow before API writes, broad repairs, generated patch batches, integration/BPMS edits, access changes, imports, or any action learned from UI/API captures.

Safe patch is not a hard ban on integrations, BPMS, deletes, imports, or other advanced KS features. It is a staged risk gate that lets the agent learn and plan any operation, while preventing accidental execution against the wrong project, wrong stand, external systems, or server/global state.

## Modes

- `dry_run`: default. Build a plan, classify risk, inspect payloads, and produce read-back checks. No API writes or runtime actions.
- `execute_project_writes`: allows ordinary project-scoped create/update/save calls after read-before, dry-run summary, and read-back checks.
- `approved_runtime`: allows exact approved runtime actions such as integration run, connection check, integration-table refresh/export/update, BPMS start/complete, model recalculation, or file import/export.
- `approved_destructive`: allows exact approved destructive/global actions such as delete, access changes, backup restore/import, or broad cleanup, with narrow targets and rollback/export notes.
- `server_maintenance`: only for explicit server maintenance tasks. Project work should not use this mode.

Learning rule: the agent may study, model, and dry-run high-risk endpoints, but must not execute them just because the plan is valid. Execution requires the matching mode and exact user approval.

## Patch Plan Shape

Use a JSON plan for non-trivial changes:

```json
{
  "metadata": {
    "task": "repair selected dashboard events",
    "baseUrl": "https://<host>/api",
    "targetProjectUuid": "<project_uuid>",
    "mode": "dry_run"
  },
  "approval": {
    "userApproved": false,
    "approvedOperationIds": [],
    "approvedEndpoints": []
  },
  "operations": [
    {
      "id": "dashboard-events-1",
      "endpoint": "/dashboards/update",
      "method": "POST",
      "entityType": "dashboard",
      "entityUuid": "<dashboard_uuid>",
      "entityName": "<dashboard_name>",
      "summary": "Replace legacy nested-dashboard button events with sendEntity/place",
      "readBefore": {"endpoint": "/dashboards/get-by-id", "payload": {"UUID": "<dashboard_uuid>"}},
      "payload": "<redacted or path to generated payload>",
      "readBack": {
        "endpoint": "/dashboards/get-by-id",
        "payload": {"UUID": "<dashboard_uuid>"},
        "checks": [
          {"path": "data.name", "equals": "<approved-dashboard-name>"}
        ],
        "manualChecks": [
          "button emits sendEntity",
          "nested cell listens getDashboard/place"
        ]
      },
      "rollback": "Restore dashboard JSON captured by readBefore"
    }
  ]
}
```

For generated payloads, store payload files locally and refer to paths instead of pasting huge JSON into chat. Keep secrets redacted.

Every write/runtime operation must declare exactly one of `payload` or
`payloadPath`. Nested read-before/read-back blocks may declare at most one.
The plan must declare only one operation container (`operations`, or the
legacy `patches` alias), and duplicate/conflicting mode declarations are
blockers rather than precedence rules.
Paths are relative to the plan directory and may not traverse it, be absolute,
or resolve through a symlink. An intentional empty request body is written as `"payload": {}`;
`payloadBuildHint` alone keeps a generated draft non-executable. Machine checks
are objects with `path` plus exactly one operator: `equals`, `notEquals`,
`exists`, `contains`, or `length`. Paths may use dotted form, JSON Pointer, or
`$` for the response root. Keep browser or cross-response assertions under
`manualChecks`; they do not replace machine checks. Project writes require a
non-empty machine `checks` list. Runtime operations require the same unless a
specific documented `verificationWaiver` is reviewed.

Runtime secrets use a dedicated namespace so login credentials cannot be
accidentally injected into an integration request:

```json
{
  "id": "connection-check-1",
  "endpoint": "/integrator/check-connection",
  "payload": {"connection": {"password": "<password>"}},
  "payloadEnv": [
    {
      "path": "connection.password",
      "env": "KS_RUNTIME_PAYLOAD_SOURCE_PASSWORD"
    }
  ]
}
```

Set `KS_RUNTIME_PAYLOAD_SOURCE_PASSWORD` only for that reviewed run. Generic
environment names and core credentials such as `KS_TOKEN`, `KS_PASSWORD`, SSH,
cloud or source-control credentials are rejected. A `payloadEnv` path may point
only to a credential or source-connection value such as password, token, host,
login, database or URL. It cannot inject an entity/project UUID, action,
delete/control flag or another approval-sensitive target. Reusing the live KS
login, password or token value is rejected even through a correctly named
`KS_RUNTIME_PAYLOAD_*` variable.

The generic project-write executor uses a `single_entity` target strategy. A
UUID-shaped `entityUuid`, the top-level mutation `UUID`/`uuid`, and every
explicit `/get-by-id` read-before/read-back UUID must identify the same entity.
Create/batch payloads that cannot express this contract need a separate,
documented target strategy before they become executable.

## Risk Classes

- `read_only`: list/get/tree/search/history endpoints. Safe to call when credentials and project are scoped.
- `project_write`: project-scoped create/update/save/copy/move. Requires read-before when possible, dry-run summary, write, and read-back.
- `external_or_runtime`: can call an external system, run integrations/processes, refresh integration tables, recalculate, import/export, or upload files. Requires exact runtime approval.
- `destructive_or_global`: deletes, access/global/user/role/project settings, backup restore/import, broad cleanup. Requires exact destructive approval and narrow target.
- `server_or_db`: SSH/DB/container/filesystem/server actions. Not part of KS project patching; requires explicit server-maintenance task.
- `unknown`: endpoint or action shape not classified. Treat as high-risk until Swagger/UI capture/reference confirms it.

## Required Checklist

Before execution:

1. Confirm one unambiguous stand URL and `targetProjectUuid`; conflicting aliases or explicit nulls are blockers. Never infer target from a browser tab alone.
2. Classify each operation by endpoint and business effect, not only by HTTP method.
3. Remove or redact passwords, tokens, cookies, source credentials, connection strings, SSH keys, and personal data from plan/payload/logs.
4. For project writes, read current entity first and preserve unrelated fields.
5. For runtime/destructive operations, record exact operation id, endpoint, entity, expected effect, and user approval text.
6. Print a dry-run summary before writing: operation id, endpoint, entity type/name/UUID, changed fields, risk, read-back check.
7. Preflight every local input and output in the whole executable batch before
   login, then execute in small batches and stop on the first HTTP error, JSON
   `error`, empty unexpected response, or read-back mismatch.
8. After execution, read back every changed entity and report what remains browser-only or externally unverified.
9. If a mutation/runtime request times out or returns an unusable response,
   mark it `effect_unknown`, never retry automatically, stop subsequent
   operations, and perform only the already-declared best-effort read-back.

## What Safe Patch Must Not Do

- It must not permanently forbid integrations, BPMS, import/export, deletes, or access changes. These are valid KS work when intentionally requested and safely scoped.
- It must not execute external/runtime/destructive actions from a generic “continue” instruction.
- It must not turn server access into a shortcut for project writes.
- It must not hide uncertainty. Unknown endpoints stay unknown/high-risk until verified.

Use `scripts/ks_safe_patch_lint.py` to classify a patch plan offline before running anything.

Use `scripts/ks_safe_patch_execute.py` only after linting when you have a JSON plan and explicit execution intent. The executor is deliberately narrow: it can execute read-only calls and exact-approved `project_write` operations with read-before/read-back checks. It defers `external_or_runtime`, `destructive_or_global`, `unknown`, and `server_or_db` operations to separate approved flows. This is a capability boundary for the generic project-write script, not a permanent ban on integrations, BPMS, imports/exports, recalculation, deletes, or server maintenance when the user intentionally requests them and the correct approval mode is active.

Use `scripts/ks_approved_runtime_execute.py` for the separate `approved_runtime` flow. It can execute exact-approved runtime operations such as integration runs, connection checks, integration-table refresh/export/update, BPMS start/complete, and recalculation. It requires `metadata.mode=approved_runtime`, `approval.userApproved=true`, an approved operation id/endpoint, confirmed project UUID, `--execute`, and read-back/verification or a documented `verificationWaiver`. Use only dedicated `KS_RUNTIME_PAYLOAD_*` variables in `payloadEnv` entries for runtime secrets instead of storing passwords or tokens in plan JSON.
