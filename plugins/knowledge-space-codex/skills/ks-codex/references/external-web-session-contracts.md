# External Web-service Session Contracts

Use this reference when a KS dashboard, button, integration, or embedded web
application sends user-selected filters or edits to an external service.

## Identity Boundary

The external service must determine the user from its own authenticated
session, signed token, or trusted gateway identity. Do not treat a query-string
`user_uuid`, client IP, KS tag, shared indicator, or raw KS session identifier
as proof of identity.

A browser-session KS variable can isolate the selected URL or filter before the
request leaves the tab. It does not replace server-side authorization or tenant
checks.

## Recommended Request Envelope

```json
{
  "request_id": "<uuid-or-ulid>",
  "project_uuid": "<ks-project-uuid>",
  "model_uuid": "<ks-model-uuid>",
  "dashboard_uuid": "<ks-dashboard-uuid>",
  "cell_uuid": "<stable-cell-uuid>",
  "value_mode": "absolute",
  "expected_revision": 17,
  "filters": {},
  "changes": []
}
```

Use `request_id` for correlation and logs. It is not an idempotency guarantee.
Use a separate `Idempotency-Key` or durable operation key when retries must not
apply the same change twice.

Prefer absolute desired values over deltas. A retry of `quantity = 100` can be
made idempotent; a retry of `quantity += 10` cannot without a durable ledger.
Use `expected_revision` or an equivalent ETag/version for optimistic
concurrency when two users can edit the same logical record.

## Server Rules

- Bind every request to the authenticated user and allowed tenant/project.
- Verify that all model, dataset, object, cell, and dimension UUIDs belong to
  that project; do not trust browser-provided ownership.
- Return the same result for a replayed idempotency key.
- Include `request_id`, operation status, applied revision, and a structured
  error code in responses.
- Reject stale revisions with a conflict response rather than silently
  overwriting newer state.
- Do not route responses by a process-global "last selected filter" value.
- Redact credentials, cookies, and personal data from logs.

## Cross-system Consistency

KS, a queue, a database, and an external compute service do not form one atomic
transaction. A request can update one store and fail before another. Production
flows need an outbox, operation journal, reconciliation worker, or another
explicit recovery mechanism. "No exception" is not proof that all business
rows were applied.

## IFRAME and Browser Notes

- Prefer an HTTP-only authenticated cookie or short-lived signed token owned by
  the embedded application.
- Account for `SameSite`, third-party-cookie, CSP, and `frame-ancestors`
  restrictions.
- Do not expose a bearer token in an IFRAME URL, browser history, referer, or KS
  dashboard configuration.
- If cross-origin messaging is required, validate both `event.origin` and a
  narrow message schema; never use unrestricted `postMessage("*", ...)` for
  sensitive data.

## Multi-user Verification

1. Open two independent authenticated browser sessions.
2. Apply different filters with distinct request and idempotency keys.
3. Verify each response is bound to the correct authenticated user.
4. Retry one request and confirm it is not applied twice.
5. Send a stale revision and confirm the service rejects it.
6. Simulate a partial downstream failure and confirm reconciliation exposes or
   repairs the incomplete operation.
