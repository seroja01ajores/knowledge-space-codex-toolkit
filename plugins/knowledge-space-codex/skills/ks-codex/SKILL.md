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

## Required Decision Order

Use known compatible evidence before broad stand discovery:

1. Bind only the stand, project, named target, intended outcome, and expected
   effect needed to search safely. Do not inventory the project yet.
2. Check, in order, the exact user-supplied portable card, fresh private
   `verified` or `promoted` cards, a bundled deterministic pattern/helper, and
   an exact working same-project analogue.
3. Resolve one full recipe and perform the smallest compatibility check for KS
   version, endpoint family, target UUID, direct dependencies, preconditions,
   expected delta, and safety gate.
4. If compatible, execute through Direct or Coordinated mode and verify. If
   uncertain, perform one targeted read. If incompatible, record the reason
   and run one refined known-path search.
5. Enter Discovery only after known paths are absent, exhausted, or contradicted.
   Missing network, credentials, or approval is a pause boundary, not a reason
   to invent another solution.
6. Expand from target reads to area or full-project audit only on a material
   risk signal or an explicit user request. A full audit remains available; it
   is not the automatic first or final step for every narrow repair.

Read `references/known-path-first.md` when a portable/private card is present,
when choosing between a known route and Discovery, or when deciding how far to
expand an audit.

## Execution Workflow

1. Identify the target project and confirm `KS_PROJECT_UUID` without reading
   unrelated project state.
2. Select and compatibility-check the known route using the decision order
   above.
3. Choose the operating mode. For an eligible deterministic one-entity change,
   use the Mechanical Fast Path in `references/mechanical-fast-path.md`.
4. Read the exact target and only the dependencies named by the selected route.
   Use `scripts/ks_readonly_audit_runner.py` for an explicit baseline/audit or
   after evidence justifies broader inspection, not as a mandatory prelude.
5. Make small project-scoped API writes.
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
6. Verify the expected delta through API and confirm non-target state relevant
   to a full-object payload is unchanged.
7. Verify material UI behavior in a browser when available, especially after
   dashboard, Gantt, modal, widget, or publication changes.
8. Broaden the audit only when verification, dependency resolution, effect
   classification, or residual risk supplies a concrete reason. Prepare a
   private candidate card only after a genuinely novel route is verified.

When browser access is unavailable, still build and audit through API, but mark visual behavior as unverified. Do not call a user-facing interface complete only because JSON references are present.

## Adaptive Task Operating Model

Codex interprets the request semantically; scripts never classify user wording.
Select any number of areas required by entities, effects, dependencies, safety,
and verification. The planner already has no numeric area limit; never truncate
a real dependency chain to fit an arbitrary count.

- **Direct**: entities, outcome, known route, and effect are clear; work without
  a capability plan. Use the Mechanical Fast Path for one deterministic entity.
- **Coordinated**: dependent phases, approvals, handoff, resume, or audit trail;
  keep a structured plan and load details per phase.
- **Discovery**: known routes are exhausted or contradicted and the actual
  entity/effect remains uncertain; gather minimal read-only evidence, then
  switch to Direct or Coordinated.

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
For Coordinated work transferred to another task or resumed without the needed
working context, use
`scripts/ks_task_handoff.py` and read `references/task-handoff.md`. Keep the
handoff outside the plugin; it carries reduced evidence and lineage, not raw
responses or permission. Ordinary Direct continuation in the same task,
including an approval reply, does not require a handoff.

For Discovery, first record why the supplied/retrieved/bundled known paths were
not applicable. Then inspect API maps/OpenAPI, followed by redacted official UI
network evidence. Use read-only server/DB diagnostics only when API/UI is
insufficient and policy permits it. Record a capability gap or candidate card
after solving; discovery never inherits non-read permission. For a Coordinated
unknown task, select one or more `capability-discovery` operations alongside
every already-known area involved; this is a fallback evidence workflow, not a
natural-language router.

## Subagent Use

Do not spawn subagents for a normal Mechanical Fast Path. For Coordinated or
Discovery work, delegate only independent read-only checks that materially save
time, after one route and boundary are selected. Assign exactly one
`writer_owner`; every other agent is `no_write`. Readers never mutate KS, run
integrations/BPMS/recalculation, or perform active UI clicks with business
effects. Use a probe ledger to prevent duplicate investigations and stop
unneeded probes when a route is confirmed.

Read `references/subagent-orchestration.md` before delegating KS work. Its
single-writer rule does not replace the existing safe patch, runtime,
destructive, or server approval gates.
Use `scripts/ks_workflow_trace.py` only for regression testing or a
high-assurance handoff. It validates routing, bindings, audit escalation, and
writer/delegation policy offline; it neither proves task completion nor grants
permission.

Read references/use-case-patterns.md only when the request is unfamiliar,
product-shaped, ambiguous between modes, or involves cross-area state,
multi-user/session isolation, migration, lineage, or reusable automation.
Skip it for routine Direct work.

## Capability And Reference Map

This is the full surface overview; operation details stay in
`capability-index.json` and load only on demand.

| Area | Load on demand |
| --- | --- |
| Known path / audit depth | `known-path-first.md` |
| Mechanical Direct changes | `mechanical-fast-path.md`, then the exact area reference |
| Coordinated subagents | `subagent-orchestration.md` |
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

1. If the user supplies a portable card, use `inspect-card` on that exact file
   first. Otherwise query early from the requested outcome, symptom, named
   entity, likely capability, and intended effect; do not wait for a project
   inventory.
2. Start with one focused `search --ready-only` pass of up to five `verified`
   or `promoted` cards, adding known version/scope filters. It returns compact
   matches; use `get-card` with the selected ID and
   returned SHA-256 to load exactly one full recipe.
3. Check freshness, portable scope when moving across stands, KS version,
   endpoint family, target and dependency UUIDs, preconditions, and actual
   effect. Retrieval never grants permission.
4. If the first route is incompatible or ambiguous, make one narrower pass
   using the observed mismatch. Additional focused passes are allowed when new
   evidence warrants them; five is a per-pass context bound, not a task-wide
   knowledge limit.

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
