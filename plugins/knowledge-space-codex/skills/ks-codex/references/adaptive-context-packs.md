# Adaptive Context Packs

Use this reference for Coordinated work that spans dependent phases, several
KS areas, an unfamiliar capability, or a resumable handoff.

The objective is progressive disclosure without knowledge loss:

- Codex sees the compact capability catalog and chooses every relevant area.
- The planner expands prerequisites and read-before operations.
- A phase pack names only the references and scripts needed now.
- Completed work is reduced to evidence and a new pack is built for the next
  phase.
- The complete plugin remains available; nothing is deleted or hidden behind a
  fixed area count.

The planner and packer do not interpret user language, call KS, or authorize an
effect. Codex performs semantic selection. Existing safe-patch, runtime, and
server-maintenance gates remain authoritative for actual execution.

## No Area Limit

The request schema requires at least one capability but defines no maximum.
Dependencies can expand the selection further. The generated task plan and
every context pack report areaLimit as null.

Do not split or omit a real dependency merely to make a smaller plan. Context
is reduced by loading one phase at a time, not by limiting the number of
domains represented in the complete plan.

## Lifecycle

1. Inspect an exact supplied card or run one focused search when an explicit
   private knowledge root is available. Resolve at most one selected full
   recipe by ID and SHA-256 before broad current-state reads.
2. Print the compact catalog only when the map in SKILL.md is insufficient.
3. Let Codex select capability and operation IDs semantically.
4. Validate the structured request into a task plan outside the plugin. A
   requested retrieval phase precedes `read-current-state` and narrows its
   target, dependencies, and preconditions. The planner uses `bind` or
   `read-target` operations for exact read-before dependencies when available;
   it does not silently substitute an area or project audit.
5. Build a context pack for the current phase.
6. Read only the listed references. Execute a listed script without reading its
   source unless the task is to modify or diagnose that script.
7. Classify the real endpoint, payload, channel, and expected effect before any
   action.
8. Retain UUID-bound facts, unknowns, approvals, artifacts, and verification
   status.
9. Rebuild the pack when evidence changes or execution moves to another phase.

Example commands:

    python scripts/ks_capability_plan.py catalog

    python scripts/ks_capability_plan.py validate --input-root /safe/work --input capability-request.json --output-root /safe/work --output task-plan.json

    python scripts/ks_capability_plan.py pack --input-root /safe/work --input task-plan.json --phase-id read-current-state --output-root /safe/work --output context-pack.json

Output roots must stay outside the plugin so generated plans, evidence, and
private state never enter a portable public bundle.

## Context Pack Contract

A teamvalue.ks-context-pack version 1.0 contains:

- planSha256 and requestSha256 for lineage;
- current phase position, objective, capabilities, gates, and expected outputs;
- reference and script paths with byte size and SHA-256;
- a default action for each resource;
- next phase IDs without loading their details;
- the reduced handoff policy;
- planning-only safety fields copied from the task plan.

Reference and script contents are deliberately absent. Hashes detect a resource
change between planning and use; they are not signatures and do not grant
trust or permission.

The pack is a context manifest, not an executor. A plan or pack with
executionAuthorized set to true, liveKsCalled set to true, an unavailable
resource, a duplicate phase, or a recognized secret representation is rejected.

## Unknown Tasks

When no supplied, private, bundled, or exact-project known path applies and no
stable capability covers the request, use capability-discovery.
Select only the evidence channels actually needed:

- inspect-api for API map, OpenAPI, project scope, and observed endpoint
  behavior;
- inspect-ui-network for redacted official UI request chains and browser
  behavior;
- inspect-server-readonly only after API and UI evidence are insufficient and
  explicit server access approval exists;
- record-gap after the useful result and safety boundary are understood.

Combine discovery operations with all known capabilities involved. There is no
one-area or five-area ceiling.

Discovery must stop when enough evidence exists to switch to Direct or
Coordinated execution. It must not invent an endpoint, infer permission from a
similar task, or turn private evidence into public plugin knowledge. Missing
credentials, network, or approval pause the task and do not prove a capability
gap.

## Resume And Handoff

Use parentPlanSha256 when a later structured request continues an earlier plan.
The hash proves lineage to the supplied bytes, not that earlier execution
succeeded.

A compact handoff should contain:

- target stand and project UUID status, without credentials;
- verified UUID-bound facts;
- unknowns and contradictions;
- exact approvals and prohibited effects;
- generated artifact paths and hashes;
- completed and pending verification;
- the next phase ID.

Discard raw responses after extracting required evidence unless the user
explicitly needs a private artifact. Never persist tokens, passwords, customer
data, raw backups, HAR files, or screenshots in a task plan or context pack.

## Learning Boundary

An unfamiliar solution may produce a private candidate card, but retrieval and
learning remain separate from execution authority. Promotion requires
independent evidence and sanitization. Read self-learning.md for the complete
candidate, review, promotion, freshness, and public-release boundary.

For cross-task continuation, prepare and validate a compact handoff with
scripts/ks_task_handoff.py. Read task-handoff.md and
task-handoff.schema.json before defining or consuming that artifact.
