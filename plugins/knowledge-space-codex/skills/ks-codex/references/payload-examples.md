# Redacted Payload Examples

Use these snippets as portable patterns, not as complete endpoint specs. Replace every placeholder, include `X-Project-UUID`, preserve the surrounding object shape read from the current stand, and read back after each write. For dashboard changes, send the full dashboard object to `/dashboards/update`; do not assume partial cell patches persist.

## Dashboard: Gantt Selected Work Variable

```json
{
  "type": "getObject",
  "tags": "работа",
  "uuids": ["<gantt_cell_uuid>"],
  "action": "save",
  "saveEvents": false,
  "saveGlobalVariableType": "settings",
  "saveGlobalVariableForce": true,
  "useCurrentEntityCellSettings": false
}
```

Use the real Gantt cell UUID. Imported backups can contain `saveValue`/`self`; verify in browser before relying on that pattern.

## Dashboard: Nested Interface Switch

Button event:

```json
{
  "type": "sendEntity",
  "action": "place",
  "sendEntityType": {"value": "dashboard", "entityType": null, "additionalValue": "dashboard"},
  "sendEntityValue": {
    "value": "<target_dashboard_uuid>",
    "entityType": "dashboard",
    "additionalValue": "<target_dashboard_uuid>"
  },
  "sendEntityValueSettings": {"dashboard": {"settings": {}}}
}
```

Nested dashboard placement cell:

```json
{
  "type": "getDashboard",
  "action": "place",
  "uuids": ["<button_cell_uuid>"],
  "saveEvents": false,
  "useCurrentEntityCellSettings": false
}
```

The listener must point to the source button cell, and the placement cell must have visible size.

## Dashboard: Modal Open Button

```json
{
  "type": "showDashboard",
  "title": "<modal_title>",
  "showType": "inWindow",
  "dashboard": {
    "value": "<modal_dashboard_uuid>",
    "entityType": "dashboard",
    "additionalValue": "<modal_dashboard_uuid>"
  },
  "windowSize": {"width": "95", "height": "90", "widthUnit": "%", "heightUnit": "%"},
  "hasIconClose": true,
  "runActionType": "inBackground",
  "useEntityName": true
}
```

When launched from an application, add the modal dashboard to the publication inner tree as hidden.

## Table: Related Resource Rows For Selected Work

Constructor row in `/data-tables/update-constructor-data` or `/data-tables/update` fallback:

```json
{
  "uuid": "<related_objects_class_row_uuid>",
  "fieldType": "relatedObjectsClass",
  "entityType": "object",
  "data": {
    "classUuid": "<resource_class_uuid>",
    "classesPath": ["<assignment_relation_class_uuid>", "<work_class_uuid>"],
    "fullChain": true,
    "hideObjectRelations": false
  }
}
```

Dashboard table listener:

```json
{
  "type": "getObject",
  "tags": "работа",
  "uuids": ["variable"],
  "action": "tableFilterStructure",
  "filter": {
    "tableCellSettings": {
      "fieldUuid": "<related_objects_class_row_uuid>",
      "fieldUuids": [],
      "objectChainPartIndex": 1
    }
  }
}
```

For `resource -> relation -> work`, `objectChainPartIndex: 1` targets the destination work. Verify the visible result: assignment rows must be limited to the selected work.

## Publication: Hidden Modal Dashboard

```json
{
  "publicationUuid": "<publication_uuid>",
  "parentUuid": "<parent_inner_node_uuid>",
  "previousUuid": "<previous_sibling_inner_node_uuid_or_null>",
  "referenceUuid": "<modal_dashboard_uuid>",
  "type": "dashboard",
  "name": "<modal_dashboard_name>",
  "customName": "",
  "isHidden": true,
  "iconUuid": null,
  "iconName": ""
}
```

Read `/publications/get-by-ids` after creation and confirm `parentUuid`, `referenceUuid`, and `isHidden`.

## Integration: Output Sampling Conditions

Create/read one output condition per operation, then filter read-back by `operationUuid` before counting.

```json
{
  "operationUuid": "<send_data_operation_uuid>",
  "indicatorUuid": "<indicator_uuid>",
  "operator": "!=",
  "conditionType": "CONDITION",
  "compareType": "constant",
  "constValue": {"data": 0, "type": "number"},
  "compareIndicatorUuid": "00000000-0000-0000-0000-000000000000"
}
```

The integration course output pattern uses two relevant conditions on the output operation: `IS NOT NULL` and `!= 0`.

## BPMS: Task Runs Integration

```json
{
  "UUID": "<task_uuid>",
  "ProcessUUID": "<process_uuid>",
  "Name": "<task_name>",
  "CompletionCriteria": "run_integration",
  "IntegrationSettings": {
    "IntegrationUUID": "<integration_uuid>",
    "ModelUUID": {"ParamValue": "<model_uuid>", "VariableUUID": null},
    "DatasetUUIDs": {"ParamValue": ["<dataset_uuid>"], "VariableUUID": null}
  }
}
```

Preserve the existing task fields around this excerpt. Read back with `/tasks/get-by-ids`. Updating the task is a project write; starting the process can run the integration and needs separate explicit approval.

## Layout: Align Selected Dashboard Cells

Use a safe patch plan instead of editing cells ad hoc:

```json
{
  "endpoint": "/dashboards/update",
  "entityType": "dashboard",
  "changes": [
    {
      "cellUuid": "<cell_uuid>",
      "before": {"left": 6800, "top": 8850, "width": 3200, "height": 1150},
      "after": {"left": 0, "top": 8850, "width": 3200, "height": 1150},
      "fieldChanges": ["settings.sizeAndContent.left.value"]
    }
  ]
}
```

Build the actual payload by reading the full dashboard and changing only the listed `sizeAndContent` values. Run `ks_dashboard_layout_plan.py` and `ks_safe_patch_lint.py` before execution.

## Comments: Dashboard Description

Dashboard-level analyst comments use top-level `description` on the dashboard object:

```json
{
  "uuid": "<dashboard_uuid>",
  "name": "<existing_name>",
  "description": "Назначение интерфейса: <business purpose>. Перед изменениями проверьте связанные таблицы, события и публикацию.",
  "configuration": "<existing_configuration_unchanged>"
}
```

Read with `/dashboards/get-by-id`, update only `description`, then write the raw dashboard object to `/dashboards/update`. Do not put long comments into visible labels or `settings.name.value`. On tested KS 1.7-style projects, ordinary data table and dashboard cell descriptions were not exposed; keep rationale in the parent dashboard description or external analyst docs unless the stand exposes verified fields.
