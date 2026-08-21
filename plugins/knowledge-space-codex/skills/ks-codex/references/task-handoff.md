# Task Handoff And Resume

Use a task handoff when Coordinated work continues in another Codex task,
resumes after approval, or must discard bulky evidence before the next phase.

The handoff is a compact local artifact. It is not a transcript, backup,
credential store, execution request, or proof that an action succeeded.

## What It Preserves

- the task-plan, request, context-pack, state, and handoff hashes;
- completed phase and whether it completed, paused, or became blocked;
- the next legal phase;
- target project UUID confirmation status;
- verified, inferred, missing, and contradicted facts;
- approvals with exact risk, status, and scope;
- relative artifact paths and caller-supplied hashes;
- passed, failed, pending, and explicitly waived verification;
- one concrete next action.

It never embeds raw responses, reference contents, scripts, credentials, or
automatic execution authority.

## Prepare

Create a handoff-state JSON outside the plugin using format
teamvalue.ks-handoff-state version 1.0. Keep facts short and point evidenceRefs
to private receipts or artifacts rather than copying response bodies.

Then run:

    python scripts/ks_task_handoff.py prepare --plan-root /safe/work --plan task-plan.json --state-root /safe/work --state handoff-state.json --output-root /safe/work --output task-handoff.json

For a completed phase, nextPhaseId must be the immediate next plan phase. When
the current phase is partial or blocked, continuation stays on the same phase.
Omit nextPhaseId to let the tool derive the legal value.

The tool rebuilds the completed phase context pack, binds all relevant hashes,
rejects recognized secrets, and writes atomically with owner-only permissions.

## Validate

Before using a handoff from another task or machine:

    python scripts/ks_task_handoff.py validate --input-root /safe/work --input task-handoff.json

Validation checks the handoff hash and its planning-only boundary. Artifact
hashes are recorded assertions; verify important artifact bytes separately
before using them as evidence.

## Bind A Resume Request

Prepare the next structured capability request normally, then bind it to the
validated previous plan:

    python scripts/ks_task_handoff.py bind-request --handoff-root /safe/work --handoff task-handoff.json --request-root /safe/work --request next-request.json --output-root /safe/work --output bound-request.json

The command adds or verifies parentPlanSha256. It does not copy the handoff into
the request, select capabilities, grant an approval, or call KS.

## Efficiency Boundary

Keep the handoff instead of prior raw context. In the resumed task load:

1. the compact skill entrypoint;
2. the validated handoff;
3. the bound request and generated task plan;
4. the current phase context pack;
5. only resources listed by that pack.

Open older private artifacts only when a fact is disputed or verification
requires the original evidence.

## Safety Boundary

- Store handoffs only outside the public plugin.
- Use stand aliases rather than credential-bearing URLs.
- Never place tokens, passwords, cookies, private keys, raw HAR data, customer
  rows, backups, or screenshots in state fields.
- An approved scope does not survive target, payload, endpoint, session, or
  expected-effect changes.
- A handoff can carry an approval record, but the actual executor must still
  enforce its own current gate.
- parentPlanSha256 proves lineage to a plan, not success of its execution.

Read task-handoff.schema.json for the generated artifact contract and
adaptive-context-packs.md for phase selection and context-pack behavior.
