# Dashboard Events

KS interfaces are dashboards. The most reliable source is `/dashboards/get-by-id`, field `dashboard.configuration.cells`.

## Important Cell Types

- `gantt`: Gantt chart.
- `table`: data table.
- `WIDGET`: widget list / flat widget list.
- `buttons`: action buttons.
- `dashboard`: nested dashboard/interface.
- `filter`: dataset, dictionary, date, or other filters.
- `NAVIGATOR`: dictionary/object navigator.

## Common Reference Fields

Table cell:

```json
{
  "entity": {
    "type": "table",
    "tableModel": "<model_uuid>",
    "tableTable": "<data_table_uuid>"
  }
}
```

Nested dashboard cell:

```json
{
  "entity": {
    "type": "dashboard",
    "value": {"uuid": "<dashboard_uuid>"}
  }
}
```

Gantt cell:

```json
{
  "entity": {
    "type": "gantt",
    "value": {"uuid": "<gantt_uuid>"},
    "ganttModel": {"uuid": "<model_uuid>"}
  }
}
```

## Action Names

Observed action values include:

- `save`: save incoming entity to global/settings variable on verified KS 1.7 frontend builds.
- `saveValue`: legacy save action still seen in backups; verify before reusing it.
- `transfer`: transfer selected object/entity from a widget or navigator.
- `filter`: filter ordinary object/data table by incoming object.
- `tableFilterStructure`: filter table structure, often for dictionary/dataset/dimension filtering.
- `changeRelationObject`: replace related objects in an object/card cell; do not assume it filters data-table relation chains.
- `place`: place one dashboard into a nested dashboard cell.
- `modal`: open dashboard as modal.
- `showDashboard`: open a dashboard, commonly as a modal/window when paired with `showType`.
- `closeModalInterface`: close the current modal/dashboard window from a button.
- `refresh`: refresh by incoming model/entity.
- `addObject`: create object.
- `deleteObject`: delete selected object.
- `addRelationObject`: create relation object.

## Event Patterns

### Gantt Selected Work To Global Variable

Gantt entity event generation should tag selected task/object, for example `работа`.

Cell incoming event:

```json
{
  "type": "getObject",
  "tags": "работа",
  "uuids": ["<gantt_cell_uuid>"],
  "action": "save",
  "saveGlobalVariableType": "settings",
  "saveGlobalVariableForce": true
}
```

On one verified KS 1.7 frontend, `uuids: ["self"]` did not match the Gantt select event; the listener needed the real Gantt cell UUID. Imported backups with `action: "saveValue"` should be migrated only after browser/API verification on the target stand.

### Open Modal From Gantt Control

Gantt `iconsElements[*].events` in older projects often use:

```json
{
  "type": "getDashboard",
  "action": "modal",
  "dashboard": {"uuid": "<modal_dashboard_uuid>"},
  "width": 900,
  "height": 650
}
```

The modal dashboard must also be included in the publication/application, usually hidden.

Current KS frontend button actions are more reliable with `showDashboard` than `getDashboard` + `modal`. Imported backups can contain button events shaped as `{"type":"getDashboard","action":"modal"}`; those can render a button but not open the modal. Migrate button-triggered modal opening to:

```json
{
  "type": "showDashboard",
  "dashboard": {
    "entityType": "dashboard",
    "value": "<modal_dashboard_uuid>",
    "additionalValue": "<modal_dashboard_uuid>"
  },
  "showType": "inWindow",
  "windowSize": {
    "width": "95",
    "widthUnit": "%",
    "height": "90",
    "heightUnit": "%"
  },
  "useEntityName": true,
  "hasIconClose": true,
  "runActionType": "inBackground"
}
```

Keep an explicit close button inside the modal:

```json
{
  "type": "closeModalInterface",
  "action": "closeModalInterface"
}
```

Do not rely on Esc or backdrop click as the only close path.

### Widget Filters Ordinary Table

Widget emits selected resource:

```json
{
  "type": "getObject",
  "tags": "оборудование",
  "action": "transfer"
}
```

Ordinary object table receives it:

```json
{
  "type": "getObject",
  "tags": "оборудование",
  "action": "filter"
}
```

### Table Selector Fallback

When a widget list renders blank and a regular table is used as the selector, the table must emit click events explicitly:

```json
{
  "entity": {
    "type": "table",
    "clickEventSettings": {
      "tags": "оборудование",
      "tableEventTypes": ["getObject", "getDataset", "getDictionaryElement"],
      "tableEventsCell": true,
      "tableEventsHeader": true
    }
  }
}
```

Downstream tables or button cells then listen to that selector cell UUID with the same tag. Without `clickEventSettings`, a table may display rows but never transfer the selected object to filters, delete actions, or relation-creation buttons.

### Selected Work Filters Related-Object Table

For modal assignment tables built as `resource -> relation class -> work`, use a class-based related-object row and a structure filter. The row field should look like:

```json
{
  "fieldType": "relatedObjectsClass",
  "data": {
    "classUuid": "<resource_class_uuid>",
    "classesPath": ["<assignment_relation_class_uuid>", "<work_class_uuid>"],
    "fullChain": true,
    "hideObjectRelations": false
  }
}
```

Then the table cell listens to the selected-work variable:

```json
{
  "type": "getObject",
  "tags": "работа",
  "uuids": ["variable"],
  "action": "tableFilterStructure",
  "filter": {
    "tableCellSettings": {
      "fieldUuid": "<row_field_uuid>",
      "fieldUuids": [],
      "objectChainPartIndex": 1
    }
  }
}
```

For `resource -> relation -> work`, `objectChainPartIndex: 1` targets the destination work object. `action: "changeRelationObject"` can leave unrelated rows visible in a table; it is not the reliable table-chain filter on verified KS 1.7 frontend builds.

Verify the result in the launched UI. A table can receive the selected work tag and still display all relation rows if the constructor path, event source UUID, tag, or relation direction is wrong. The visible proof is not "selected work is shown somewhere"; it is "assignment rows are limited to that selected work".

If the event listens to the assignment table's own cell UUID, the modal can look correct but fail to filter by the work that was selected before opening the modal.

### Switch Nested Interfaces

On verified KS 1.7 frontend builds, a button that switches a nested dashboard should emit an entity, not use `getDashboard` directly as the button action. Button action:

```json
{
  "type": "sendEntity",
  "action": "place",
  "sendEntityType": {
    "entityType": null,
    "value": "dashboard",
    "additionalValue": "dashboard"
  },
  "sendEntityValue": {
    "entityType": "dashboard",
    "value": "<target_dashboard_uuid>",
    "additionalValue": "<target_dashboard_uuid>"
  }
}
```

The nested dashboard placement cell listens with:

```json
{
  "type": "getDashboard",
  "action": "place",
  "uuids": ["<button_cell_uuid>"]
}
```

The listener `uuids` must include the source button cell UUID. Old backups can contain button events with `type: "getDashboard"` and `action: "place"`; on verified KS 1.7 frontend builds those may only change the active button style and not replace the nested dashboard.

### Add Relation From Selected Work And Selected Resource

Button event:

```json
{
  "type": "addRelationObject",
  "sourceObject": {"tags": "работа", "fromEvent": true, "entityType": "object"},
  "destinationObject": {"tags": "оборудование", "fromEvent": true, "entityType": "object"},
  "relationClass": {"value": "<relation_class_uuid>", "entityType": "class_relation"},
  "model": {"value": "<model_uuid>", "entityType": "model"}
}
```

Use matching resource tag for personnel or another class.

Before saving a relation-creation button, inspect the relation class source and destination. If the relation is `Resource -> Work`, the selected resource must be the source object and the selected work must be the destination object, even if the UI text says "link resource to work".

## Layout

Use `settings.sizeAndContent` for robust cell display:

```json
{
  "top": {"unit": "percents", "value": 0},
  "left": {"unit": "percents", "value": 0},
  "width": {"unit": "percents", "fixed": false, "value": 5000},
  "height": {"unit": "percents", "fixed": false, "value": 3000}
}
```

Avoid overlapping large cells. If the UI shows a white area but API references are valid, inspect layout first.

For button rows, reserve enough height for the configured button pixel height plus padding. A cell can look fine in JSON but clip labels or overlap the next table when the row is too short.

## API-Only Layout Repair

Use this sequence when fixing a dashboard without relying on the browser editor:

1. Read the dashboard with `POST /dashboards/get-by-id`.
2. Unwrap the response from `dashboard`; some endpoints return HTTP 200 with `{"error": ...}`, which must fail the run.
3. Patch the full `dashboard.configuration` object offline. Do not send a tiny partial cell patch unless the endpoint specifically documents that shape.
4. Send the raw dashboard object to `POST /dashboards/update`. Do not wrap it as `{"dashboard": dashboard}`; that can return HTTP 200 but fail to persist.
5. Before `POST /dashboards/update`, print a dry-run summary: dashboard name/UUID, cell count before/after, removed/added cell titles, changed rectangles, and event type/action changes.
6. After update, read the dashboard back and verify by exact title and event:
   - expected cell count;
   - no unintended removed cells;
   - nested switch buttons use `sendEntity` and point at the target dashboards;
   - nested dashboard cells listen with `getDashboard/place`;
   - modal buttons or Gantt controls use `getDashboard/modal` or the deliberately chosen `showDashboard` fallback.
7. Regenerate an offline cell report and diff against the reference or previous snapshot.

When converting a broken nested interface switch, do not leave a hidden `1x1` dashboard cell as a placeholder. Use one visible nested `dashboard` cell for the placement area, make the switch buttons emit `sendEntity` with the target dashboard UUID, and make the nested cell listen for `getDashboard`/`place` from the button cell.

## Browser Walkthrough Checklist

Use this when verifying a built project or learning from a demo/final project through the KS UI.

1. Open dashboards through the tree or publication menu, not only by direct dashboard UUID. The route often needs the real tree node UUID.
2. Launch view mode before judging user-facing behavior.
3. For every screen, classify visible buttons before clicking:
   - navigation or nested-dashboard placement;
   - modal/picker opening;
   - create/update/delete object;
   - BPMS/integration run;
   - import/export/refresh;
   - unknown.
4. Click only navigation and harmless modal/picker buttons during read-only learning. Leave run/export/import/refresh/delete/cleanup buttons untouched without approval.
5. Verify large tables and charts with both visual state and DOM/console state. A screenshot timeout or temporarily blank canvas is not enough to call a dashboard broken.
6. For nested dashboards, confirm the incoming `place`/navigation event and that the nested cell has enough size.
7. For modal dashboards, confirm the hidden/published modal is included in the application and has an explicit close path.
8. If a table displays headers but no rows, check model/dataset/object/filter context before changing layout.

## Risky Button Labels

Treat these labels as likely mutating until dashboard events prove otherwise:

```text
Загрузить
Очистить
Рассчитать
Утвердить
Передача данных
Экспорт
Импорт
Запустить
Обновить
Удалить
```

Treat these labels as usually navigation, but still verify events in critical projects:

```text
Вход в личный кабинет ...
Открыть
Назад
Справочники
Планирование
Аналитика
```
