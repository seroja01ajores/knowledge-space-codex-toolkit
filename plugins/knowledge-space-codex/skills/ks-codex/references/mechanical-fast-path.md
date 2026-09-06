# Mechanical Fast Path

Use this reference for a small deterministic project-scoped change whose
target, operation, expected delta, and verification are already clear. This is
a short Direct route, not a lower safety class.

## Eligibility

Use the fast path only when all of these are true:

- stand, project, target container, and intended outcome are unambiguous;
- one logical entity changes through one known project-write endpoint;
- the semantic delta is small, deterministic, and reversible from one exact
  read-before;
- the event or payload shape comes from a compatible card, bundled invariant,
  or exact working sibling;
- every direct dependency already exists and resolves to one UUID;
- no architecture, UX, or business-rule choice remains;
- the expected machine read-back and bounded browser check are known;
- the actual effect is a project write, not runtime, external, destructive,
  global, server, or database work.

The number of visible UI elements does not define simplicity. One button that
runs an integration or chains several events is not a Mechanical Fast Path.

## Minimal route

For an exact dashboard UUID and a button with no external dependency:

1. Resolve a known pattern and check only its compatibility requirements.
2. Read the exact dashboard once.
3. Build one local semantic delta while preserving all existing fields and
   UUIDs.
4. Present a micro dry-run: project and target UUID, endpoint, changed field or
   cell, expected effect, read-back check, and rollback source.
5. Use the bundled `KSClient` from `scripts/ks_api_client.py` for the target
   read, write, and read-back, with authentication and project scoping enabled.
   Use `post(..., ok_empty=False)` when the recipe expects a non-empty response.
6. Read the same dashboard once and compare the target plus every non-target
   field that the full payload could have changed.
7. When the UI is material and the action is harmless, perform one bounded
   browser smoke check of the new behavior.

The client handles transport and API errors; effect classification and approval
still follow eligibility and `safe-writes.md`. The same agent owns all three
calls. Do not add a JSON-plan executor merely to repeat these reads.

With an exact target, the normal API budget is two target reads and one write.
One additional exact dependency read is allowed when the recipe names that
dependency. Name resolution may add one list/tree read when the user did not
provide a UUID.

In an optional regression trace, put the concrete reason in `signal` on each
extra read. `efficiencyWarnings` reports repeats beyond one target read, one
read-back, or one dependency read when no reason is recorded; these warnings
are separate from safety-policy violations and do not change approval gates.

Do not run the capability planner, full project snapshot, OpenAPI discovery,
general browser walkthrough, or full dashboard cell report merely because
they are available. Load only the reference needed by the selected operation.

## Verification

Read-back must prove:

- the project and target UUID did not change;
- the expected element exists exactly once;
- label, event, payload, target references, and layout delta match the plan;
- non-target state is canonically unchanged;
- the response contains no `error`, including under HTTP 200.

The browser check should exercise only the new path. If browser access is not
available, report that API configuration is verified but user-facing behavior
remains unverified.

Perform each mutation once. Timeout, an `error` response, an empty unexpected
response, or read-back mismatch ends the fast path as `failed` or
`effect_unknown`; never retry automatically.

## Exit signals

Leave the fast path and choose targeted Coordinated or Discovery work when:

- target, placement, dependency, or intended action is ambiguous;
- the card is stale, version-incompatible, contradicted, or lacks a required
  precondition;
- more than one entity or endpoint must change;
- selected-row state, session/global variables, relation direction, or a
  multi-event chain is not already verified;
- the effect is runtime, external, destructive, global, server, or unknown;
- the first exact read contradicts the recipe;
- write/read-back or browser behavior differs from the expected delta.

An exit signal permits the next necessary audit level; it does not
automatically require a full-project audit.

## Delegation

Do not spawn subagents for a normal Mechanical Fast Path. One agent owns the
route, payload, write, and verification. If an exit signal creates two or more
independent read-only questions, delegation may begin under
`subagent-orchestration.md`; the writer remains unique.
