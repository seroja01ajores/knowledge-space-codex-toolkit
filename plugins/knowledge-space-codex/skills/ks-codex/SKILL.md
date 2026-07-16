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
   Runtime payload credentials must come only from purpose-created
   `KS_RUNTIME_PAYLOAD_*` environment variables declared by exact payload path;
   never reuse `KS_TOKEN`, `KS_PASSWORD`, SSH, cloud, or source-control
   credentials as operation payloads.
7. Verify through API.
8. Verify high-risk UI paths in a browser when available, especially after dashboard, Gantt, modal, widget, or publication changes.

When browser access is unavailable, still build and audit through API, but mark visual behavior as unverified. Do not call a user-facing interface complete only because JSON references are present.

## What To Load Next

- Read `references/api-map.md` for endpoint names, payload casing, and known API quirks.
- Read `references/api-client-patterns.md` before writing automation scripts or troubleshooting API/session issues.
- Read `references/openapi-endpoints.md` when choosing endpoints for an unfamiliar KS feature.
- Read `references/ui-observed-builder.md` when creating a project or constructor entities from scratch; it summarizes payloads observed from the KS UI.
- Read `references/payload-examples.md` when you need compact redacted snippets for dashboard events, table constructors, publications, integration conditions, or BPMS task updates.
- Read `references/project-audit.md` before diagnosing a whole project or empty interfaces.
- Read `references/dashboard-events.md` before editing dashboards, nested interfaces, widgets, tables, modals, buttons, or Gantt events.
- Read `references/interface-authoring.md` before creating an interface from a design/Figma/template, adding analyst comments/descriptions, or doing layout tasks such as alignment, spacing, overlap repair, and readable table/modal layout.
- Read `references/bpms-patterns.md` before inspecting or configuring business processes, BPMS tasks, process-triggered integrations, variables, or process history.
- Read `references/complex-project-patterns.md` before auditing large planning or
  forecasting projects with role dashboards, nested navigation, modal flows,
  wide tables, and many integrations/processes.
- Read `references/ui-network-capture.md` when Swagger or existing references are insufficient and you need to learn endpoint/payload shapes by observing KS UI actions.
- Read `references/devtools-diagnostics.md` when using Chrome/Edge DevTools to diagnose KS UI behavior through Network, WebSocket messages, console dashboard event logs, session storage, frontend cache, responsive view checks, or browser-only errors.
- Read `references/ks-1-7-field-notes.md` when troubleshooting KS 1.7 behavior around dictionaries, integrations, formulas, tables, and interface edge cases captured from field knowledge-base cards.
- Read `references/advanced-course-patterns.md` before building or auditing the advanced KS course, especially widgets, dimensional currency data, Gantt modal events, and publication nodes.
- Read `references/course-project-workflows.md` before recreating, completing,
  or comparing a base, advanced, or integration training project in an isolated
  scratch project.
- Read `references/safe-writes.md` before using any create/update/save endpoint.
- Read `references/safe-patch-workflow.md` before generated patch batches, broad repairs, integration/BPMS runtime actions, destructive operations, imports/exports, or any change where execution mode and approval level matter.
- Read `references/backups-zstd.md` before inspecting exported KS project backups or `.zst`/zstd-compressed JSON.
- Use `$ks-diagram-roundtrip` for the versioned offline workflow `KS backup -> Diagramm JSON -> dry-run change plan -> cloned backup`; it owns bridge maps, supported/deferred field rules, structural validation, packing, and isolated restore/read-back safety.
- Read `references/integrations-patterns.md` before working with sources, integrations, operations, integration tables, mappings, or integration-course projects.
- Read `references/integrations-course-build-spec.md` when recreating the DB integration course from scratch or comparing an integration-course project with the final demo backup.
- Use `scripts/ks_smoke_check.py` for a quick read-only project overview when env vars are available.
- Use `scripts/ks_project_diff.py` to compare two sanitized read-only snapshots before broad rebuilds, course checks, or interface repair work.
- Use `scripts/ks_integration_readonly_audit.py` to compare integration-course snapshots safely; it filters field rules and output sampling conditions by operation UUID so global read-back lists do not produce false counts.
- Use `scripts/ks_bpms_audit.py` after snapshots to inspect BPMS processes, tasks, run-integration settings, broken references, and run-safety warnings offline without calling KS.
- Use `scripts/ks_table_audit.py` after snapshots to inspect data table constructor rows/columns/filters and catch broken model/class/indicator/dictionary references before blaming dashboard layout.
- Use `scripts/ks_dashboard_cell_report.py` after snapshots to inspect dashboard cells, refs, events, coordinates, and overlap risks before any layout repair.
- Use `scripts/ks_dashboard_layout_plan.py` to generate an offline dry-run plan for dashboard alignment/spacing fixes before `/dashboards/update`.
- Use `scripts/ks_comment_audit.py` to audit verified description/comment targets and prepare safe analyst-description plans without inventing unsupported metadata.
- Use `scripts/ks_publication_patch_plan.py` to prepare a dry-run publication inner-node plan before adding visible or hidden dashboards to an application.
- Use `scripts/ks_safe_patch_lint.py` to classify a JSON patch plan offline and identify required execution gates before running API changes.

## Common KS Diagnostics

Empty interface blocks usually come from one of these, in order:

1. Dashboard cells have no usable size/layout in `configuration.cells[*].settings.sizeAndContent`.
2. Table cell points to the wrong `tableTable` or model.
3. Data table constructor rows/columns reference the wrong class, dataset, indicator, dimension, or relation path.
4. Data is missing for the exact dataset/object/indicator/dimensions shown in the table.
5. Incoming event action is wrong:
   - widget to ordinary object table: `filter`;
   - selected object to relation-scoped table: usually `tableFilterStructure` with `filter.tableCellSettings`;
   - object-card relation replacement: `changeRelationObject`;
   - dictionary/dataset dimension filtering: often `tableFilterStructure`;
   - nested dashboard placement: button emits `sendEntity`, nested dashboard cell listens with `getDashboard` + `place`;
   - modal button opening: prefer `showDashboard` + `showType: inWindow` over imported legacy `getDashboard` + `modal`.
6. Publication does not include the dashboard, or a modal dashboard is not included as hidden.
7. Frontend cache/session is stale after config writes.
8. The route uses the entity UUID as `node`; the KS UI often needs the real tree node UUID from `/dashboards/tree-get-down` or a tree click.
9. A frontend component fails despite valid JSON. Check browser console and avoid relying on API state alone for widgets, charts, nested dashboards, and modals.

## Writing Style For User Updates

Report KS work as facts:

- what endpoint/section was checked;
- what was missing or wrong;
- what was changed;
- what remains unverified.

Do not claim a project is complete until API checks and browser behavior both match the requested workflow.

## Private Evidence Overlay

If the user supplies a separate private overlay with redacted UI/API evidence,
use it as empirical input for constructor payloads. Keep raw captures, customer
identifiers, stand profiles and uncertain observations outside this public
plugin. Promote a learned pattern only after normalization, safety
classification and a synthetic regression; this skill's safety rules remain
the governing policy.
