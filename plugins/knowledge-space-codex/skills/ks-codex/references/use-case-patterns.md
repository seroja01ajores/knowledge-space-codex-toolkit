# KS use-case patterns

Use this reference to classify an unfamiliar, product-shaped, or cross-area KS
task without turning user language into a keyword router. Codex interprets the
request. Structured tools validate selected capability and operation IDs,
dependencies, resources, risks, and outputs.

Do not load this file for a routine Direct task whose entity, intended effect,
project, and verification are already clear.

## Decision frame

Describe the task through observable decisions rather than terminology:

1. Outcome: inspect, explain, diagnose, build, change, run, migrate, compare,
   visualize, package, or learn.
2. State owner: browser or tab, KS project, external service, private local
   artifact, global KS state, or server.
3. Scope: one entity, one area, several dependent areas, one project, several
   projects, or several stands.
4. Effect: read only, local artifact write, project write, runtime or external
   effect, destructive or global effect, or server and database maintenance.
5. Evidence: API state, normalized snapshot, official UI network evidence,
   browser behavior, isolated restore, or independently verified knowledge.
6. Completion proof: structural read-back, behavioral browser check, external
   result, parity report, or a clearly stated unverified boundary.
7. Reuse: one-time result, resumable plan, reusable report, deterministic
   helper, private knowledge candidate, or public stand-agnostic pattern.

Choose Direct, Coordinated, or Discovery from those facts. A task can change
mode as evidence develops. Do not limit the number of capability areas.

## Operating patterns

| Situation | Initial mode | Expected result |
| --- | --- | --- |
| Explain or inspect a known entity | Direct | UUID-bound facts and evidence |
| Repair one known project entity | Direct | Dry-run patch, approval, read-back |
| Run integration, BPMS, or recalculation | Coordinated | Exact runtime approval and result verification |
| Diagnose a causal chain across areas | Coordinated | Evidence-labelled dependency chain |
| Build a course or project from a specification | Coordinated | Phased build, reference resolution, browser proof |
| Clone, migrate, restore, or compare projects | Coordinated | Source-bound plan, isolated target, parity report |
| Investigate an unknown component or effect | Discovery | Minimal evidence, capability gap, next safe probe |
| Diagnose a browser-only failure | Direct or Discovery | DOM, console, network, and API boundary |
| Separate simultaneous users or sessions | Coordinated or Discovery | State-ownership model and isolation proof |
| Produce a diagram, lineage, or impact map | Coordinated | Source-linked graph with evidence status |
| Produce a health or compliance report | Coordinated | Prioritized findings and safe repair options |
| Reuse prior experience | Direct or Coordinated | Bounded verified evidence, never authorization |
| Learn from a corrected or novel solution | Coordinated | Redacted private candidate and verification gaps |
| Maintain this plugin or its release | Separate local workflow | Offline artifact, no implicit KS access |
| Change users, roles, global state, server, or DB | Separate gated workflow | Exact target-specific approval |

## Cross-area diagnosis

Build the shortest causal chain that can explain the symptom. Common chains
include:

- external source -> integration operation -> stored model data -> formula ->
  table -> dashboard -> publication -> browser;
- dashboard control -> event payload -> filter or indicator -> data query ->
  cell rendering;
- BPMS task -> data mutation -> recalculation -> dashboard notification;
- backup record -> normalized structure -> cloned project -> API parity ->
  browser parity.

Mark every edge verified, inferred, missing, or contradicted. Do not repair the
last visible component merely because it displays the symptom. A proposed
change must target an edge with evidence of the defect.

Load detailed references only for the current phase. Carry forward UUIDs,
hashes, verified facts, unknowns, approvals, artifacts, and verification state.
Do not carry raw API bodies when a normalized record is sufficient.

## Multi-user and iframe state

An iframe does not create user isolation by itself. Determine which layer owns
every selected filter or URL:

| Layer | Typical lifetime | Isolation question |
| --- | --- | --- |
| Browser tab or iframe bridge | Tab or page session | Is state intentionally per tab? |
| KS project entity or indicator | Project-defined | Is storage actually user-scoped or shared? |
| External microservice | Service session or tenant | Which trusted identity partitions state? |
| URL parameters | Navigation request | Can values leak through history, logs, or referrers? |

Do not assume a project-level KS value is user-scoped. Verify its storage and
read semantics. Do not use a shared mutable project value as the sole carrier
for transient per-user filters when concurrent users can overwrite it.

For a dynamic external page, prefer a stable bridge document as the KS iframe
source:

1. The bridge establishes its own opaque session with the target service.
2. A filter update reaches the bridge through a validated parent message, or
   the bridge reads its session state from a service endpoint.
3. The bridge validates message origin, message type, schema, and session
   binding before changing the child URL.
4. The bridge changes only its nested iframe or application route and returns
   an acknowledgement.
5. The target service stores data by authenticated user, tenant, or opaque
   session key and never trusts a caller-supplied user ID alone.

Cross-origin browser rules prevent KS from directly editing another site's DOM.
Use an explicit message or service contract instead of relying on DOM access.
Never send a KS password, bearer token, source-control credential, or server
credential to the iframe. Prefer a same-site service session. If a bootstrap
token is unavoidable, make it short-lived, audience-bound, one-time, redacted
from logs, and exchange it immediately for an opaque service session.

Useful implementation patterns:

- Parent-to-bridge postMessage for immediate tab-local updates.
- Session endpoint plus polling, SSE, or WebSocket when KS cannot emit a
  suitable event but the bridge can maintain a service session.
- Full iframe URL reload with non-sensitive query values as a compatibility
  fallback.
- Separate KS interfaces only when the content and lifecycle are genuinely
  different, not as a substitute for per-user state.

Isolation is verified only with at least two independent sessions. Confirm that
simultaneous filter changes produce different service requests and responses,
do not overwrite each other, survive the intended navigation lifetime, and do
not expose either session's data to the other.

## Product-shaped outcomes

Prefer composing existing snapshots, auditors, planners, and safe executors
over creating parallel infrastructure.

### Project health report

Collect a read-only snapshot, run focused audits, group findings by causal
area, attach UUID and endpoint evidence, distinguish structural and browser
gaps, and propose lintable repairs. A report is not permission to repair.

### Data lineage and impact map

Trace sources, models, indicators, tables, dashboards, publications, BPMS, and
runtime operations. Each node keeps its source UUID and each edge keeps an
evidence status. For a proposed change, show upstream assumptions and
downstream affected artifacts.

### Interface event diagram

Represent controls, filters, events, target cells, nested interfaces, modals,
iframes, and external messages. Distinguish an API reference from behavior
verified in a browser. This can be generated from dashboard configuration and
enriched with observed event traffic.

### Project parity checker

Compare source and target by stable semantic identity plus UUID maps. Separate
missing entities, changed definitions, changed data, unresolved references,
publication differences, and browser-only differences. Never overwrite a
target merely to make counts match.

### Safe repair pack

Package findings, a dry-run patch plan, required gates, preconditions,
verification checks, rollback information where supported, and unresolved
risks. The pack remains inert until the exact operation is approved.

### Project or course constructor

Compile a specification into dependency-ordered project operations. Reuse
known payload contracts, resolve UUIDs from read-back, and stop on ambiguous
targets. Finish with structural and material browser verification.

### Incident assistant

Start with the observed symptom and identify the earliest disproven edge in the
causal chain. Preserve timestamps and request identifiers where useful. Do not
convert an incident diagnosis into a broad rewrite.

## Discovery contract

When no current area pattern explains the request, produce a compact capability
gap:

- requested observable outcome;
- discovered entities, endpoints, and versions;
- current matching capabilities and missing capability;
- read-only evidence collected;
- rejected hypotheses and contradictions;
- intended effect and highest possible safety gate;
- next minimal probe;
- verification still required;
- whether a private candidate card is justified.

Discovery remains read-only until an actual endpoint, payload, target, effect,
and approval boundary are known. A new user term does not require a vocabulary
entry. Prefer observed structures and effects over adding linguistic rules.

## Learning contract

Search verified or promoted cards only after scope, version, entities, and
effect are known. Use multiple focused passes when different phases require
different evidence; the per-pass result bound is not a task-wide knowledge cap.

Prepare a candidate only when it adds a reusable decision, payload invariant,
diagnostic distinction, compatibility boundary, or safety rule. Preserve
rejected hypotheses so later work does not repeat them. Contradictory verified
patterns remain separate and searchable by version and scope.

Never auto-promote, auto-publish, or let retrieved knowledge grant access or
execution permission. Public knowledge must be synthetic, stand-agnostic,
redacted, and independently reviewed.

## Context and maturity rules

- Routine Direct work should not load this reference.
- Coordinated work loads all required short capability contracts but only the
  current phase's detailed references.
- Discovery expands context incrementally from API map to official UI evidence
  and only then to permitted server diagnostics.
- More capability areas are allowed whenever the causal chain requires them.
- Completed evidence is reduced, not discarded; raw sensitive data is removed
  while hashes, UUIDs, findings, and provenance remain.
- New automation must demonstrate repeated value and a stable safety boundary
  before entering the plugin.
- A successful local parse is not live KS verification. A successful API
  read-back is not browser verification.

The product is mature when representative single-area, multi-area, unknown,
runtime, destructive, session-isolation, offline round-trip, and learning
scenarios have explicit observable outcomes and regression coverage without
loading unrelated knowledge by default.
