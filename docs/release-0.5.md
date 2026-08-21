# Knowledge Space Codex Toolkit 0.5 release contract

This document defines what must be true for the public v0.5 line. It is a
stand-agnostic verification contract, not evidence that any live KS stand was
accessed and not permission to execute an operation.

## Product outcome

Codex should retain awareness of the complete KS task while loading only the
detailed material needed for the active phase. The task may involve one area,
any number of dependent areas, or a capability that is not yet represented.
Unknown work starts with Discovery rather than a guessed keyword route. Proven
experience can be reused through a private evidence lifecycle without making
private data public or allowing retrieved knowledge to grant permission.

## Required v0.5 capabilities

| Requirement | Authoritative artifact | Required proof |
| --- | --- | --- |
| No numeric domain limit | Capability request and task-plan schemas | A synthetic plan with at least six directly selected areas remains valid |
| Phase-scoped context | Adaptive context pack | Only active-phase resources are detailed; every included resource and plan has a SHA-256 binding |
| Unknown-task support | Discovery capability and use-case contract | Unknown entity/effect remains read-only and produces a compact gap plus next safe probe |
| Resume without full replay | Task handoff | Validation detects changed plan, context or state hashes and carries no raw response or credential |
| Safe reusable learning | Knowledge card 1.1 and local index | Applicability, freshness, contradictions, supersession and promotion checks are queryable and fail closed |
| Execution evidence | Execution receipt | Plan/report bindings, statuses and artifact hashes are recorded without approval or retry authority |
| Existing write safety | Safe linter and approved executors | Endpoint, payload, target, read-before, approval and read-back regressions remain green |
| Complete comparison evidence | Project diff | Any snapshot collection error blocks missing/extra inference and returns a non-zero status |
| Structural/runtime separation | Dashboard audit | Iframe and other runtime-only evidence is reported separately from structural risks |
| Restore artifact integrity | Backup and restore guidance | Validated compressed input, exact hash, terminal status, access and source-preservation checks are explicit |
| Product usefulness | Use-case patterns | Single-area, multi-area, unknown, iframe, constructor, lineage, health, parity, incident and learning routes remain discoverable |
| Portable public release | Release builder | ZIP contains only the canonical plugin, excludes sensitive artifacts and is deterministic |

## Local release gate

Run from the repository root:

```bash
python3 tools/run_plugin_tests.py
python3 tools/test_build_portable_plugin.py
python3 /path/to/skill-creator/scripts/quick_validate.py plugins/knowledge-space-codex/skills/ks-codex
python3 /path/to/skill-creator/scripts/quick_validate.py plugins/knowledge-space-codex/skills/ks-diagram-roundtrip
python3 tools/build_portable_plugin.py --output-dir dist
```

The local gate proves schema, planner, filesystem, secret, executor, round-trip
and package behavior covered by synthetic tests. It does not prove a live KS
API contract or browser behavior.

## Final real-task matrix

Run these only against an explicitly approved scratch project and approved
test identities. Do not use production customer data.

| Scenario | Minimum evidence |
| --- | --- |
| Direct read-only inspection | UUID-bound API result and normalized snapshot |
| Coordinated multi-area diagnosis | Phase plan, context pack and source-linked causal chain |
| Unknown capability | Discovery gap, observed endpoint/payload and explicit safety classification |
| Narrow project write | Lint, exact approval, read-before, write response, machine read-back and receipt |
| Runtime action | Exact runtime approval, target binding, external result or documented verification waiver |
| Browser-only interface behavior | API state plus DOM, console and network evidence |
| Iframe session isolation | Two independent sessions with non-overwriting requests and responses |
| Incomplete snapshot comparison | Non-zero diff status and no missing/extra conclusions until both snapshots are complete |
| Learning lifecycle | Private candidate, redaction review, independent verification, freshness and supersession behavior |
| Diagram round-trip | Source hashes, structural validation, cloned backup and isolated restore/read-back |

Live restore, global/destructive changes, user/role changes, server maintenance
and database work remain separate target-specific approvals. A local green
build, a generated receipt or a prior knowledge card cannot authorize them.

## Release evidence boundary

A release claim must name which layers were verified:

- local structure and synthetic behavior;
- portable package and checksum;
- scratch-project API behavior;
- browser behavior;
- external runtime result;
- isolated restore read-back.

Missing layers stay explicitly unverified. Success at a lower layer cannot be
used as proof for a higher one.
