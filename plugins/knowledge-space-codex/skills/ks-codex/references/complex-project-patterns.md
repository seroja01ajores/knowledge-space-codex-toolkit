# Complex Project Patterns

Use this reference for large planning or forecasting KS projects: many
dashboards, role-based applications, modal flows, large forecast tables,
integrations, and business processes.

## Safety

- Work read-only first. Complex projects often contain hidden buttons that run integrations, recalculate models, start BPMS, export files, or clear data.
- Do not use demo labels as portable implementation names. Preserve business names in the target project, but write portable docs as patterns.
- Do not print raw business datasets, customer lists, source schemas, source hosts, credentials, or personal data from backups.
- Names containing `test`, `delete`, support notes, or personal names are not reliable anchors. Use UUIDs and read-back state.

## Audit Order

1. Identify models, datasets, classes, relation classes, dictionaries, and technical classes.
2. Map dashboards by persona/folder, not only by flat tree order.
3. Map publications/applications and their menu structure.
4. Map integrations and processes, but do not run them.
5. Inspect dashboard events for every prominent button.
6. Verify only read-only navigation and display flows in browser.
7. Keep a list of unsafe buttons/processes that require explicit approval before testing.

## Role-Based Dashboards

Large role-based projects often have a start page with role buttons:

```text
Вход в личный кабинет администратора
Вход в личный кабинет КАМа
Вход в личный кабинет прогнозиста
```

These buttons usually navigate to role dashboards. The role dashboard may initially show a placeholder such as `Выберите пункт меню слева`; that is normal when the real content is chosen from a nested menu/tree.

When auditing:

- enter each persona from the start page;
- expand the matching dashboard folder in the left tree;
- open each child dashboard in view mode;
- distinguish navigation buttons from process/integration buttons;
- verify that menu entries, breadcrumbs, and nested dashboard placement match the intended persona.

## Large Tables And Forecast Views

Large forecast screens can contain wide time-series tables with many hidden columns. Screenshot capture may time out, and visible text can appear blank until the table finishes rendering.

Before marking a dashboard broken:

- wait for table headers and first rows;
- inspect DOM text for table headers/rows;
- check console warnings/errors;
- test horizontal and vertical scroll behavior if visual QA is required;
- confirm cell width settings, fixed headers, and auto-width toggles.

Common forecast view patterns:

- filters by brand/category/series/SKU/distributor/warehouse;
- weekly or monthly time columns;
- enriched/base/promo forecast measures;
- assumption or novelty dashboards;
- buttons for forecast calculation or approval, which are mutating.

## Promo And Assumption Flows

Promo dashboards often combine:

- a promo list table;
- a selected-SKU or selected-distributor detail table;
- buttons like `Создать`, `Выбрать SKU`, `Рассчитать`, `Утвердить`;
- modal dashboards for selection/editing.

Selection/modal buttons can be safe to inspect if they only open a picker. Creation, calculation, approval, and upload buttons should be treated as mutating until their dashboard events prove otherwise.

## Integration And BPMS Shape

Complex demo projects often include:

- input integrations for history, cleaned history, baseline forecasts, enriched forecasts, and promo forecasts;
- output integrations for publishing/sending enriched or promo forecasts;
- modular integration graphs with operation nodes and edge/layout records;
- process tasks for filtering, summing, recalculation, cleanup, or integration runs.

When editing a complex integration:

1. Read the full integration, operations, field rules, relations, conditions, variables, and graph/layout records.
2. Preserve `sourceOperationUuids`, previous-operation edges, operation names, and layout records unless the change explicitly targets them.
3. Prefer creating a disposable copy/scratch project for experiments. Do not patch complex production-style integrations by visual intuition alone.

## Backup Inspection

For large backups, use aggregate inspection:

- count entity types;
- list model/dashboard/integration/process names;
- map dashboard tree paths;
- map integration directions and operation routes;
- inspect source records only enough to identify type/product, with sensitive fields redacted;
- sample at most small metadata slices, not raw business rows.

Keep project-specific table names, schemas, and business data out of portable
examples unless they are explicitly marked as synthetic demo material.

## Browser QA Checklist

- Start page loads and role buttons are visible.
- Each role button navigates to the expected persona shell.
- Persona shell menu entries open dashboards without white screens.
- Large tables show headers and at least one row, or an explicit empty/error state.
- Charts render or show a clear data-empty state.
- Modal/picker buttons open and close without requiring a write.
- Process/integration/export/import buttons are identified but not clicked unless approved.
- Console has no fatal errors for the inspected path; cache warnings alone are not enough to mark failure.
