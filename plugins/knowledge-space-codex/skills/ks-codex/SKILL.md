---
name: ks-codex
description: "Use when auditing, building, repairing, or verifying Knowledge Space / KS projects through the official KS API, including course or scratch-project reconstruction; models, datasets, classes, indicators, formulas, objects and data; tables, dashboards, publications, Gantt, integrations, BPMS, approved runtime actions, and safe project-scoped changes."
metadata:
  short-description: Work safely with Knowledge Space projects
---

# KS Codex

Use this skill when a task involves Knowledge Space / KS project analysis or project-scoped edits.

On a new machine, run `scripts/ks_environment_preflight.py` before the first
API or packed-backup task. Install the plugin-root `requirements.txt` when the
required `requests` package is missing; do not replace a failed prerequisite
check with ad-hoc credential handling.

## Non-Negotiable Safety Rules

- Work through the official KS HTTP API first. Do not write directly to PostgreSQL, Docker volumes, files, or server config.
- Every API request after login must include `X-Project-UUID` for the selected project.
- Treat HTTP 200 with an `error` field as failure.
- Read-only SSH/DB diagnostics are allowed only when the API is insufficient or inconsistent. Never use SSH/DB for writes unless the user explicitly asks for server maintenance.
- Keep edits inside the chosen KS project. Do not change users, global roles, deployment, nginx, containers, backups, or other projects while doing project work.
- Before any broad write, produce a dry-run summary: entity type, name, UUID, endpoint, and intended field changes.
- Avoid destructive actions (`delete`, role/access changes, backup restore/load, mass object deletion) unless the user explicitly requests that exact operation.

## Connection Pattern

Required environment:

```text
KS_BASE_URL=https://<host>/api
KS_LOGIN=<ks user>
KS_PASSWORD=<ks password>
KS_PROJECT_UUID=<project uuid>
```

Login:

```http
POST /auth/login
{"login": "...", "password": "..."}
```

Then use:

```http
Authorization: Bearer <token>
X-Project-UUID: <project uuid>
```

Prefer `requests.Session()` or a reusable client wrapper. Redact tokens and passwords from logs.

For new Python automation scripts, prefer the bundled `scripts/ks_api_client.py` helper for login, headers, project scoping, response unwrapping, JSON `error` handling, and redacted diagnostics.

## Recommended Workflow

1. Identify the target project and confirm `KS_PROJECT_UUID`.
2. Read the project structure: models, datasets, classes, indicators, dictionaries, objects.
3. Read UI artifacts: data tables, dashboards, dashboard tree nodes, publication tree, Gantt charts if relevant.
   For a standard safe baseline, run `scripts/ks_readonly_audit_runner.py` against an existing `snapshot.json` or with `KS_BASE_URL`, `KS_LOGIN`, `KS_PASSWORD`, and `KS_PROJECT_UUID` set; it creates a read-only snapshot and bundled dashboard/table/BPMS/integration reports.
4. Compare actual state with the user request, course file, or target spec.
5. Separate findings into:
   - missing model/data entities;
   - missing values;
   - wrong dashboard events;
   - wrong table constructor settings;
   - publication/access problems;
   - frontend-only verification gaps.
6. Make small project-scoped API writes.
   For JSON safe patch plans, run `scripts/ks_safe_patch_lint.py` first. Use `scripts/ks_safe_patch_execute.py` only for read-only calls and approved `project_write` operations; runtime/destructive/server actions are not banned, but require a separate exact-approved runtime/destructive/server flow.
   For intentional integration runs, connection checks, integration-table refresh/export/update, BPMS start/complete, or recalculation, use `scripts/ks_approved_runtime_execute.py` with `metadata.mode=approved_runtime`, exact operation approval, target project verification, and read-back/verification or an explicit verification waiver.
   After either executor writes its JSON report, use
   `scripts/ks_execution_receipt.py` for a compact hashed evidence receipt.
   Read `references/execution-receipts.md`; a receipt never carries approval
   or authorizes retry.
   Runtime payload credentials must come only from purpose-created
   `KS_RUNTIME_PAYLOAD_*` environment variables declared by exact payload path;
   never reuse `KS_TOKEN`, `KS_PASSWORD`, SSH, cloud, or source-control
   credentials as operation payloads.
7. Verify through API.
8. Verify high-risk UI paths in a browser when available, especially after dashboard, Gantt, modal, widget, or publication changes.

When browser access is unavailable, still build and audit through API, but mark visual behavior as unverified. Do not call a user-facing interface complete only because JSON references are present.

## Adaptive Task Operating Model

Codex interprets the request semantically; scripts never classify user wording.
Select any number of areas required by entities, effects, dependencies, safety,
and verification. The planner already has no numeric area limit; never truncate
a real dependency chain to fit an arbitrary count.

- **Direct**: entities and outcome are clear; work without a capability plan.
- **Coordinated**: dependent phases, approvals, handoff, resume, or audit trail;
  keep a structured plan and load details per phase.
- **Discovery**: no matching section or uncertain entity/effect; gather minimal
  read-only evidence, then switch to Direct or Coordinated.

For every mode, load only current-phase detail, but add every reference actually
needed. Reduce completed evidence to UUID-bound facts, unknowns, approvals,
artifacts, verification status, and next action; never retain credentials or
raw customer data. Rebuild the working set when evidence changes.

For Coordinated work, follow `multidomain-orchestration.md`. Codex selects
capability and operation IDs; `ks_capability_plan.py` validates them, expands
prerequisites/read-before phases, and remains planning-only. Actual effect
classification stays with the safe patch and approved runtime tools.
After writing a plan outside the plugin, use its `pack` command for the
current phase. The result contains only resource paths, hashes, gates, expected
outputs, and handoff policy; it embeds no reference or script content and never
authorizes execution. Read `references/adaptive-context-packs.md` for the
contract and resume flow.
For work resumed in another task or after an approval boundary, use
`scripts/ks_task_handoff.py` and read `references/task-handoff.md`. Keep the
handoff outside the plugin; it carries reduced evidence and lineage, not raw
responses or permission.

For Discovery, inspect API maps/OpenAPI first, then redacted official UI
network evidence. Use read-only server/DB diagnostics only when API/UI is
insufficient and policy permits it. Record a capability gap or candidate card
after solving; discovery never inherits non-read permission. For a Coordinated
unknown task, select one or more `capability-discovery` operations alongside
every already-known area involved; this is a fallback evidence workflow, not a
natural-language router.

Read references/use-case-patterns.md only when the request is unfamiliar,
product-shaped, ambiguous between modes, or involves cross-area state,
multi-user/session isolation, migration, lineage, or reusable automation.
Skip it for routine Direct work.

## Capability And Reference Map

This is the full surface overview; operation details stay in
`capability-index.json` and load only on demand.

| Area | Load on demand |
| --- | --- |
| Environment/API | `api-client-patterns.md`, `api-map.md`, `openapi-endpoints.md` |
| Models/data | `project-audit.md`, `api-map.md`, `ui-observed-builder.md` |
| Indicators/formulas | `api-map.md`, `payload-examples.md`, version field notes |
| Tables | `project-audit.md`, `dashboard-events.md`, `payload-examples.md` |
| Dashboards/interfaces | `dashboard-events.md`, `interface-authoring.md` |
| IFRAME/external sessions | `iframe-session-bridge.md`, `external-web-session-contracts.md` |
| Publications/Gantt | `dashboard-events.md`, `payload-examples.md` |
| Integrations | `integrations-patterns.md` |
| BPMS | `bpms-patterns.md` |
| Browser diagnostics | `devtools-diagnostics.md`, `ui-network-capture.md` |
| Courses | `course-project-workflows.md` plus the matching course reference |
| Backups/diagrams | `backups-zstd.md`, `project-clone-restore.md`, or `$ks-diagram-roundtrip` |
| Unknown work / adaptive context | `adaptive-context-packs.md`, `use-case-patterns.md` |
| Safe execution | `safe-writes.md`, `safe-patch-workflow.md` |
| Execution evidence | `execution-receipts.md`, `execution-receipt.schema.json` |

Read `references/diagnostics-toolbox.md` when choosing a bundled audit or
planning script, or when diagnosing an empty interface. Run a script for its
output without loading its source unless the task is to modify that script.

## Automation Preference

- Reuse an existing bundled client, auditor, planner, or executor when it fits
  the required effect; do not generate parallel infrastructure by default.
- Use deterministic scripts for repetitive or fragile operations. Keep
  context-dependent diagnosis and capability selection in Codex.
- Prefer offline snapshots, diffs, dry runs, and linted plans before writes.
- When no automation exists, solve the task safely first. Propose a reusable
  tool only after the workflow and its safety boundary are understood.
- Promote a new helper into the plugin only when it is reusable, redacted,
  project-scoped, and does not bypass existing gates.

## Evidence Retrieval And Learning

Use `scripts/ks_knowledge.py` only with user-provided private cards and database
roots. The derived SQLite FTS5 index stays outside the plugin and never changes
KS.

For retrieval:

1. Query with discovered entities, endpoint families, KS version, symptom, and
   intended effect rather than only the user's original wording.
2. Start with one focused pass of up to five `verified` or `promoted` cards.
   If an evidence gap remains, run another narrower pass; five is a per-pass
   context bound, not a limit on the task's knowledge.
3. Treat matches as evidence. Re-check UUIDs, dependencies, live state, and
   version compatibility. Retrieval never grants permission.

For learning from unfamiliar or corrected work:

1. Prepare a `candidate` card only after the useful result and its safety
   boundary are understood.
2. Record a redacted problem signature, KS version/scope, affected entities and
   endpoints, solution, evidence, rejected hypotheses, risk class, and
   verification state.
3. Write only to an explicitly supplied private cards root. Never persist raw
   backups, HAR files, screenshots, credentials, customer data, unredacted
   hostnames, or raw API responses.
4. Promote a card to `verified` or `promoted` only after independent read-back,
   browser evidence when material, and normalization for reuse.
5. Do not automatically copy private learning into the public plugin. Public
   promotion requires synthetic, stand-agnostic evidence and a separate review.

Read `references/knowledge-card.schema.json` before creating cards and
`references/self-learning.md` when maintaining the learning pipeline. Vector search
is optional; it supplements rather than replaces exact API and safety checks.

## Common KS Diagnostics

For empty interfaces and constructor failures, read
`references/diagnostics-toolbox.md`. Preserve the diagnostic order there; do
not jump from a blank cell directly to a dashboard rewrite.

## Writing Style For User Updates

Report KS work as facts:

- what endpoint/section was checked;
- what was missing or wrong;
- what was changed;
- what remains unverified.

Do not claim a project is complete until API checks and browser behavior both match the requested workflow.
