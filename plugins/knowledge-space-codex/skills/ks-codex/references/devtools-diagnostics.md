# DevTools Diagnostics For KS

Use this reference when API/Swagger/snapshots are not enough to explain how the KS browser UI behaves. The goal is to learn endpoint shapes, dashboard event flow, frontend state, and browser-only errors without leaking secrets or changing unrelated projects.

## Safety

- Inspect only the target training/scratch project unless the user explicitly approves another project.
- Never save or print `Authorization`, `Cookie`, bearer tokens, passwords, source credentials, SSH keys, or raw session values.
- Treat browser storage as user state. Read `Session Storage`, `Local Storage`, cookies, and cache for diagnostics; clear or delete values only on a training/scratch profile or with explicit approval.
- Do not replay captured `delete`, `run`, `integrate`, backup load/restore, import/export, refresh, role/access, or admin requests without exact user approval and the normal KS safe-patch/runtime gate.
- If a browser action might start integrations, BPMS, recalculation, import/export, or backup work, stop at observation unless the user has approved that exact runtime action.

## Network Capture Checklist

1. Open DevTools with `F12`, `Fn+F12`, or `Ctrl+Shift+I`; use Chrome/Edge when possible.
2. Open `Network`.
3. Enable `Preserve log` before reproducing redirects, login, WebSocket, modal, or multi-step UI behavior.
4. Use `Disable cache` while DevTools is open when stale frontend state is suspected.
5. Filter to `Fetch/XHR` and, if needed, `/api/`.
6. Clear the log immediately before one target UI action.
7. Perform exactly one action, then stop recording or avoid extra clicks.
8. Inspect `Headers`, `Payload`, `Preview`, and `Response`.
9. Record the normalized endpoint path, HTTP method, status, request payload shape, response wrapper, and any JSON `error`.
10. Export HAR or copy as cURL/fetch only after redacting auth/cookies/tokens/secrets.

Prefer the request `Path` over the displayed request `Name` when identifying a KS endpoint. A path such as `/api/dashboards/get-by-id` is usually more useful than a short repeated name like `get` or `get-by-id`.

## Interpreting Responses

- `2xx` means the HTTP request completed; still inspect the JSON body because KS can return an `error` object inside a successful HTTP response.
- `4xx` normally points to request/auth/project/payload problems.
- `5xx` points to server-side handling failure; collect endpoint, payload shape, request id if present, and the redacted error body.
- In `Preview`, use recursive expansion for nested objects and arrays. Use the browser search box inside the response tree to find UUIDs, formula IDs, table fields, or error text.
- In KS data responses, common compact keys are:
  - `d`: dataset;
  - `i`: indicator;
  - `m`: dimension;
  - `o`: object;
  - `v`: value.

## Copying A Request

Use right click on a Network request and copy as cURL, PowerShell, fetch, or Node fetch. This is useful for comparing the browser request with an API script.

Before adding any copied request to a skill/reference/task:

1. Remove `Authorization`, `Cookie`, CSRF/session headers, passwords, and personal/source credentials.
2. Replace project/user/entity UUIDs with placeholders unless they are intentionally part of a stand-specific note.
3. Keep only the minimum payload fields needed to document the API shape.
4. Mark the pattern as observed if it has not been verified by a fresh API write/read-back.

## WebSocket Diagnostics

Use the `Network` filters `WS`, `Socket`, or `WebSocket` when debugging background KS work that reports progress through messages: integrations, BPMS-triggered integrations, backups, long-running imports/exports, and some interface events.

Workflow:

1. Enable `Preserve log`.
2. Filter to WebSocket requests.
3. Refresh or reopen the relevant page if no socket is present.
4. Open the socket request and inspect `Messages`.
5. Expand messages recursively and inspect `type`, `subject`, `message`, `result`, `errors`, and `info`.

Do not start integrations, BPMS, backups, restores, imports, exports, or recalculations solely to collect WebSocket messages unless that exact runtime action has been approved.

## Dashboard Event Logging From Console

Some KS frontends expose diagnostic helpers on `window`. Use them only for observation in a browser session; they should not be persisted in project JSON.

Useful commands when available:

```js
window.dashSelectedCellUuid
window.logDashEventStartLoggingCell("<cell_uuid>")
window.logDashEventStopLoggingCell("<cell_uuid>")
window.logDashEventCellUuids
window.logDashEventLoggingAll = true
window.logDashEventLoggingAll = false
```

To get a cell UUID from the UI editor, select/click the dashboard cell and evaluate `window.dashSelectedCellUuid`. If a command is unavailable on a stand/version, fall back to `/dashboards/get-by-id` and `configuration.cells[*].uuid`.

When reading dashboard event logs, focus on:

- event `type`, for example `getObject`, `getDataset`, `getTable`, `getDashboard`;
- `tags`, which must match between sender, variable, and receiver;
- `targetUuid`, the destination/listener cell or event target;
- entity UUIDs in `data.uuids`;
- whether the log line is a dispatch from a cell or execution by a receiving cell;
- `manualEvent`, which distinguishes user action from platform-triggered propagation;
- `time`, which can be converted with `new Date(<timestamp>)`.

For noisy dashboards, prefer cell-level logging over global logging. Turn logging off after the check.

## Event-Type Debug Flags

Some KS builds expose broader console flags for component-specific logs:

```js
window.logGanttEvents = true
window.logTableEvents = true
window.logChartEvents = true
window.logButtonActions = true
window.logDiagramActions = true
```

Disable them after use:

```js
window.logGanttEvents = false
window.logTableEvents = false
window.logChartEvents = false
window.logButtonActions = false
window.logDiagramActions = false
```

Use these flags to understand whether a click, row selection, Gantt selection, chart interaction, or button press emits the expected KS dashboard event before changing project JSON.

## Application Storage

Use `Application` / `Storage` when a UI issue may be caused by browser state instead of project config.

Read-only checks:

- `Session Storage`: inspect per-session interface state.
- `ganttSettings`: local Gantt display/filter settings; stale settings can make a valid Gantt look wrong.
- `dashboardVariables`: saved global variables, selected objects/tables, and values used by dashboard events.
- Cookies: confirm a session exists, but do not copy cookie values into logs.

Clearing site data, cookies, or storage can change the local browser session and sign the user out. Do it only on a disposable profile/training stand or after approval.

## Common KS Debug Scenarios

### Empty Or Wrong Interface Block

1. Inspect the dashboard via API first: cell size, entity refs, table refs, events, and publication node.
2. In browser view mode, open DevTools console.
3. Enable logging for the suspected cell or component type.
4. Trigger the UI action once.
5. Confirm the emitted event type/tags/source UUID match the receiving cell.
6. Check Network for `/api/dashboards/get-by-id`, table data requests, and any frontend error response.

### Recalculation Error

Open Network, reproduce the recalc/error display, find the error-log request, and inspect `Preview` for error message, indicator/formula UUIDs, recalculation log UUIDs, and stack/error context. Do not rerun recalculation without approval if it is not already part of the user's requested action.

### BPMS Instance Error

Open the business process history/details screen, clear Network, open the failing instance details, and inspect the steps/list response. Expand the failed element and inspect `error`, failed task element UUID, duration, and any integration/formula context.

### Integration Error

If the integration is launched by a process or UI button, identify the process/task/button first. With approval for the runtime action, inspect WebSocket `Messages` after launch. Expand `errors` and `info` blocks and keep the operation/integration UUIDs, source/table names, and redacted error cause.

### Backup Or Restore Error

Use WebSocket messages to inspect backup/create/load progress and failure details. Treat backup creation, load, restore, and import as runtime/destructive-adjacent actions requiring explicit approval.

### Tree Search Appears Stuck

Watch Network for tree requests such as `tree-get-node-tree`. `Pending` means search/loading is still in progress; HTTP `200` means the request finished even if zero nodes were found.

### Find The Request Behind A Visible UI Error

Copy a short distinctive phrase from the visible browser error and use Network search. Open the matching request, inspect `Preview`/`Response`, then copy the path from the address bar or request details for API reproduction.

### Responsive Or Aspect-Ratio Checks

Use the device toolbar in DevTools to test dashboards at different widths/heights when the issue is overlap, clipped buttons, hidden scrollbars, or responsive layout. Combine this with an API cell report before changing layout.

## Turning Findings Into KS Skill Knowledge

Add a finding to a KS skill/reference only when it is portable or clearly marked as stand/version-specific. Good entries include:

- normalized endpoint and method;
- payload fields that were necessary;
- response wrapper and important fields;
- event type/action/tag/source/target relationships;
- safety gate required before replaying the action.

Do not add raw HAR files, screenshots containing secrets, cookies, tokens, source credentials, or personal data to portable archives.
