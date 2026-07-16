# Course And Scratch Project Workflows

Use this reference when recreating, completing, or checking a KS training
project from an assignment, course document, sanitized reference map, or backup.
It is a portable workflow: discover every UUID and stand-specific enum from the
target environment.

## Isolation Rules

- Treat course templates and reference projects as read-only.
- Build only in a named scratch/training project selected by the user.
- Confirm the authenticated user, project UUID, and target name before writes.
- Do not copy credentials, source hosts, project UUIDs, or access lists from a
  reference backup.
- Compare structure read-only first. Run integrations, BPMS, recalculation,
  import/export, and source connection checks only through an exact-approved
  runtime plan.
- Verify project access separately; never inherit or broaden access merely
  because a reference project has it.

## Inputs And Evidence

Prefer this evidence order:

1. current assignment/course document;
2. target-stand Swagger/OpenAPI and UI-observed payloads;
3. sanitized map or read-only snapshot of the expected project;
4. aggregate inspection of a reference backup;
5. browser observation in a disposable project when payload shape is unclear.

Record expected entities by stable role and dependency, not by copied UUID.
When a course document and an older backup disagree, report the difference
before choosing which one to reproduce.

## Build Order

Build and verify one layer at a time:

1. **Project context**: target project, locale, current user, requested access.
2. **Dictionaries**: lists, elements, time/currency/type dimensions.
3. **Semantic model**: models, datasets, classes, relation classes, indicators,
   formula definitions, and tree placement.
4. **Objects and values**: create/import in dependency order; then relation
   objects and dimensional values.
5. **Tables**: model/dataset binding, rows, columns, filters, relation paths,
   display settings, and data availability.
6. **Interfaces**: cells, layout, tables, widgets, charts, filters, buttons,
   nested dashboards, modals, object cards, and Gantt.
7. **Events**: selected object/dataset/dictionary values, filter propagation,
   nested-dashboard placement, and modal open/close behavior.
8. **Application**: publication tree, visible dashboards, hidden modal
   dashboards, navigation, and explicitly requested access.
9. **Integrations/BPMS**: configuration parity first; runtime only after exact
   approval and with read-back.
10. **Acceptance**: API comparison plus browser checks of every interactive
    path required by the assignment.

Never create downstream UI entities before their model/table dependencies are
resolved. Never treat a successful create response as completion without
re-reading the entity and its containing tree.

## Base Modeling Pattern

A common planning course uses:

- one planning model with plan/fact/common datasets;
- work, equipment, personnel, technical, and consolidating classes;
- assignment relation classes from resources to work;
- start/end, quantity, rate/price, cost, revenue, profit, progress, and limit
  indicators;
- type dictionaries and time dimensions;
- planning, cost-estimation, work-analytics, and finance-analytics interfaces;
- finance tables/charts, a Gantt view, filters, object cards, and summary
  widgets;
- one publication containing the required interfaces.

Use these as roles, not guaranteed names. Read the assignment before deciding
which indicators are shared across datasets, dimensional, calculated, or
loaded. For formulas, inspect the target version's token/AST contract; never
turn a display formula string directly into a KS write.

## Advanced Interface Pattern

For dimensional currency/resource exercises:

- create one value per object, dataset, and dictionary element where required;
- verify relation direction before creating assignment objects or button
  events;
- use relation-aware table paths for resources assigned to a selected work;
- keep nested resource dashboards large enough for selector, controls, and
  detail table;
- store a Gantt-selected work in a variable and apply the same selection to
  modal tables;
- include modal dashboards as hidden publication nodes;
- verify a leaf task, not only a parent/group row, when checking calculated
  values.

Read `advanced-course-patterns.md` for payload and browser details.

## Integration Course Pattern

Reconstruct integration exercises in two passes:

1. configuration parity: source placeholder, integration direction,
   operations and order, field rules, conditions, model/dataset/class targets,
   integration tables, BPMS task settings, and publication/UI wiring;
2. exact-approved runtime: source credentials supplied outside plan JSON,
   connection check or selected run, expected external effect, and machine-
   evaluated read-back.

Do not run a reference/template integration to prove configuration parity.
Read `integrations-course-build-spec.md` for the detailed educational pattern
and `integrations-patterns.md` / `bpms-patterns.md` for portable API rules.

## Parity Report

Report each expected item as:

```text
role | expected dependency/path | actual UUID/name | status | evidence
```

Use statuses `present`, `missing`, `different`, `unverified-ui`, or
`runtime-not-approved`. Include at least:

- models/datasets/classes/relations/indicators/formulas;
- dictionaries and elements;
- object/data completeness evidence;
- tables and broken references;
- dashboards, cell layout, events, Gantt, nested/modal flows;
- publication nodes;
- integration/BPMS configuration and runtime state;
- API read-back and browser acceptance results.

Call the course complete only when the requested structure exists, read-back
matches, required UI flows work, and every intentionally unrun runtime action
is clearly marked.
