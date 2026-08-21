# KS Diagram round-trip command guide

Load this reference only when executing or reviewing round-trip commands,
manifest behavior, bounded packed slicing, or the enriched Diagramm view. The
skill entrypoint contains the always-required safety boundary, workflow,
artifact set, and stop conditions.

## Structural CLI

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

Omit `--accept-deferred-path` when the plan contains no deferred paths.
Otherwise repeat it once per exact path copied from the reviewed plan. In
`structural-v0.1`, relationship type, direction, cardinality, and any attributes
or indicators remain Diagramm-only, so a relationship create normally requires
explicit path-by-path acknowledgement.

The downstream `--manifest` flags on `diff`, `build`, `validate`, and `pack` may
remain optional for compatibility with isolated command use, but they are
required in the complete safe workflow. Omitting one leaves the final bundle
incomplete and `validate-bundle` must fail.

The manifest is JSON stored inside the run directory. Artifact paths are
relative to the manifest directory. Each stage safely merges or upserts only
its own artifact entries and SHA-256 values. It must reject an attempt to
replace a previously recorded path or hash with conflicting content. Read
`roundtrip-contract.md` for required fields and bundle validation rules.

## Enriched Diagramm view

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

The mapper presents non-numeric KS indicators as KS fields or attributes,
numeric and calculated indicators as indicators, formula provenance in the
sidecar, and source-bound per-class object counts without retaining object
names or values. The Diagramm product metric `formulaCount` equals the
displayed indicator count. Actual KS formula-record and calculated-indicator
counts stay separate in `ksProperties` and evidence so the UI metric is not
mistaken for a KS write instruction.

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
Never feed the enriched read model or evidence sidecar directly into `build` or
`pack` as KS records.

## Enriched read-model boundary

`slice-packed-read-model` uses the separate `diagram-read-v0.2` profile. It
retains structural records plus indicator, indicator L10n, unit, dimension,
formula, formula-element, and indicator-tree records. It includes only
sanitized `integrator/integration`, `integrationOperation`, and
`integrationRelation` provenance.

Connection parameters, API settings and templates, authentication, passwords,
queries, request bodies, variables, and all unallowlisted integration fields
are excluded. `object/object` is counted only by `Data.classUuid`; object
records and values remain excluded.

The `classStats` aggregate keeps
`derivedFormulaCount = displayIndicatorCount` separate from actual KS
formula-record and calculated-indicator counts. The stream fails closed if
unique object owner UUIDs exceed the documented bound. The object-count digest
covers explicit zeroes and unresolved owners and is bound to the packed source
SHA-256.

The output and metadata both state `readOnly: true`,
`restorePayload: false`, and `liveRestoreBlocked: true`.
