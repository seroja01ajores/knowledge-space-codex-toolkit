# Security model

## Scope

The plugin is designed for project-scoped Knowledge Space work through the
official HTTP API and for offline processing of exported project backups. It
does not grant permission to change a KS deployment, database, containers,
users, global roles or unrelated projects.

## Capability gates

- `dry_run`: read, classify and prepare plans; no side effects.
- `execute_project_writes`: exact approved project-scoped changes with
  read-before and machine read-back checks.
- `approved_runtime`: exact approved integration, BPMS, recalculation, export,
  upload and similar runtime effects.
- `approved_destructive`: exact destructive/global operation such as delete,
  access change or isolated backup restore. The generic executors do not
  implement this gate.
- `server_maintenance`: explicitly separate server work. It is never inferred
  from a KS project task.

Unknown or ambiguous operations fail closed.

## Credential handling

- Configure `KS_BASE_URL`, `KS_PROJECT_UUID` and either `KS_TOKEN` or
  `KS_LOGIN`/`KS_PASSWORD` outside Git.
- Runtime integration secrets use dedicated `KS_RUNTIME_PAYLOAD_*` variables.
  They may target only reviewed credential/source-connection fields. Identity,
  project, action and control fields cannot be supplied through `payloadEnv`,
  and core KS credentials are rejected even if copied into an allowed variable.
- Do not paste cookies, CSRF values, private keys, source credentials or
  production backups into plans or issues.
- Generated reports redact sensitive keys and embedded credential patterns.
- Every locally knowable defect in an executable batch is checked before the
  first login or project API call. A lost mutation/runtime response is reported
  as `effect_unknown`; the batch stops, automatic retry is forbidden, and the
  declared read-back is attempted when possible.

## Backup and diagram safety

- Source backups are immutable inputs and must remain private.
- Large backups use bounded zstd slicing; business object values are not placed
  in the Diagramm read model.
- Every editable artifact is bound to source and artifact SHA-256 values.
- The write profile builds a cloned structural backup and never edits the
  original in place.
- Live restore is outside the offline CLI and must target a newly approved
  scratch project with its own destructive preflight and read-back.

## Reporting a vulnerability

Do not open a public issue containing credentials, customer data, real project
UUIDs, backup fragments or internal hostnames. Contact the repository owner
privately and include only a minimal synthetic reproduction.
