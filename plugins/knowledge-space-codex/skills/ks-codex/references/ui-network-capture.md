# UI Network Capture For KS

Use this workflow when the API or Swagger does not explain how the KS UI creates or updates an entity. The goal is to observe official UI requests, convert them into safe project-scoped API patterns, and update skill references without copying secrets or stand-specific data into portable docs.

## Safety Rules

- Capture only requests for the target training/scratch project.
- Never save or print `Authorization`, `Cookie`, CSRF headers, passwords, source credentials, SSH keys, or personal tokens.
- Redact project/user/source identifiers before adding examples to portable references unless the UUID is intentionally a placeholder.
- Do not replay captured `delete`, `run`, `integrate`, `refresh`, backup restore, access, or admin requests without explicit user confirmation.
- Prefer read-only observation first: click through the UI, inspect requests, and document payload shapes before writing through automation.

## What To Capture

For every UI action, record:

- UI area and action name, for example `Interfaces > create dashboard cell`, `Data tables > save constructor`, `Integrations > create field rule`.
- HTTP method and normalized endpoint path.
- Status code and whether the response contains an `error` object.
- Request payload with secrets redacted and UUIDs replaced by placeholders.
- Response shape only as much as needed to identify returned UUIDs or wrapper fields.
- Required headers beyond auth, such as `X-Project-UUID`, `X-Lang`, or locale headers.

## Preferred Capture Options

Use the strongest available option in the current environment:

1. Browser automation with network logging, if Codex has a browser tool or Playwright access.
2. Chrome/Edge DevTools Network tab with `Preserve log`, `Fetch/XHR` filter, and HAR export.
3. Browser started with Chrome DevTools Protocol remote debugging and a small CDP network listener.
4. Server-side access logs only as a fallback, and only for read-only diagnostics.

## Manual DevTools Workflow

1. Open the KS UI in a clean browser profile.
2. Log in as a user scoped to the training/scratch project.
3. Open DevTools > Network.
4. Enable `Preserve log`.
5. Filter to `Fetch/XHR` and, if useful, `/api/`.
6. Clear the log.
7. Perform exactly one UI action.
8. Save the relevant request/response details or export HAR.
9. Redact auth headers, cookies, passwords, personal data, and stand-specific UUIDs before sharing or adding to skill references.

## Codex Browser / Playwright Workflow

When browser automation is available, attach request and response listeners before clicking. The exact API varies by tool, but the discipline is stable:

```js
page.on("request", request => {
  const url = request.url();
  if (!url.includes("/api/")) return;
  console.log({
    method: request.method(),
    url,
    postData: redact(request.postData())
  });
});

page.on("response", async response => {
  const url = response.url();
  if (!url.includes("/api/")) return;
  console.log({
    status: response.status(),
    url,
    body: await safeJsonPreview(response)
  });
});
```

Capture one UI action at a time, redact secrets, and keep only normalized request shapes in portable docs.

If the plugin script is available, use it as a local helper:

```bash
node skills/ks-codex/scripts/ks_capture_api_calls.mjs \
  --url https://<ks-host>/ \
  --out captures/ks-api-capture.jsonl
```

Review output before sharing or committing, even though the helper redacts common auth, cookie, token, secret, and password fields.

## CDP Remote Debugging Option

If the user can launch a browser with remote debugging, use a dedicated browser profile and connect to Chrome DevTools Protocol:

```bash
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/ks-capture-profile
```

Subscribe to:

- `Network.requestWillBeSent`
- `Network.responseReceived`
- `Network.loadingFinished`

Only persist redacted API metadata. Do not store raw HAR files with cookies or bearer tokens in the repository.

## Detailed DevTools Diagnostics

For manual Chrome/Edge DevTools workflows beyond API request capture, read `devtools-diagnostics.md`. It covers Network request triage, WebSocket messages, console dashboard event logging helpers, Session Storage state, frontend cache checks, responsive view checks, and safe conversion of UI observations into portable KS references.

## Turning Captures Into Skill Knowledge

After capture:

1. Compare the observed endpoint with `references/openapi-endpoints.md`.
2. Compare payload shape with `references/ui-observed-builder.md`, `dashboard-events.md`, or feature-specific references.
3. If the pattern is general across KS, add a small normalized example to the portable reference.
4. If it is specific to one stand/version/project, put it in a stand-specific reference instead.
5. Mark untested write shapes as observed, not guaranteed.

## Naming Captures

For local work products, use explicit names:

```text
captures/YYYY-MM-DD/<area>/<number>-<short-action>.jsonl
captures/YYYY-MM-DD/<area>/<number>-<short-action>.har.redacted.json
```

Do not include raw non-redacted captures in archives intended for other analysts.
