# Round-trip Contract

## Artifact Graph

Use a three-way patch, never a blind conversion from the edited diagram:

```text
source KS backup
  -> either unpacked record array + metadata report -> structural slice
  -> or exact-frame packed stream -> structural slice + metadata report
  -> run manifest with relative paths + SHA-256
structural source records
  -> normalized baseline
  -> baseline Diagramm JSON + bridge map
packed source -> separate sanitized read model
read model + structural baseline + bridge
  -> enriched Diagramm review JSON + read-only sidecar + validation report
structural source + baseline Diagramm + edited Diagramm + bridge map
  -> source-bound dry-run change plan
source KS records + exact hashed plan + exact deferred-path acceptance
  -> cloned clean records
  -> validation
  -> zstd frame + raw metadata tail + pack report
run manifest + all stage artifacts
  -> baseline/final bundle-validation report
```

The source records preserve unknown KS fields. The Diagramm file owns visual and
analytical intent. The bridge owns KS entity/tree/helper identity and provenance.
The run manifest binds paths and hashes across stages. The plan is build input,
not merely a human-readable preview.

## Versioned Formats

- Plugin and offline CLI release: `0.3.0`; this is independent from artifact
  format versions and is stored as run-manifest `toolVersion`.
- Diagramm output: `schemaVersion: "1.2"`. A fully hash-bound legacy bundle
  may still be read with `1.1`; do not mix schema versions inside one bundle or
  silently migrate a reviewed artifact.
- Bridge: `format: "teamvalue.ks-diagram-bridge-map"`, `formatVersion: "0.1"`.
- Plan: `format: "teamvalue.ks-diagram-change-plan"`, `formatVersion: "0.1"`.
- Run manifest: `format: "teamvalue.ks-diagram-run-manifest"`,
  `formatVersion: "0.1"`.
- Bundle validation: `format: "teamvalue.ks-diagram-bundle-validation"`,
  `formatVersion: "0.1"`.
- Mapping profile: `structural-v0.1`.
- Separate read-only enrichment profile: `diagram-read-v0.2`, format
  `teamvalue.ks-diagram-read-model`. It is not a mapping/write profile.

Reject unknown versions. Do not silently migrate them during a run.

## Separate Diagram Read Model

`slice-packed-read-model` streams the same immutable packed source but produces
an independent, non-restorable enrichment artifact. It deliberately has no
`--manifest` option: it must never replace or extend the `structural-v0.1`
source lineage, `structuralSource`, `cleanOutput`, or packed restore payload.

The read model selects:

- the complete `structural-v0.1` selection;
- `class/indicator`, `indicatorL10n`, `indicatorUnitL10n`,
  `indicatorDimension`, `formula`, and `formulaElement`;
- `class/tree` where `Data.type=indicator`;
- only sanitized provenance records for `integrator/integration`,
  `integrationOperation`, and `integrationRelation`.

The streaming pass also derives `classStats` for every selected KS class UUID.
It counts `object/object` records by `Data.classUuid` without selecting any
object record or value. Stats keep these meanings distinct:

- `ksIndicatorCount`: every native KS indicator owned by the class UUID;
- `displayIndicatorCount`: indicators displayed as Diagramm metrics;
- `derivedFormulaCount`: exactly equal to `displayIndicatorCount` by the
  constructor UX rule;
- `actualFormulaRecordCount`: physical selected `class/formula` records;
- `activeRegularFormulaRecordCount` and `actualCalculatedIndicatorCount`:
  source evidence, never aliases of the derived count.

The aggregate must contain explicit zeroes for selected class UUIDs with no
objects or indicators. The sum of all `objectCount` values plus unresolved
owner counts must equal source `object/object`; validation recomputes every
indicator/formula field from selected records and rejects a changed derived
count. A downstream Diagramm mapper may copy `objectCount` only through the
bridge UUID map and must not add semantic-relation or helper counts to ordinary
classes.

`classStats.objectCountDigest` is source-bound integrity evidence for the
distribution. Its fields are `algorithm=sha256`,
`canonicalization=teamvalue.object-count-distribution-v1`, the lowercase packed
`sourceBackupSha256`, and the resulting lowercase `sha256`. Canonicalize UTF-8
JSON with sorted object keys and separators `,` and `:` over this payload:

```json
{
  "sourceBackupSha256": "<packed-backup-sha256>",
  "byKsEntityUuid": [["<sorted-class-uuid>", 0]],
  "unresolvedObjectOwnerCounts": [["<sorted-owner-uuid>", 1]]
}
```

The two arrays are sorted by UUID and include explicit zeroes for selected
classes. Validation must compare the digest's source hash to
`readModel.source.sha256`, recompute the digest, and reject redistributed counts
even when their total is unchanged. Keep the external metadata report and
verify its whole-read-model SHA-256 for protection against an actor rewriting
both counts and their public digest. Streaming aggregation fails closed above
100,000 unique nonempty `object/object.Data.classUuid` owners; this bound is
reported as `streamingLimits.maxObjectClassUuids`.

Integration records are projected through an explicit wrapper/Data-field
allowlist. Never retain connection parameters, integration sources, API
settings/templates, authentication, passwords, headers, certificates,
`customQuery`, options/settings, request bodies, variable records or values, or
unknown integration fields. The safe provenance is sufficient to link an
indicator-shaped `internalField` through `integrationRelation.operationUuid` to
its operation/integration without retaining executable configuration.

Validation requires one project, the full structural graph, unique selected
UUIDs, indicator owners, indicator-tree ancestry to the owner class/relation,
indicator L10n/unit/dimension reference closure, formula owner/indicator
closure, formula-element formula references, and idempotent integration
sanitization. When `classStats` is present, validation also requires the exact
selected class UUID set, nonnegative counts, the object-count total, and the
source-bound object-distribution digest plus derived/actual formula invariants.
A missing indicator L10n is reported as a warning because KS can
fall back to the indicator record name.

Every read-model envelope and report keeps `readOnly: true`,
`restorePayload: false`, and `liveRestoreBlocked: true`. Generic KS
restore/build/pack loaders reject this format. The dedicated
`ks_diagram_enrich.py` mapper validates these flags, the selected record
closure, the class-statistics digest, source/project binding, and bridge IDs
before it creates a Diagramm `1.2` review model. It maps every KS indicator,
uses `sourceConfig.presentationRole=attribute` for non-numeric indicators,
copies per-class `objectCount`, preserves actual formula evidence separately
from the constructor's derived formula count, and writes the complete formula
records only to a read-only sidecar.

The enriched review model and sidecar are deliberately outside the structural
run manifest and never replace `structuralSource`, `cleanOutput`, or a restore
payload. Preserve the exact enriched baseline next to the edited export. Before
the ordinary structural `diff`, use the mapper's structural projection command
to verify that existing read-only indicators, KS properties, and object counts
were not changed and to remove those display-only fields. Never feed a
read-model envelope or sidecar to `build` or `pack`.

## Run Manifest

Store `run-manifest.json` inside the dedicated run directory. Every artifact
path is relative to the manifest directory; reject absolute paths, `..` escapes,
symlink escapes, duplicate logical roles, and input/output path collisions.

The manifest records at minimum:

- manifest format/version, tool version, mapping profile, and run ID;
- original backup path, size, and byte SHA-256 when a packed source exists;
- either the decoded record array, or `sourceAcquisition: packed-stream` with
  the original packed source and hash-bound metadata report;
- structural slice path, SHA-256, allowlist profile, and source linkage;
- normalized baseline, baseline Diagramm, bridge, and their SHA-256 values;
- edited Diagramm and source-bound plan path/SHA-256 when created;
- cloned clean records, structural validation, and build report hashes;
- packed backup and pack report hashes;
- the exact deferred paths accepted for the build;
- an offline live-restore state that remains `blocked`.

Commands safely merge or upsert only the artifact roles they own. Repeating a
command with identical content is idempotent. A conflicting existing path,
hash, profile, model ID, run ID, or source lineage is a hard error; never silently
rewrite earlier provenance.

For `packed-stream`, the source backup, metadata report, and structural slice
are the only acquisition artifacts. The command must validate the raw tail,
feed exactly the zstd-frame byte range (never the tail) through a bounded pipe,
validate the full top-level JSON array and zstd checksum, and retain only the
allowlisted project/class/classL10n/folderL10n/class-or-folder-tree records.
Class records include visible relations and helpers, and their nested unknown
fields remain unchanged. Bundle validation must bind the packed hash, byte
counts, source record count, slice hash, profile, and live-restore block.

## Identity Rules

- Existing Diagramm class IDs map explicitly to KS class entity and tree UUIDs.
- Existing relationship IDs map explicitly to the visible relation-class,
  relation tree node, both endpoint classes, and both helper relation UUIDs.
- New Diagramm IDs receive deterministic output UUIDs and are written to the
  output bridge/report.
- A name is display data, not identity. Duplicate names are warnings; name-only
  matching is forbidden.
- Bind a restored target only from post-restore read-back because KS remaps UUIDs
  when restoring into a new project.

## Change Classes

- `candidate`: supported create intent.
- `local-only`: canvas/layout or Diagramm metadata with no KS write.
- `deferred`: understood edit without a confirmed mapping in this profile.
- `blocked_destructive`: delete or other high-risk edit outside the profile.
- `hard error`: invalid model, bridge, source, or KS graph.

Each repeated `--accept-deferred-path PATH` acknowledges only that exact path in
the exact reviewed plan and means its value remains Diagramm-only. Reject
wildcards, prefixes, unknown paths, duplicate/conflicting acceptance, accepted
paths absent from the plan, and any deferred plan path left unaccepted. The flag
must not create placeholder indicators, objects, fields, formulas, or notes.

Relationship type, direction, and cardinality are semantic deferred fields, not
canvas-only changes. Class position/size and model frames/viewport are
`local-only`.

## Source-bound Plan and Build

`diff --source --manifest` hashes the actual structural source along with
baseline Diagramm, edited Diagramm, and bridge, then upserts the edited/plan
artifacts in the manifest. A build-ready plan contains all four hashes, the model
ID, bridge format/profile, target mode, operations, exact deferred paths, and
policy result. A plan missing any required hash is preview-only and cannot be
built.

`build --plan --manifest` must verify the plan file and recompute every bound
artifact hash before evaluating operations. It must reject a changed source,
baseline, edited Diagramm, bridge, plan profile, model ID, write policy, or
operation payload. The build report records the plan SHA-256 and the exact
accepted deferred-path set, and the command upserts clean output/build report
entries in the manifest. Never substitute a newly recomputed unreviewed plan for
the supplied plan.

## Golden Structural Create

One ordinary class plus one semantic relationship produces eight top-level
records:

1. ordinary class;
2. ordinary classL10n;
3. ordinary class tree node;
4. visible relation-class;
5. relation classL10n;
6. relation tree node;
7. source helper relation-class;
8. destination helper relation-class.

Nested relation copies are added to the new source class, visible relation, and
existing target class. The existing target class is the only expected mutation
when the source class is new and the target already exists.

The visible relation's wrapper `ParentRelationUUID` follows its chosen tree
placement; it is not universally the source or destination. Helpers have no own
tree/L10n records. The visible relation tree/L10n records are mandatory.

## Backup Packaging

The clean payload is a JSON array. Compress it as one zstd frame, then append the
metadata tail outside the frame:

```text
%backup_metadata_size=104%<base64>
```

The decoded compact JSON is:

```json
{"projectUuid":"00000000-0000-0000-0000-000000000000","isFileCompressed":true}
```

`validate --manifest` upserts the clean structural-validation report.
`pack --report --manifest` then validates the clean input, writes the zstd frame
and raw tail, and reads the packed output back. It must rediscover and split the
tail, decompress the frame, parse the JSON array, compare its canonical content
to the clean input, and rerun structural invariants. The report records
input/output hashes, byte sizes, zstd/tail details, and the read-back validation
result; the command upserts packed output/report entries in the manifest. File
extension is not proof of compression.

## Bundle Validation

`validate-bundle --manifest run-manifest.json --report ...` resolves artifacts
only through manifest-relative paths and recomputes their byte SHA-256 values.
At the baseline stage it verifies source lineage, manifest integrity, normalized
baseline, Diagramm schema/model ID, bridge version/profile, mapping completeness,
and source/baseline/bridge hash agreement.

At the final stage it additionally verifies edited Diagramm and plan hashes,
exact deferred acceptance, plan-to-build binding, clean-record validation,
expected mutation/addition counts, pack-report hashes, raw-tail/zstd read-back,
and that no earlier artifact changed. Missing required roles, stale reports,
unexpected extra writes, or any mismatch make the report invalid and exit
nonzero.

For compatibility, `--manifest` may be optional on isolated `diff`, `build`,
`validate`, and `pack` calls. It is mandatory in the complete workflow. An
artifact produced without manifest upsert cannot satisfy final bundle validation.

Bundle validation proves offline artifact coherence only. Its report must keep
`liveRestoreBlocked: true`; it is not a restore preflight or approval token.

## Live Restore Boundary

The offline CLI ends after final bundle validation. It has no upload, restore,
access-change, recalculation, cleanup, or delete command. A separate executor may
perform a new-project restore only after the exact `approved_destructive`
preflight in `safe-restore-readback.md`. No offline artifact or flag can clear
the live-restore block.

## Determinism and Audit

Record source SHA-256, baseline semantic hash, edited Diagramm SHA-256, plan
SHA-256, clean output SHA-256, packed output SHA-256, tool version, mapping
profile, timestamp, and exact accepted deferred paths. Semantic hashes exclude
machine-specific absolute paths and mutable run-directory provenance. Repeating
the same synthetic fixture with the same timestamp/ID policy must yield the same
semantic result from any run-directory path.
