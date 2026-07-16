# Advanced Course Patterns

Use this reference when building or auditing the advanced KS course project, or when another project uses the same patterns: dimensional currency indicators, nested resource interfaces, modal resource assignment, Gantt events, and publication setup.

## Scope And Safety

- Work only in the selected project. Confirm `KS_PROJECT_UUID` and the target project name before writes.
- Use official API writes only: `/data/save`, `/dashboards/update`, `/data-tables/update`, `/publications/create-inner-node`, `/publications/update-inner-node`.
- Do not use SSH, database writes, Docker, backup restore, access changes, or server config changes for course/project content.
- For course work, read the course document and any Excel assignment files first; do not infer object names, quantities, or relation directions from UI labels.

## Dimensional Data

For indicators with a dictionary dimension, save one row per dataset/object/indicator/dictionary element:

```json
{
  "ModelUUID": "<model_uuid>",
  "d": "<dataset_uuid>",
  "o": "<object_uuid>",
  "i": "<indicator_uuid>",
  "m": {"<dictionary_uuid>": "<dictionary_element_uuid>"},
  "v": {"type": "number", "data": 12.5}
}
```

Advanced course currency defaults are usually:

```text
Рубль = 1
Лира = 3.5
Юань = 12.5
```

Write currency rates to every dataset shown in tables, not only to `План`, unless the project intentionally uses a hidden/common dataset. Verify by reading all returned rows and mapping `row.m[dictionary_uuid]` back to dictionary element names. Do not trust a `/data/get-list` request to filter dimensions unless you inspect the returned `m` field; some deployments return the first dimensional value when the payload is not exact.

Expected count checks:

```text
resource currency rows = resource_count * dataset_count * currency_element_count
rate rows = dataset_count * currency_element_count
relation currency rows = relation_count * dataset_count * currency_element_count
```

## Relation Direction

Always inspect relation class fields before creating relation objects or button actions:

```text
relatedSourceUuid
relatedDestinationUuid
```

Use the real source/destination direction in `addRelationObject`, even when the course describes a logical parent differently. For example, in the base course project the assignment classes can be `Оборудование -> Работы` and `Персонал -> Работы`; the button must send the selected resource as source and the selected work as destination.

For relation-scoped tables that should show assignments for a selected work, do not use `changeRelationObject` as a shortcut. On verified KS 1.7 frontend builds that action is for object-card relation replacement, while data tables need `tableFilterStructure` with `filter.tableCellSettings`.

Reliable assignment-table constructor:

- row field: `fieldType: "relatedObjectsClass"`;
- `data.classUuid`: resource class (`Оборудование` or `Персонал`);
- `data.classesPath`: `[assignment_relation_class_uuid, work_class_uuid]`;
- `data.fullChain: true`;
- `data.hideObjectRelations: false` when the relation row/name should be visible;
- listener event from the selected-work variable: `type: "getObject"`, `uuids: ["variable"]`, `action: "tableFilterStructure"`;
- listener filter: `tableCellSettings.fieldUuid` is the row field UUID and `objectChainPartIndex: 1` for `resource -> relation -> work`.

Do not validate a selected-work modal only by checking that the selected work card changed. The assignment tables must be filtered to the same selected work. If rows such as `<resource>_<other work>` remain visible after selecting a leaf task, fix the table constructor path or incoming event before calling the modal complete.

## Flat Widget Lists

For nested resource interfaces, prefer explicit name indicators over `valueType: entityName` when object names render blank in a widget list. Do not treat a `WIDGET` JSON config as valid until the launched interface visibly shows object names and real indicator values in the browser.

Minimal reliable widget pattern:

- `entity.type`: `WIDGET`;
- `widgetCommonSettings.entityType`: `objects`;
- `objectsSettings.classUuid`: resource class UUID;
- `objectsSettings.model.modelUuid`: use the model UUID only when the resource objects belong to that model; if objects are standalone reference objects with `modelUuid: null`, a model-bound widget can render a single blank/default card instead of the object collection;
- `listSettings.columns`: `1`;
- `widgetStyles[*].hasScroll`: `true` for long lists;
- first row: explicit name indicator (`Название оборудования`, `Название персонала`);
- second row: price/rate and participation count indicators;
- `widgetEvents`: `{"type":"getObject","action":"transfer","tags":"оборудование"}` or `персонал`.

Then the resource currency table cell receives:

```json
{"type":"getObject", "tags":"оборудование", "action":"filter"}
```

Use matching tags consistently across widget, delete button, relation button, and table filter events.

If the widget renders blank cards, default values such as `0.00`, or only one template card, switch to a visible table selector for the same resource data table before calling the project finished. The table selector should show real resource names/values, keep the create/delete/link buttons above it, and leave the detailed price/rate table below it. Record the widget issue as residual work instead of hiding a blank widget in a production-like handoff.

When using a table selector fallback, preserve the course workflow:

- show `Создать`, `Удалить`, and `Связать с работой` above the selector;
- give the selector table `clickEventSettings` with `tableEventTypes: ["getObject", "getDataset", "getDictionaryElement"]` and the resource tag (`оборудование` or `персонал`);
- make row click transfer the resource tag (`оборудование` or `персонал`);
- use the selected resource tag for delete/link/detail-table filtering;
- keep the detailed currency table visible below the selector;
- state in the handoff that the fallback was chosen because the widget did not render real object names on the tested stand.

## Dashboard Layout

Dashboard cell coordinates are percent-like integers from `0` to `10000`. Before writing a dashboard, check every cell has `settings.sizeAndContent` and no overlaps:

```text
left + width <= 10000
top + height <= 10000
```

For nested dashboards, reserve enough height in the parent cell. A nested resource interface with top buttons, widget list, and table usually needs about half the parent interface height; otherwise buttons and table headers may visually collide even when the API accepts the config.

Recommended advanced main layout shape:

```text
Gantt: full width, top ~43%
Left bottom: switch buttons, then nested dashboard
Right bottom: currency rates table, filters/navigator, modal open button
```

For the planning dashboard, the stable reference pattern is:

- Gantt at the top, opening the resources modal through a Gantt custom icon/control.
- A two-button resource switch row below the Gantt.
- One visible nested `dashboard` cell below the switch row. The switch row uses `getDashboard/place`; do not add separate hidden `1x1` dashboard cells for each resource type.
- Right column with currency table, optional currency filter, and the resources modal button.

Run an API layout check after `/dashboards/update`; browser screenshots are still required for final visual sign-off.

## Gantt And Modal Workflow

Gantt structure on this deployment should be verified with:

```json
{"UUID":"<gantt_uuid>", "ModelUUID":"<model_uuid>", "ShowEmptyTasks": true}
```

For the advanced modal workflow:

- Gantt cell emits selected work with tag `работа` (`selectTask` / `transferObjectsToEvents`).
- The Gantt cell also receives its own object event and saves it as a global/settings variable with `action: save` and tag `работа`. On current deployments the listener `uuids` must include the real Gantt cell UUID, not `"self"`. Older backups may contain `saveValue`; verify against the active frontend before reusing it.
- The modal selected-work widget/table receives the work from the global variable with `uuids: ["variable"]`.
- Related assignment tables receive the same work tag from `uuids: ["variable"]` with `action: tableFilterStructure` and `filter.tableCellSettings`.
- The Gantt custom control opens the modal dashboard with `action: modal`.

If `action: modal` is unreliable, use a button/control with `showDashboard`, `showType: inWindow`, `hasIconClose: true`, and add a visible `Закрыть` button with `closeModalInterface`.

Browser validation recipe:

1. Open the main dashboard through the tree node route.
2. Select a leaf work row in Gantt. Do not use a parent/grouping work as the only analytics check: parent rows can legitimately show zero totals while leaf rows show the calculated costs.
3. Open the resources modal.
4. Confirm the selected-work block shows that exact leaf work.
5. Confirm assigned equipment/personnel rows belong to that selected work only. Virtualized tables may show only the first visible row until scrolled; the key failure signal is unrelated rows for another work.
6. Close the modal through the explicit close button.

## Publication/Application

If a modal dashboard is opened from a published app, it must be present in the publication `innerTree`. Add:

- main dashboard as visible (`isHidden: false`);
- modal dashboard as hidden (`isHidden: true`);
- nested dashboards do not need visible publication nodes, but the referenced dashboards must exist.

Use `/publications/create-inner-node` for missing nodes. Do not change publication access unless the user explicitly asks.

## Completion Checklist

A course project is ready only when all are true:

- Gantt returns the expected task count and has sequence/nesting relation UUIDs.
- Required classes, indicators, dictionaries, relation objects, and assignment quantities exist.
- Currency rates and resource currency values exist for every displayed dataset and currency element.
- Nested resource widgets show names and values, and click filters the related currency table.
- Main dashboard switches between equipment and personnel nested interfaces.
- Analytics dashboards are checked with a leaf Gantt work selected; zero values on a parent/grouping row are not by themselves an interface bug.
- Modal opens from the Gantt control and assignment tables respond to selected work.
- Modal assignment tables show only rows for the selected work, not all relation objects.
- Publication contains the main dashboard and hidden modal dashboard.
- Dashboard API layout has no overlapping cells.
- Browser refresh/screenshot confirms there are no blank blocks, stale cache, or clipped controls.
