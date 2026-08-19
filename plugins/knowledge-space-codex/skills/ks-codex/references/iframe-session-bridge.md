# Session-scoped Dynamic IFRAME Routing

Use this pattern when a KS dashboard must change an embedded page without
reloading the dashboard and without persisting one user's selected URL into
shared dashboard configuration.

## Architecture

1. A KS button sends the final URL as a string entity.
2. The button saves that entity in a session-scoped global variable.
3. KS exposes the variable through `sessionStorage["dashboardVariables"]`.
4. A fixed `srcdoc` bridge polls the session value.
5. The bridge validates the URL and updates a nested IFRAME only when it
   changes.

Do not update `dashboard.configuration.cells[*].entity.iframeSrc` on each click.
That is a persistent shared-project write and can race between users.

## Button Action

Create the button in the current KS UI when possible and preserve all fields it
generates. The final action must include:

```json
{
  "type": "sendEntity",
  "sendEntityType": {
    "entityType": null,
    "value": "string",
    "additionalValue": "string"
  },
  "sendEntityValue": {
    "entityType": "string",
    "value": "https://example.test/page-1",
    "additionalValue": "https://example.test/page-1"
  },
  "sendEntityTags": "iframe_target_url",
  "saveGlobalVariable": true,
  "saveGlobalVariableType": "session",
  "saveGlobalVariableForce": true
}
```

The stored event is commonly exposed as `getString`. Verify the generated
dashboard JSON on the target stand rather than replacing a complete action with
this minimal example.

## IFRAME Cell

Keep the outer cell stable:

```json
{
  "type": "IFRAME",
  "iframeSrc": "about:blank",
  "iframeAttributes": [
    {
      "key": "srcdoc",
      "value": "<JSON-escaped iframe-bridge.html>"
    }
  ],
  "iframeParams": [],
  "iframeQueries": []
}
```

Use the complete contents of
`../assets/iframe-session-bridge/iframe-bridge.html`. Set its event tag, project
UUID, exact host allowlist, and optional path prefixes before inserting it.

The final rendered HTML must contain literal `</script>`. A verified KS
frontend left `<\/script>` unclosed inside `srcdoc`, so the bridge did not run.

The bridge needs script execution and same-origin access to KS session storage.
Do not add an outer `sandbox` unless required. If it is mandatory,
`allow-scripts allow-same-origin` is the minimum functional pair, but it reduces
the isolation normally provided by sandboxing.

## Security and Isolation

- Accept only `https:` URLs.
- Match exact allowed hostnames; never use substring matching.
- Treat session-storage values as untrusted input.
- Never put KS tokens, cookies, raw session identifiers, passwords, or source
  credentials into the URL or bridge.
- Let the embedded application authenticate and authorize its own users.
- Keep the event tag unique to this dashboard workflow.

This isolates the final URL in the browser session. It does not isolate shared
KS indicators or formulas used earlier to construct that URL. Move user-specific
inputs into session scope or enforce user identity in the receiving service.
Duplicating a browser tab can copy the initial `sessionStorage` snapshot.

## Browser Constraints

The target site must allow framing through `X-Frame-Options` and CSP
`frame-ancestors`. Third-party cookies and authentication redirects can also
fail inside an IFRAME. HTTP 200 alone is not proof: inspect DOM, console, and
network state.

## Verification

1. Read the dashboard and record its UUID and target cell UUID.
2. Save the stable `about:blank` plus `srcdoc` configuration once.
3. Reload once after that initial configuration write.
4. Select two URLs in sequence and confirm both load without another dashboard
   reload.
5. Open a separate browser session and confirm it retains an independent URL.
6. Read the dashboard back and verify the button session fields and stable cell
   configuration.
