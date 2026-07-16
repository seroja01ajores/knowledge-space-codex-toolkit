---
name: ks-diagram-roundtrip
description: "Use when unpacking or slicing Knowledge Space project backups, converting structural records to Diagramm JSON, reviewing edits as a source-bound change plan, building and validating a cloned structural KS backup, or preparing a separate exact-approved scratch-restore preflight and read-back."
metadata:
  short-description: Manifest-bound offline KS Diagramm round-trip
---

# KS Diagram Round-trip

Use this skill for the offline pipeline `KS backup -> unpack/slice -> Diagramm
JSON -> source-bound plan -> validated cloned KS backup`. Keep the Diagramm
model, bridge sidecar, source records, and run manifest together. Never map
existing entities by name alone.

## Safety Boundary

- Treat source backups as sensitive. Do not commit real project names, UUIDs,
  hashes, records, objects, data, integrations, files, or credentials.
- Work on a copy. Never edit the exported backup in place.
- Default to `structural-v0.1`: new classes, including their names and
  descriptions, and new semantic relationships only. Updates to existing class
  descriptions remain deferred. Report every unsupported field as `deferred`.
- `objectCount` is read-derived; never create or delete KS objects from it.
- `unpack`, `slice`, `slice-packed`, `slice-packed-read-model`,
  `validate-bundle`, `from-ks`, `diff`, `build`, `validate`, and `pack` are
  local-only commands. They never upload, restore, call a KS API, or authorize
  another tool to do so.
- Offline conversion does not authorize a live restore. Every offline plan,
  manifest, bundle report, and packed backup remains live-restore blocked.
- Server-side backup export/creation is `approved_runtime`. Local offline
  packing is not a server action. Restore/import is
  `approved_destructive` and requires a separate exact preflight and approval
  for the stand, authenticated user, packed hash, restore options, and target.
- Restore only as a new scratch project, current-user access only, model
  recalculation off. Never overwrite a work or template project.

Read `references/roundtrip-contract.md` before building or reviewing artifacts.
Read `references/supported-fields.md` before deciding whether a Diagramm field
can become a KS write. Read `references/safe-restore-readback.md` before any live
upload or restore.

## Workflow

1. Create a dedicated local run directory and copy the source backup into it.
   Never use an exported backup as an output path.
2. For an ordinary packed backup with proven disk headroom, run `unpack` and
   then `slice`. For a large backup or an unknown decompressed size, run
   `slice-packed` instead: it feeds only the exact zstd frame through a bounded
   pipe and writes no full decoded business-data array. If the input is already
   a clean JSON record array, use `slice` directly.
3. Require an allowlisted structural record array. Both slice paths drop
   nonstructural top-level record types while preserving every unknown field
   inside selected class, relation/helper, tree, and L10n records. Never print
   business rows.
4. Run `from-ks --manifest` to create:
   - baseline Diagramm JSON;
   - bridge map;
   - normalized structural baseline.
   To enrich the Diagramm view with all KS indicators and formula provenance,
   run `slice-packed-read-model` separately against the immutable packed source.
   Its `diagram-read-v0.2` output is read-only, sanitized, has no structural run
   manifest, and is rejected by restore/build/pack input loaders. During the
   same bounded pass it may retain only per-class object counts and class-level
   indicator/formula aggregates; never retain an object record, name, or value.
   The sorted object-count distribution is protected by a SHA-256 digest bound
   to `source.sha256`; reject a missing or mismatched binding.
5. Run `validate-bundle` and require a valid baseline-stage report before giving
   the Diagramm JSON to the user.
6. Preserve the source slice, normalized baseline, baseline Diagramm, bridge,
   and manifest entries unchanged while the user edits and exports
   a second Diagramm JSON.
7. Run `diff --source --manifest`. Review hard errors, create candidates,
   local-only fields, deferred fields, updates, deletes, source hash, and all
   other artifact hashes in the generated plan.
8. Run `build --plan --manifest` only against the exact artifacts hashed by
   that plan.
   Copy each accepted Diagramm-only path from the reviewed plan into its own
   repeated `--accept-deferred-path` argument. Reject missing, extra, stale, or
   wildcard acceptance; exact acceptance never enables a hidden KS mapping.
9. Run `validate --manifest` on the cloned clean record array.
10. Run `pack --report --manifest` only after validation. `pack` must read back
    its own output by splitting the tail, decompressing, parsing, and validating
    it.
11. Run `validate-bundle` again and require a valid final-stage report covering
    every manifest artifact and hash.
12. Stop. Live upload/restore is outside this offline CLI and stays blocked
    until the separate exact `approved_destructive` preflight in
    `references/safe-restore-readback.md` is satisfied.

## CLI

The bundled `scripts/ks_diagram_roundtrip.py` is offline and uses only Python's
standard library plus the local `zstd` executable for unpacking and packing.
The required CLI contract is:

```bash
# Large/unknown decompressed size: use this instead of unpack + slice.
python3 scripts/ks_diagram_roundtrip.py slice-packed \
  --input source.backup \
  --output structural-records.json \
  --metadata-output source.metadata.json \
  --manifest run-manifest.json

# Separate read-only source for indicator/formula Diagramm enrichment.
# This has deliberately no --manifest option and is not a restore payload.
python3 scripts/ks_diagram_roundtrip.py slice-packed-read-model \
  --input source.backup \
  --output diagram-read-model.json \
  --metadata-output diagram-read-model.metadata.json

# Ordinary-size alternative with proven disk headroom.
python3 scripts/ks_diagram_roundtrip.py unpack \
  --input source.backup \
  --output source.records.json \
  --metadata-output source.metadata.json \
  --manifest run-manifest.json

python3 scripts/ks_diagram_roundtrip.py slice \
  --input source.records.json \
  --output structural-records.json \
  --manifest run-manifest.json

python3 scripts/ks_diagram_roundtrip.py from-ks \
  --input structural-records.json \
  --diagram baseline.diagram.json \
  --bridge baseline.bridge.json \
  --baseline baseline.normalized.json \
  --manifest run-manifest.json

python3 scripts/ks_diagram_roundtrip.py validate-bundle \
  --manifest run-manifest.json \
  --report baseline.bundle-validation.json

python3 scripts/ks_diagram_roundtrip.py diff \
  --source structural-records.json \
  --baseline baseline.diagram.json \
  --edited edited.diagram.json \
  --bridge baseline.bridge.json \
  --output change-plan.json \
  --manifest run-manifest.json

python3 scripts/ks_diagram_roundtrip.py build \
  --input structural-records.json \
  --baseline baseline.diagram.json \
  --edited edited.diagram.json \
  --bridge baseline.bridge.json \
  --plan change-plan.json \
  --output cloned.clean.json \
  --report build-report.json \
  --manifest run-manifest.json \
  --accept-deferred-path '<exact-path-from-change-plan>' \
  --accept-deferred-path '<another-exact-path-from-change-plan>'

python3 scripts/ks_diagram_roundtrip.py validate \
  --input cloned.clean.json \
  --output validation.json \
  --manifest run-manifest.json

python3 scripts/ks_diagram_roundtrip.py pack \
  --input cloned.clean.json \
  --output cloned.backup.json \
  --report pack-report.json \
  --manifest run-manifest.json

python3 scripts/ks_diagram_roundtrip.py validate-bundle \
  --manifest run-manifest.json \
  --report final.bundle-validation.json
```

Run the script with `--help` and the selected subcommand with `--help` before
first use. Exit nonzero on hard validation errors. Do not bypass a failure by
editing the report.

Omit `--accept-deferred-path` when the plan contains no deferred paths. Otherwise
repeat it once per exact path copied from the reviewed plan. In
`structural-v0.1`, relationship type/direction/cardinality and any attributes or
indicators remain Diagramm-only, so a relationship create normally requires
explicit path-by-path acknowledgement.

The downstream `--manifest` flags on `diff`, `build`, `validate`, and `pack` may
remain optional for compatibility with isolated command use, but they are
required in this complete safe workflow; omitting one leaves the final bundle
incomplete and `validate-bundle` must fail.

The manifest is JSON stored inside the run directory. Artifact paths are
relative to the manifest directory. Each stage safely merges or upserts only its
own artifact entries and SHA-256 values; it must reject an attempt to replace a
previously recorded path or hash with conflicting content. See the round-trip
contract for required fields and bundle validation rules.

## Enriched Diagramm View

After producing the immutable structural layout, use the separate sanitized
`diagram-read-v0.2` source to build the user-facing Diagramm schema 1.2 model:

```bash
python3 scripts/ks_diagram_enrich.py build \
  --source diagram-read-model.json \
  --stats-source diagram-read-model.json \
  --layout baseline.diagram.json \
  --bridge baseline.bridge.json \
  --output enriched.diagram.json \
  --sidecar enriched.evidence.json \
  --report enriched.build-report.json

python3 scripts/ks_diagram_enrich.py validate \
  --source diagram-read-model.json \
  --stats-source diagram-read-model.json \
  --layout baseline.diagram.json \
  --bridge baseline.bridge.json \
  --model enriched.diagram.json \
  --sidecar enriched.evidence.json \
  --output enriched.validation.json
```

The mapper presents non-numeric KS indicators as KS fields/attributes, numeric
and calculated indicators as indicators, formula provenance in the sidecar,
and source-bound per-class object counts without retaining object names or
values. The Diagramm product metric `formulaCount` equals the displayed
indicator count; actual KS formula-record and calculated-indicator counts stay
separate in `ksProperties`/evidence so the UI metric is not mistaken for a KS
write instruction.

Before structural diff, remove unchanged read-only enrichment while preserving
user-created structural edits:

```bash
python3 scripts/ks_diagram_enrich.py project-structural-edits \
  --structural-baseline baseline.diagram.json \
  --enriched-baseline enriched.diagram.json \
  --edited edited.enriched.diagram.json \
  --bridge baseline.bridge.json \
  --output edited.structural.diagram.json \
  --report structural-projection-report.json
```

Only `edited.structural.diagram.json` proceeds to the manifest-bound `diff`.
Never feed the enriched read model or evidence sidecar directly into
`build`/`pack` as KS records.

`slice-packed-read-model` uses the separate `diagram-read-v0.2` profile. It
retains structural records plus indicator, indicator L10n/unit/dimension,
formula, formula-element, and indicator-tree records. It includes only
sanitized `integrator/integration`, `integrationOperation`, and
`integrationRelation` provenance. Connection parameters, API settings and
templates, authentication, passwords, queries, request bodies, variables, and
all unallowlisted integration fields are excluded. `object/object` is counted
only by `Data.classUuid`; object records and values remain excluded. The
`classStats` aggregate keeps `derivedFormulaCount = displayIndicatorCount`
separate from actual KS formula-record and calculated-indicator counts. The
stream fails closed if unique object owner UUIDs exceed the documented bound.
The object-count digest covers explicit zeroes and unresolved owners and is
bound to the packed source SHA-256. The
output and metadata both
state `readOnly: true`, `restorePayload: false`, and
`liveRestoreBlocked: true`.

## Required Artifact Set

Keep these files per run:

- immutable original-backup checksum and run manifest;
- either a decoded record array plus metadata report, or a packed-stream
  metadata report bound to the original backup hash and structural slice;
- clean allowlisted structural records;
- slice profile/allowlist evidence;
- normalized baseline;
- baseline Diagramm JSON;
- bridge map;
- edited Diagramm JSON;
- source-bound dry-run change plan and its SHA-256;
- exact accepted deferred paths;
- cloned clean records;
- structural validation and build reports;
- packed backup, pack report, and packed-backup checksum;
- baseline and final bundle-validation reports;
- optional live restore read-back.
- optional separate read-only Diagramm enrichment model and its hash/count
  report; never register either as `structuralSource` or `cleanOutput`.

Use synthetic fixtures for tests. A golden create of one class plus one relation
must add exactly eight top-level records and mutate only the expected existing
target class's nested `Data.relations`.

## Stop Conditions

Stop the current offline stage when:

- manifest format, schema, bridge version/profile, model ID, source hash, plan
  hash, or any recorded artifact hash does not match;
- IDs are duplicated or an endpoint cannot be resolved;
- a Diagramm read model loses an indicator owner/tree/formula closure, contains
  non-allowlisted integration data, or changes any read-only/restore-block flag;
- helper/tree/L10n closure is broken;
- an existing entity was updated or deleted under `structural-v0.1`;
- a deferred path is unaccepted, accepted more broadly than its exact plan path,
  or acceptance does not match the plan being built;
- baseline-stage or final-stage bundle validation fails;
- packed-backup self-validation fails.

A valid final bundle ends the offline workflow. Always stop before live restore
until a separate exact `approved_destructive` preflight fixes and verifies the
stand, authenticated user, new-project target, access mode, recalculation mode,
packed SHA-256, and approval snapshot. Stop again if restore read-back fails.
