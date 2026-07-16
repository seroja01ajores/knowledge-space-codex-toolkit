# Integrations Patterns

Use this reference for KS integration-course work and for projects that use `Интеграции`, `Источники`, or `Интеграционные таблицы`.

## Safety

- Integrations can call external systems, mutate project data, and store secrets. Default to read-only until the user explicitly authorizes a run or connection change.
- Never print source passwords, connection strings, API tokens, cookies, CSRF tokens, or JWTs.
- Do not run `/integrator/integrate`, `/integrator/connect`, `/integrator/check-connection`, password updates, deletes, or global source changes unless the user requested that exact action and the target project/source is confirmed.
- Do not run `/integrator/integrate-modular`, `/integration-table/refresh-data`, `/integration-table/update-data`, `/integration-table/export-data`, or dashboard buttons that send/export/load integration data unless explicitly approved.
- Opening an integration or integration table in the UI can automatically fetch source metadata and display connection errors. Treat those messages as observations, not as permission to test or fix the source.
- When learning from a final/demo integration project, inspect it read-only first and recreate only inside a new educational project.
- When the user intentionally asks to run/check/refresh/export an integration, use the approved-runtime flow: create a JSON plan with `metadata.mode=approved_runtime`, exact operation approval, target project UUID, expected effect, and read-back/verification or a documented waiver; then execute with `scripts/ks_approved_runtime_execute.py --execute`.

## Integration Section Roots

The integration tree has three root areas:

```text
Источники
Интеграции
Интеграционные таблицы
```

Open or search the tree:

```http
POST /integrator/tree-get-down
```

```json
{
  "perPage": 50,
  "nodeUuid": null,
  "root": null,
  "nodeNum": 0,
  "sortBy": "createdAt",
  "sortDesc": false,
  "filter": {"nodeTypes": [], "openedNodesUUIDs": []}
}
```

Search can use `filter.term`.

## Core Read Endpoints

```text
POST /integrator/get-list
POST /integrator/get-by-ids
POST /integrator/get-sources-list
POST /integrator/get-sources-by-ids
POST /integrator/get-operations-list
POST /integrator/get-fields-rules-list
POST /integrator/get-api-mapping-list
POST /integrator/get-sampling-conditions-list
POST /integrator/get-output-sampling-conditions-list
POST /integrator/get-variables-by-integration-uuid
POST /integrator/get-processes-list
POST /integration-table/get-list
POST /integration-table/get-by-ids
POST /integration-table/get-data
POST /integration-table/get-mappings-list
POST /integration-table/get-filter-values
```

Common list payloads:

```json
{"projectUuid":"<project_uuid>", "uuids": null}
```

```json
{"byProject":"<project_uuid>", "onlyGlobal": false, "page": 1, "perPage": 50, "term": ""}
```

```json
{"integrationUuid":"<integration_uuid>"}
```

```json
{"integrationTableUuid":"<integration_table_uuid>", "filter": [], "order": [], "pagination": {"page": 1, "perPage": 50}}
```


## Read-Back Filtering Quirks

On some KS stands, read endpoints for integration details can return broad/global lists even when the payload looks integration-scoped. Do not treat array length as proof of the target integration state until each item is filtered back to the integration operations.

Safe comparison pattern:

1. Read integrations with `/integrator/get-list` or `/integrator/get-by-ids`.
2. Read operations with `/integrator/get-operations-list` and build `operationUuids` for the target integration.
3. Read field rules with `/integrator/get-fields-rules-list`, then keep only rules where `rule.operationUuid in operationUuids`.
4. Read output sampling conditions with `/integrator/get-output-sampling-conditions-list`, then keep only conditions where `condition.operationUuid in operationUuids`.
5. Compare counts, routes, mapping outputs, IDs, indicators, dimensions, disabled flags, custom SQL presence, and previous-operation links only after that filtering.

This avoids false reports such as thousands of field rules on a small training integration or output conditions appearing on every integration.

## Create/Update Tree Nodes

`/integrator/create-node` creates a tree node and, for `source` or `integration`, usually the backing entity too.

Folder:

```json
{"name":"Folder", "parentUuid": null, "previousUuid": null, "type":"folder", "description":""}
```

Source node shape, with secrets redacted:

```json
{
  "name": "Source node",
  "parentUuid": "<sources_folder_uuid>",
  "previousUuid": null,
  "type": "source",
  "source": {
    "name": "Source",
    "type": "database",
    "product": "postgres",
    "host": "<redacted>",
    "port": "5432",
    "dbName": "<redacted>",
    "login": "<redacted>",
    "password": "<redacted>",
    "sslMode": true,
    "isGlobalSource": false
  }
}
```

Integration node:

```json
{
  "name": "Integration node",
  "parentUuid": "<integrations_folder_uuid>",
  "previousUuid": null,
  "type": "integration",
  "integration": {"name":"Integration", "direction":"input", "sourceUuid":"<source_uuid>"}
}
```

Rename/move nodes:

```text
POST /integrator/update-node
POST /integrator/move-node
```


## DB Source Connection Parameters

For database sources, the UI may create the tree node first and then save connection parameters separately. Keep secrets redacted in logs and summaries.

```text
POST /integrator/create-connection-params
POST /integrator/update-source
POST /integrator/source-update-password
```

Connection-param shape, with sensitive fields redacted:

```json
{
  "params": [
    {
      "sourceUuid": "<source_uuid>",
      "sourceType": "database",
      "productType": "postgres",
      "auth": "password",
      "host": "<redacted>",
      "port": "5432",
      "productName": "<redacted_db_name>",
      "login": "<redacted>",
      "password": "<redacted>",
      "sslMode": "prefer"
    }
  ]
}
```

Treat `check-connection`, `connect`, password updates, global source binding, endpoint source activation, and source consumers as explicit-approval actions.

## Integration Entities

Direct create/update endpoints exist, but UI-observed tree creation is often safer for new items.

```text
POST /integrator/create
POST /integrator/update
POST /integrator/create-operations
POST /integrator/update-operation
POST /integrator/move-operation
POST /integrator/create-fields-rules
POST /integrator/update-field-rule
POST /integrator/create-api-mappings
POST /integrator/update-api-mapping
POST /integrator/create-sampling-conditions
POST /integrator/update-sampling-condition
POST /integrator/create-output-sampling-conditions
POST /integrator/update-output-sampling-condition
POST /integrator/create-variables
POST /integrator/update-variables
```

A direct integration create shape from OpenAPI:

```json
{
  "integrations": [
    {
      "name": "Input integration",
      "direction": "input",
      "location": "Europe/Moscow",
      "modelUuid": "<model_uuid>",
      "datasetUuid": "<dataset_uuid>",
      "sourcesUuids": ["<source_uuid>"],
      "routename": "data/save"
    }
  ]
}
```

## Integration Course Operating Rules

Patterns observed in the integration-course final project:

- Build object operations before data-update and relation operations. For example, create `Работы`, `Оборудование`, or `Персонал` objects before updating indicators or creating relation objects.
- Preserve operation order and previous-operation links. In sequential integrations, the tree/action order is part of the behavior.
- Treat external primary keys as text unless the course/source explicitly requires numeric typing. Exact ID matching is more important than display type.
- Dictionary loads should use exact names/case and stable external IDs. Case-insensitive dictionary handling can create duplicate or lower-cased values on some stands.
- Dimension values must match the internal dimension type exactly. Time dimensions from a backup must be rechecked on the target stand before reuse.
- Output integrations should have sampling conditions so zero/null values are not sent unintentionally.
- In the UI, action checkboxes and selected rows are not enough proof that only one action will run. Verify operation settings and run endpoint payload before any approved run.
- Some course/demo integrations show misleading success/error states when the source is unavailable. Verify by read-back, process history, and affected data, not only by toast text.

If the source is unavailable, operation detail screens can degrade to empty or `undefined` labels. Use the backup/API read-back as the source of truth for exact field rules and operation routes.



## Observed Integration Write Shapes

These payloads were observed on a 2026 KS stand while building a scratch integration-course project. Treat them as verified examples, not universal API law. On each new stand, test on a disposable project/entity first, then read back the entity before applying the pattern broadly. If OpenAPI, UI captures, and read-back behavior disagree, prefer the shape that the current stand accepts and verifies.

### Source Node And Connection Params

`/integrator/create-node` can create the source tree node and backing source, but some stands return a source with an empty/zero `connectionParam.sourceUuid`. In that case, save connection parameters separately with placeholders or approved credentials:

```json
{
  "params": [
    {
      "sourceUuid": "<source_uuid>",
      "sourceType": "database",
      "productType": "<postgres|mysql|mssql|clickhouse>",
      "auth": "password",
      "host": "<db_host>",
      "port": "<db_port>",
      "productName": "<db_name>",
      "login": "<redacted_or_env_login>",
      "password": "<redacted_or_empty_for_non_runnable_skeleton>",
      "sslMode": "<prefer|require|not_require>",
      "options": {"dboptions": {"interactionTimeout": 60}}
    }
  ]
}
```

Do not run connection checks automatically. Use an empty password only when intentionally building a non-runnable skeleton and record that the connection is unverified. Runnable integrations need credentials supplied through a secure channel.

### Updating Integration Metadata

Some stands accept the singular `/integrator/update` shape for one integration and may reject array shapes with a misleading “specified integration doesn't exist” error. Try the singular shape for a single update, then verify by reading the integration back:

```json
{
  "integration": {
    "uuid": "<integration_uuid>",
    "name": "<integration_name>",
    "direction": "<input|output|bidirectional>",
    "sourceUuid": "<source_uuid>",
    "sourcesUuids": ["<source_uuid>"],
    "modelUuid": "<model_uuid_or_zero>",
    "datasetUuid": "<first_dataset_uuid_or_zero>",
    "datasetsUuid": ["<dataset_uuid>"],
    "timeZone": "Etc/UTC",
    "useProjectTimeZone": true,
    "debugMode": false,
    "version": "sequential"
  }
}
```

Read responses may wrap `modelUuid` and `datasetsUuid` as `{"paramValue": ..., "variableUuid": null}`; this is normal.

### Operations, Field Rules, Conditions, Tables

Observed create payloads use OpenAPI casing at the top level. Verify counts and field mappings after each batch:

```json
{"Operations": [{"IntegrationUUID":"<integration_uuid>", "Routename":"create_object", "ClassUUID":"<class_uuid>"}]}
```

```json
{"FieldsRules": [{"OperationUUID":"<operation_uuid>", "SourceUUID":"<source_uuid>", "ExternalSchemaName":"public", "ExternalTableName":"<table>", "ExternalFieldName":["<field>"], "InternalField":"primaryKey", "IsID":true, "IsIndicator":false, "IsDimension":false, "IsActive":true}]}
```

```json
{"OutputSamplingConditions": [{"OperationUUID":"<operation_uuid>", "IndicatorUUID":"<indicator_uuid>", "Operator":"!=", "CompareType":"constant", "ConstValue":{"data":0,"type":"number"}, "CompareIndicatorUUID":"00000000-0000-0000-0000-000000000000"}]}
```

```json
{"IntegrationTables": [{"Name":"<table_name>", "ProjectUUID":"<project_uuid>", "IntegrationUUID":"<integration_uuid>", "OperationUUID":"<operation_uuid>", "AutoUpdate":false, "Lifetime":8, "Permanent":false, "Settings":{}, "TableSettings":{}, "ConditionSettings":{}, "IsGrouping":false}]}
```

For DB input operations, some UI/exported backups store `sourceOperationUuids` as `[source_uuid, operation_uuid]`. After creating the operation, read it back and update only if the current stand expects that path shape:

```json
{"Operation": {"uuid":"<operation_uuid>", "sourceOperationUuids":["<source_uuid>", "<operation_uuid>"]}}
```

Output/send operations often keep `sourceOperationUuids` empty and `sourceOperationType` as `undefined`; verify against the current operation read-back before changing it.

## Integration Operation Shape Notes

Operations commonly carry more than `name` and `routename`. Preserve the server/UI shape when updating an existing operation. Course backups showed fields such as:

```json
{
  "uuid": "<operation_uuid>",
  "integrationUuid": "<integration_uuid>",
  "name": "Create objects",
  "routename": "<route>",
  "sourceOperationType": "table_or_custom_query",
  "sourceOperationUuids": ["<source_operation_uuid>"],
  "options": {},
  "condition": {}
}
```

When an operation uses custom SQL, keep it in the operation/source-operation settings exactly as the UI/export stores it. Do not rewrite SQL text casually; validate generated fields with `get-custom-query-db-fields` or the backup/demo project before mapping.

## Modular Integration Graphs

Complex projects can use modular integrations (`/admin/integration-modular/...`) instead of simple sequential action lists. The UI may render operation nodes such as `Получение данных` and `Действие с сущностями` on a canvas.

Before changing a modular integration:

- read the full integration and every operation;
- read graph/edge/layout records when available;
- preserve source operation links and previous-operation edges;
- preserve node positions/layout unless the user asked for a visual cleanup;
- avoid copy-delete-reorder workflows on complex integrations, because visually identical actions may fail after structural changes.

Common source operation families in demos:

- `source_db`: database table, view, procedure, or custom query;
- `source_ks`: KS model/table data;
- entity actions: create object, update data, create relations;
- export/send actions for output integrations;
- filter/sampling actions.

If a modular operation starts failing after structural edits, recreate the affected node chain in a scratch project and compare read-back payloads instead of patching visible labels only.

## Integration Tables

Integration tables are separate from ordinary data tables. They are managed through `/integration-table/*`.

They are temporary or cached external-data views, not ordinary KS model data. A dashboard integration-table block can display rows produced by a configured integration/action without the rows being stored in the model like normal indicator data.

Create/update:

```text
POST /integration-table/create
POST /integration-table/update
POST /integration-table/create-mappings
POST /integration-table/update-mapping
```

Create shape:

```json
{
  "integrationTables": [
    {
      "name": "Table name",
      "projectUuid": "<project_uuid>",
      "integrationUuid": "<integration_uuid>",
      "operationUuid": "<operation_uuid>",
      "autoUpdate": false,
      "permanent": false,
      "lifetime": 3600,
      "settings": {},
      "tableSettings": {},
      "conditionSettings": {},
      "isGrouping": false
    }
  ]
}
```

Read data:

```json
{
  "integrationTableUuid": "<integration_table_uuid>",
  "filter": [],
  "order": [],
  "pagination": {"page": 1, "perPage": 50}
}
```

UI settings commonly include:

- source integration and action/operation;
- selected visible columns;
- lifetime/cache duration and `permanent` storage flag;
- auto-refresh;
- async data between tabs;
- grouping;
- timezone accounting;
- individual/shared display mode;
- conditional formatting.

`refresh-data`, `update-data`, and `export-data` are mutating/external-call actions. Editable integration-table rows may write back to the external source, depending on settings. Inspect mappings and settings before enabling editing or testing buttons.

When the external source is unreachable, the integration table can render a normal dashboard block with `Ошибка получения данных`. This is a valid diagnostic state, not a layout failure.


## DB Schema, Relations, And Variables

Use these read helpers while configuring operations and mappings. They may query the external source; do not call them against production/external systems unless the target source is confirmed as safe.

```text
POST /integrator/get-db-fields
POST /integrator/get-fields-by-source-operation
POST /integrator/get-fields-by-table
POST /integrator/get-source-operations-fields
POST /integrator/get-custom-query-db-fields
POST /integrator/get-custom-query-results
POST /integrator/get-routes
POST /integrator/get-relations-by-internal-uuid
POST /integrator/get-relations-by-internal-uuid-flat
```

`get-routes` is useful before choosing operation `routename`. Typical course routes observed in backups include object creation, object relation creation, data update/save, and dictionary element creation.

Integration field mappings and external/internal relations are managed separately from operation creation:

```text
POST /integrator/create-relations
POST /integrator/update-relation
POST /integrator/delete-relation
POST /integrator/delete-relations
POST /integrator/delete-relations-without-objects
POST /integrator/get-tables-relations-list
POST /integrator/create-tables-relations
POST /integrator/update-table-relation
POST /integrator/delete-tables-relations
```

Variables for parameterized integrations and integration tables:

```text
POST /integrator/get-variables-by-integration-uuid
POST /integrator/create-variables
POST /integrator/update-variables
POST /integrator/delete-variables
```

For DB integrations, inspect each operation for:

- external schema/table/field or custom SQL query;
- primary key mapping (`isId` / `primaryKey`);
- KS object name mapping;
- indicator value mappings;
- dictionary or dimension mappings;
- relation class mappings when the operation links objects.

## Running And Refreshing

Potentially mutating or external-call endpoints:

```text
POST /integrator/integrate
POST /integrator/integrate-modular
POST /integration-table/refresh-data
POST /integration-table/update-data
POST /integration-table/export-data
```

Only run these after confirming:

- target project;
- integration UUID and name;
- dataset/model targets;
- whether the source points to a demo/test system;
- expected data changes or external calls.

## Course Build Workflow

When passing the integration course from scratch:

1. Read the course DOCX text and identify expected entities, operations, mappings, and outputs.
2. Inspect the final/demo project backup or imported demo project read-only.
3. Create a new educational project or use the project the user names.
4. Build model/data prerequisites before integrations.
5. Create sources with placeholder/demo-safe credentials only; ask the user for real secrets through a secure channel if needed.
6. Create integrations, operations, field rules, mappings, sampling conditions, variables, and integration tables.
7. Verify all read endpoints and mappings before running integrations.
8. Run only demo-safe integrations after explicit confirmation, then verify process history and integration table data.
9. Document any step that cannot be completed without external credentials.
