# Safe Subagent Orchestration

Use this reference only when independent work can materially shorten a
Coordinated or Discovery task. Delegation is an optimization, not a default
step, and never expands permissions.

## Select one route first

The coordinator resolves or exhausts known paths before delegating broad work.
Every subagent receives the same selected route, target boundary, effect class,
and verification contract. Do not ask several agents to independently
"explore the stand and invent a solution."

Use these modes:

- **Fast Direct:** no subagents.
- **Coordinated Parallel Read:** one or two independent read-only checks after
  the route is selected, only when their latency exceeds delegation overhead.
  Split by independent areas or evidence channels, such as dashboard
  structure, integration contract, and passive browser evidence.
- **Discovery:** assign one explicit hypothesis or probe to each agent after
  known paths are exhausted.

Do not parallelize sequential dependencies, competing patches to one entity,
active runtime UI actions, or repeated versions of the same investigation.

## One writer

For one KS project and execution phase, designate exactly one `writer_owner`.
All other agents are `no_write` by default.

Only the writer may:

- build the final payload or approved patch plan;
- execute a project write, rollback, integration, BPMS action, recalculation,
  destructive operation, or server action;
- perform an active browser click that can trigger a business effect.

Readers may perform only explicitly scoped read-only calls and passive browser
inspection. Parallel KS writes are forbidden. A verifier reports mismatch but
does not repair it independently.

Transfer writer ownership only after the original writer has stopped, current
live state is reconciled, and the handoff names the new owner. An uncertain
mutation blocks every further effect until read-back resolves it.

## Probe ledger

Before launching a read-only probe, reserve a key:

`project UUID + capability + endpoint family + entity UUID + discriminator`

Record the assigned actor, hypothesis, disproof condition, and status. Do not
repeat an occupied or completed key unless the coordinator explicitly requests
an independent verification. Cancel unnecessary probes as soon as one route is
confirmed.

If results conflict, nobody writes. Compare target UUIDs, timestamps, hashes,
and evidence sources, then run one minimal disambiguation probe. Pause if the
conflict remains.

## Minimal handoff packet

Give each reader only:

- observable outcome and selected card/resource ID plus hash;
- stand alias, project UUID, target UUID, and allowed endpoint family;
- coordinator, assignee, allowed effect, approval state, `writer_owner`, and
  explicit `no_write`;
- completed read hashes/timestamps and known contradictions;
- one probe key, hypothesis, and stop condition;
- required output and verification contract.

Exclude credentials, raw customer data, full snapshots, and unrelated prior
conversation. A useful result contains UUID-bound facts, evidence, one
blocker/contradiction if present, and at most one proposed next probe.

## Verification

The coordinator reconciles all read results before the writer acts. After a
write, an independent reader may verify API or passive browser state, but only
after the writer has completed and the mutation result is known.

For regression testing or a high-assurance handoff, normalize the action order
and run `scripts/ks_workflow_trace.py`. Declare the supplied card and hash,
initial mode, coordinator, writer, a project/target/area-bound audit request,
the exact candidate reference and card SHA-256, and probe keys. A card read must
match the latest successful card resolution exactly, and a supplied-card route
may be resolved only once. Card aliases with the same SHA-256 are the same
revision, not a refinement. After a compatible route, do not search again
unless a bound contradiction or risk signal reopens selection. A failed target,
dependency, or read-back probe reopens it only when the candidate revision,
project, target, and operation when declared match the compatible route.
Any later resolution result or compatibility result invalidates an earlier
exhaustion. The latest lookup immediately before exhaustion must be conclusive;
enter Discovery only after a fresh conclusive refinement, exhaustion, and the
latest successful exact project/target bind.

A delegated read binds one `allowedAction`, one `endpointFamily`, and one
deterministic absolute `endpointPrefix`. Its result must retain that candidate
revision, project, target, area when present, probe, endpoint family, and mode
epoch, and must name an absolute endpoint beginning with the reserved prefix.
Before any mutation uses delegated evidence, the coordinator records a
successful `probe.reconcile` for the latest reader result. Only the latest exact
reconciliation counts; a later blocked, failed, or unknown reconciliation
invalidates an earlier success.

Record project/target-bound `mode.enter` events both when entering Discovery
and before leaving it. Bind each project write to the fresh ordered chain
compatibility -> target read -> dry-run digest -> write -> latest read-back; a
later failed event invalidates an earlier success. A write cannot reuse a
target read made before any prior mutation on the same project and target, and
the prior project write needs a successful exact read-back before the next
target read. The same candidate revision, operation, project, and target may be
mutated only once; changing the endpoint or request digest does not authorize a
retry.

For read-only server inspection, record API and UI probes, then the bound
`api-ui-insufficient` signal, then an exact `approval.server-readonly` event,
and only then the server read, all in the same Discovery epoch and on the same
project, target, and area when present. Only the latest exact API probe, UI
probe, and insufficiency signal count, and each must be successful. The
approval and server read must also share the exact endpoint and request digest.
This trace event records that the external approval was checked; the offline
validator does not create or extend that approval. Bind runtime approval,
execution, and verification or waiver to the same candidate revision, target,
operation, endpoint, and request digest.

The validator checks workflow policy only. `policyValid` does not prove task
completion, live compatibility, expected business behavior, or browser
acceptance, and it never authorizes execution. Routine Fast Direct tasks do not
need to create or persist a trace.
