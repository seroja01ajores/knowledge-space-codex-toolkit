# KS Relationship Normalization

Use this reference when converting KS class records into a user-facing
Diagramm graph or explaining why raw relationship-record counts exceed visible
edges.

## Semantic Edge vs Technical Closure

A verified KS backup represented each real class relationship with three
relationship-related records:

1. one visible semantic relationship;
2. one source-side helper relationship;
3. one destination-side helper relationship.

Therefore 24 relationship-related records can correctly normalize to 8 solid
structural edges. Do not render all three records as independent user-facing
relationships.

The `3:1` ratio is observed evidence, not a safe counting algorithm. Normalize
through the relation/helper closure, source and destination class bindings, and
the source-bound bridge map. Stop if helper closure is missing, duplicated, or
ambiguous.

## Diagram Rules

- Render one solid edge per semantic KS relationship.
- Preserve direction from the semantic source and destination classes.
- Keep helper UUIDs in evidence/bridge data, not visible graph edges.
- Never infer identity from relationship names alone.
- Reject duplicate semantic endpoints unless the source actually contains
  distinct relationships and their bridge identities remain separate.
- Validate relation counts before and after conversion.

When building a new relationship in the current `structural-v0.1` profile,
preserve the existing golden expectation: one class plus one relationship adds
the exact class, semantic relationship, helper, tree, and L10n closure expected
by the target profile. Do not simplify the packed KS structure merely because
the Diagramm view has one edge.

## Formula Dependencies Are Not Structural Relations

Cross-class formula references describe analytical dependencies, not KS class
relationships. Do not merge them into the solid structural edge set.

If users need them, add an optional read-only layer:

- dashed or otherwise visually distinct edges;
- a separate edge type and legend;
- formula/indicator provenance in the evidence sidecar;
- no mapping from these edges to relationship create/update operations.

A verified project contained 19 formulas spanning 12 directed inter-class
dependency pairs while its structural model still contained only 8 semantic
relationships. Keep both counts explicit.

## Validation Checklist

1. Count ordinary classes separately from relationship/helper records.
2. Resolve every semantic relationship to exactly one source and destination.
3. Verify complete helper closure without rendering helpers.
4. Compare visible solid-edge count with semantic relationship count.
5. Keep formula-dependency edges disabled by default.
6. Re-import the Diagramm JSON and verify edges visually; schema validation
   alone is not sufficient.
