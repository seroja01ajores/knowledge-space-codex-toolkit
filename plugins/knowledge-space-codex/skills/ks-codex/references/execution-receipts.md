# Execution Receipts

Use an execution receipt after the existing safe-patch or approved-runtime
executor has produced its JSON report. The receipt is a compact evidence
artifact for verification, handoff and learning.

It is deliberately not an executor. It does not call KS, classify a new
payload, carry approval, authorize a retry, or replace the original report.

## Build

For a project-write or read-only report:

    python scripts/ks_execution_receipt.py build --plan-root /safe/work --plan patch-plan.json --execution-root /safe/work/safe-execution --report execution_report.json --output-root /safe/work --output execution-receipt.json

For an approved runtime report, use runtime_execution_report.json from its
execution root.

The builder verifies:

- report mode, stand and project against the plan;
- exact operation coverage without duplicates;
- endpoint and risk against the original operation;
- recognized report secrets;
- every reported artifact path remains under the execution root;
- artifact bytes and SHA-256;
- boolean validity of machine read-back checks.

The resulting receipt stores only compact operation states, issue counts,
verification states and artifact descriptors. It hashes the stand instead of
copying it.

## Validate

    python scripts/ks_execution_receipt.py validate --input-root /safe/work --input execution-receipt.json

Validation checks the receipt hash and its no-authorization boundary.

## Status Meaning

- dry-run: the executor made no live call.
- dry-run-with-findings: no live call and the plan had lint blockers.
- completed: every operation ended in an executed terminal state.
- incomplete: execution was requested but at least one operation did not
  complete.
- effect-unknown: a request may have applied without a usable response.

Never retry effect-unknown automatically. Perform only the already-declared
best-effort read-back, resolve the actual state and request fresh approval if a
new effect is needed.

## Relationship To Handoff And Learning

A task handoff may reference the receipt by relative path and SHA-256. A
knowledge card may use the receipt hash as normalized evidence. Neither use
inherits the original approval.

Keep executor reports and response artifacts private. Only a synthetic,
stand-agnostic receipt pattern may enter public plugin documentation.

Read execution-receipt.schema.json for the generated contract. The existing
safe-patch and approved-runtime tools remain the only authorities for their
respective execution boundaries.
