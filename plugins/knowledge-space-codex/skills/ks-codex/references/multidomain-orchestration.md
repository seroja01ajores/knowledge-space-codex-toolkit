# Coordinated KS Work

Load this reference only when a KS task needs dependent phases, separate
approvals, a handoff, a resume boundary, or an explicit audit trail.

## Responsibility Split

- Codex interprets the user's request and selects capability and operation IDs.
- capability-index.json describes available operations, dependencies, resources,
  risks, outputs, and verification.
- ks_capability_plan.py validates structured selections and expands read-before
  dependencies. It does not interpret natural language or call KS.
- The safe patch linter and approved executors remain authoritative for actual
  endpoint, payload, business-effect, and approval classification.
- Private knowledge retrieval supplies evidence only and never grants
  permission.

## Minimal Flow

1. Run the catalog command only when the compact map in SKILL.md is
   insufficient.
2. Select every required capability and operation. Do not impose a numeric
   domain limit.
3. Create a request conforming to capability-request.schema.json.
4. Validate it into a planning-only task plan.
5. Work phase by phase and retain compact UUID-bound task state.
6. Re-plan with parentPlanSha256 when evidence changes the working set.
7. Execute only through the existing safety path and exact approval.
8. Verify API state and material browser behavior separately.
9. When useful, prepare a redacted private candidate card after verification.

## Commands

Catalog:

    python3 scripts/ks_capability_plan.py catalog

Describe one area:

    python3 scripts/ks_capability_plan.py describe --capability dashboard-ui

Validate a structured request:

    python3 scripts/ks_capability_plan.py validate \
      --input-root /safe/work/root \
      --input capability-request.json

Add output-root and output only when a saved plan is required. Generated plans
must stay outside the plugin directory.

## Discovery Boundary

Do not invent a capability ID for an unknown task. Use the Discovery workflow
from SKILL.md until read-only evidence identifies the actual KS entities and
effects. Then select existing IDs or record a capability gap for later review.

## Context Discipline

- Keep the whole selected area set visible as IDs and state.
- Load detailed references only for the current phase.
- Run scripts for outputs without loading their source unless modifying them.
- Preserve verified facts, unknowns, contradictions, approvals, prohibited
  effects, artifacts, and verification status.
- Do not persist credentials, raw customer data, raw captures, or request prose
  in the plan.
