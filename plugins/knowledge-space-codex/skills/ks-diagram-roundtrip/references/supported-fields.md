# Supported Fields

## Confirmed Mapping

| Diagramm field | KS backup/API representation | structural-v0.1 |
| --- | --- | --- |
| class name | class record + classL10n | create |
| class description | `class.Data.description` and description status | create |
| relationship endpoints | visible relation-class `relatedSourceUuid` and `relatedDestinationUuid` | create |
| relationship name | visible relation-class + classL10n | create |
| relationship description | visible relation-class description | create |
| position, size, frames, viewport | no KS write | local-only |

The relationship is itself a KS class record. Its two helpers connect source to
the visible relation and the visible relation to destination. Preserve all
wrapper, nested, tree, and L10n references.

For source-read compatibility, a complete legacy helper pair in the reversed
orientation (`R -> source` and `target -> R`) is accepted and mapped by endpoint
side without rewriting the source records. Existing self-relationships with a
complete `class -> R` / `R -> class` helper pair are also readable. Both variants
emit explicit source warnings in Diagramm, normalized, and bridge artifacts.
Creating a new self-relationship remains forbidden in `structural-v0.1`.

## Confirmed Read-only Semantics

- `objectCount` is derived from KS objects. It is not class metadata and must
  never create, clone, or delete objects. Count only top-level
  `Group=object, Type=object` by `Data.classUuid`; do not count `objectModel`,
  `objectL10n`, dataset rows, or `autoCreated` subsets. Map counts to Diagramm
  classes only through bridge UUIDs, never names. Verify the sorted distribution
  through `classStats.objectCountDigest`, bound to the packed
  `source.sha256`; the stream fails closed above 100,000 unique object owners.
- A class/relationship indicator is a `Group=class, Type=indicator` record whose
  owner is `Data.classUuid`. Diagramm `indicator.valueType` maps to KS
  `Data.dataType` / API `DataType`, not to KS `Data.valueType`.
- KS indicator `valueType` carries a different consolidation semantic such as
  `none` or `max`; preserve it or use a separately confirmed default.
- An indicator requires a tree node with `type=indicator`; its ancestor chain,
  possibly through folders, must terminate at the owner class/relation-class.
- Calculated indicators also require formula records linked to the indicator and
  owner. A Diagramm formula string is not a KS formula AST.
- KS endpoint limits use `sourceObjectsLimit`, `destinationObjectsLimit`, and
  `objectsLimitInModel`; zero means unlimited.
- `strictRelation` is relation/cascade strength, not Diagramm multiplicity.
- A calculated indicator has both a top-level formula record and an equivalent
  entity embedded in `indicator.Data.formulas`. `hasFormulas` alone is not a
  reliable source of truth.
- `derivedFormulaCount = displayIndicatorCount` is a Diagramm UX aggregate,
  not the number of KS formula records. Preserve `actualFormulaRecordCount`,
  `activeRegularFormulaRecordCount`, and `actualCalculatedIndicatorCount`
  separately; never overwrite per-indicator `sourceConfig.formulaCount`.

## Deferred Profiles

| Diagramm field | Reason |
| --- | --- |
| attributes | no confirmed first-class KS attribute entity; custom fields are not equivalent |
| attribute `required`/notes | no confirmed native field |
| indicators | record shape is known but kind/provenance/formula policy needs a separate profile |
| calculated formula/dependencies | requires KS token/AST generation and validation |
| indicator `loaded` | requires integration provenance, not just an indicator flag |
| relationship type | no native association/dependency/aggregation/etc. field |
| direction `none`/`bidirectional` | no single confirmed KS representation |
| cardinality text | must be normalized and endpoint-limit orientation must be proven in UI/API |
| stereotype/notes | no confirmed portable KS mapping |
| updates/deletes | require multi-record patch, baseline conflict checks, and higher risk gate |

Do not guess. Preserve these values in Diagramm and list them in the plan.
Relationship type, direction, and cardinality are `deferred` for both new and
existing relationships; they are never `local-only`. Only canvas/layout fields
such as position, size, frames, and viewport are local-only in this profile.

## Exact Deferred Acceptance

The plan emits a stable, fully qualified path for every deferred value. To build,
the user or reviewing agent copies each deliberately accepted path verbatim into
its own repeated argument:

```bash
--accept-deferred-path '<exact-path-from-change-plan>'
```

Acceptance is bound to the supplied plan SHA-256 and means only “keep this value
in Diagramm without a KS write.” It never enables a mapping. Reject wildcard or
prefix acceptance, a path absent from the plan, a deferred path omitted from the
accepted set, or reuse of acceptance after the plan/edited Diagramm changes.
Record the exact accepted set in the build report and run manifest.

## Indicator Profile Prerequisites

### Read-only enrichment now available

`diagram-read-v0.2` is an extraction/validation profile, not the deferred KS
write profile described below. The bundled `ks_diagram_enrich.py` uses it to
create a validated Diagramm `1.2` read view and a separate read-only sidecar:

| Read-model content | KS source | Safety treatment |
| --- | --- | --- |
| indicator identity/owner/type/defaults | `class/indicator` | preserved read-only |
| localized names and units | `indicatorL10n`, `indicatorUnitL10n` | preserved read-only |
| dimensions | `indicatorDimension` | preserved read-only |
| indicator placement | `class/tree:type=indicator` | owner ancestry validated |
| calculation provenance | `formula`, `formulaElement`, embedded formula fields | preserved; no Diagramm formula-string claim |
| loaded provenance | `integration`, `integrationOperation`, `integrationRelation` | strict field allowlist; executable/secrets removed |
| class object count | aggregate of `object/object.Data.classUuid` | integer only; object records/values excluded; source-bound distribution digest required |
| derived formula count | displayed indicator count | kept separate from actual KS formula evidence |

The integration read set excludes connection parameters, sources, API
settings/templates, auth, passwords, headers, certificates, queries, bodies,
options/settings, and variable records/values. A mapper may classify a loaded
indicator only from an active `integrationRelation` whose `isIndicator` and
`internalField` link are present and whose operation/integration closure is
available. Never infer `loaded` from an indicator flag alone.

This read profile does not change `structural-v0.1`: indicators, formulas, and
attributes remain deferred for KS writes. The read model is rejected as
`from-ks`/`build`/`pack` source input and always keeps `restorePayload: false`.
Before diffing an export from the enriched constructor view, project it back to
the exact structural baseline. The projection must fail if any existing
`indicators`, `ksProperties`, or `objectCount` changed; it may retain new
classes/relationships and local layout so the ordinary source-bound diff can
review them without treating the entire read-only enrichment as a write.

Before enabling `indicators-v0.2`, verify with synthetic create/export/read-back:

- exact indicator wrapper and `Data` enums;
- class and relation-class ownership;
- L10n/tree requirements if any;
- input vs loaded provenance;
- value type and unit mapping;
- defaults and dimensions;
- formula record closure;
- update/delete behavior;
- browser display after restore.

When cardinality is implemented, KS limits store maxima only. Diagramm minimum
multiplicity must remain in bridge metadata. With canonical `source -> target`
notation, target maximum maps to `sourceObjectsLimit`, source maximum maps to
`destinationObjectsLimit`, and `*` maps to zero. This orientation still needs a
nonzero UI/API round-trip before writes are enabled.
