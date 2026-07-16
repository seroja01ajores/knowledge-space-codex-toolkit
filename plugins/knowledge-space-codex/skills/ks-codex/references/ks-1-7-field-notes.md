# KS 1.7 Field Notes

Use this reference when practical KS behavior matters more than endpoint shape. These notes summarize internal field knowledge cards for KS 1.7 and are portable: they do not contain stand URLs, project UUIDs, credentials, tokens, or server-specific assumptions.

Treat these notes as operational guidance. For exact API payloads, still use OpenAPI, UI network capture, and scratch-project verification.

## Dictionaries And Mappings

- For dictionary loads through integrations, prefer enabling case sensitivity. If case sensitivity is disabled, dictionary values can be loaded in lower case and may create duplicates or integration errors.
- Use dictionary mappings mainly for table-based manual data input where the indicator explicitly has "Use mapping table" enabled.
- Avoid dictionary mappings when a process needs to recreate dictionary elements. Cleanup and re-binding can duplicate mappings or leave stale links.
- To update dictionary mappings in bulk, use a full export/edit/import cycle or an integration action designed for dictionary mapping updates. Synchronize the whole mapping set so stale links do not remain.

## Integration Data Safety

- Be careful with any integration setting that deletes user-created objects. It can remove model/imported objects and make tables lose indicator values. Use it only after confirming object recreation rules and table dependencies.
- Apostrophes in source values can break integration loads. Preprocess source data to remove or escape apostrophes, and warn the customer/source owner about the limitation.
- When source rows disappear, old KS values are not necessarily cleared. Send explicit `0` or `NULL` rows for combinations that must be cleared, or load from a dedicated cleanup table before loading current data.
- If a full rebuild is acceptable, "delete all objects" style integration behavior can help, but it must be explicitly confirmed because it changes data broadly.

## Integration Design

- Prefer modular integrations for new work. Sequential integrations can be maintained temporarily, but do not develop new complex scenarios on them when modular integration is available.
- Avoid copying modular integrations as a routine build method. After copying, deleting, adding, or reordering actions, visually unchanged actions may start failing.
- If a modular integration action fails after structural changes, recreate actions starting from the problematic step instead of trying to patch only visible fields.
- For PostgreSQL views feeding integrations:
  - use `INNER JOIN` only when rows must exist in both sources;
  - use `LEFT JOIN` when the left table is the required base and joined data is optional;
  - avoid `FULL JOIN` for integration feeds unless thoroughly tested because it can produce unexpected missing-side rows;
  - prefer `UNION ALL` when combining tables with the same structure.

## Integration Tables On Interfaces

To auto-refresh an integration table from an interface:

1. Create an integration variable, often a technical dictionary element.
2. Enable auto-refresh on the integration table.
3. Add the variable to integration parameters and mark it as obtainable from an event.
4. On the dashboard, add a virtual cell or control that sends the entity.
5. Connect it to the integration table's incoming event.

Use a harmless technical dictionary element for the event payload when the value itself is only a refresh trigger.

## Tables And Interface Layout

- For tables shown in dashboards, enable automatic width adjustment in the table/cell style settings when the table must fill the available width.
- Table coloring can be configured in the table's own style settings, not only in the dashboard cell. Ensure the "apply settings" toggle is enabled, otherwise colors may not render.
- To show row totals, add "Value" into rows, place the relevant object or class under it, and set consolidation to "always consolidate" where applicable.
- To hide an object from a navigator without deleting it, add a status/visibility indicator, assign visibility values through a table, and filter the navigator to show only visible objects.

## Buttons, Logging, And Microservice Bridges

- Button logging can be implemented through a business process: initiate event, create/update a log object, fill indicators, then display the log table.
- If no formal business process is needed, button logging can be implemented by creating a log object and updating its indicators directly through dashboard actions.
- A microservice embedded in an iframe can trigger a KS dashboard button through a controlled `postMessage` bridge. Use this only when the user explicitly needs microservice-to-interface behavior.
- For iframe button bridges, the target button must be visible and reliably identifiable by exact text or a stable marker. Test in browser; do not assume the bridge works from API configuration alone.

## Formula And Model Design

- Choose formula type deliberately:
  - normal formulas recalculate continuously;
  - default formulas are for initial values when an object/value is created;
  - validation formulas are for user input constraints and correction/prevention at input time.
- If an indicator has multiple formulas, execution order matters. Later/lower formulas can overwrite earlier results.
- Avoid heavy functions such as `СУММЕСЛИ`, `ПОИСК`, and `КОНСЕСЛИ` on large classes, especially around 1000+ objects. Prefer explicit relations, database preparation, or alternative calculation logic.
- When using `СУММЕСЛИ`, `ПОИСК`, or `КОНСЕСЛИ` with values pulled through relations or external sources, use consolidation type "Array" for the pulled indicators.
- Test formulas one by one in an isolated model or scratch project. Do not accumulate many formula changes before running model checks.

## Backup Discipline

- Before stand updates or global setting changes, export/backup affected projects. Past KS updates have caused white-screen outages, so project backups are part of safe operational workflow.
- This does not mean an agent may perform backup restore/import automatically. Restore/import remains a dangerous operation and needs explicit user confirmation.
