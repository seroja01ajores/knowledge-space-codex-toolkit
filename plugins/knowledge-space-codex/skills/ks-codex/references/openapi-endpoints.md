# Focused OpenAPI Endpoint Index

Source: `https://ks.works/openapi.yaml`.

This is a focused index for project work. The full OpenAPI contains many more administrative, chat, approval, backup, import/export, and system endpoints. Do not use administrative endpoints unless the user explicitly asks for that domain.

Endpoint names are listed for recognition and lookup, not as permission to call them. Treat `delete`, `run`, `integrate`, backup restore/load, access, and administrative endpoints as explicit-approval operations.

## Authentication

- `/auth/login`
- `/auth/refresh`
- `/auth/logout`
- `/auth/project-login`
- `/auth/project-logout`

## Projects And Access

Use access endpoints carefully; they can affect users beyond the current task.

- `/projects/get-list`
- `/projects/get-by-id`
- `/projects/update`
- `/access-control/can-do`
- `/access-control/get-project-roles`
- `/access-control/get-user-roles`
- `/access-control/set-project-role`
- `/access-control/unset-project-role`

## Models

- `/models/get-list`
- `/models/get`
- `/models/get-with-datasets`
- `/models/create-node`
- `/models/create-model-node`
- `/models/update`
- `/models/update-node`
- `/models/copy`
- `/models/delete-node`

## Classes

- `/classes/get-list`
- `/classes/get-by-ids`
- `/classes/get-tree`
- `/classes/get-node-by-reference`
- `/classes/create-node`
- `/classes/update`
- `/classes/update-node`
- `/classes/delete`
- `/classes/add-dimension`
- `/classes/remove-dimension`

## Indicators And Formulas

- `/indicators/get-with-formulas`
- `/indicators/create`
- `/indicators/update`
- `/indicators/delete`
- `/formulas/get-by-indicators`
- `/formulas/get-by-ids`
- `/formulas/create`
- `/formulas/update`
- `/formulas/delete`
- `/kpi/calculate-formulas-by-ids`

Formula setup is fragile. Prefer reading and reporting formula gaps unless the user specifically asks to build formulas.

## Custom Fields / Entity Cards

- `/fields/get-by-entity`
- `/fields/get-list`
- `/fields/create`
- `/fields/update`
- `/fields/save`
- `/fields/set-value`
- `/fields/delete`

The UI often hydrates constructor cards with `/fields/get-by-entity` after opening classes, indicators, models, dashboards, and other entities.

## Datasets

- `/datasets/get-list`
- `/datasets/get-by-id`
- `/datasets/get-by-ids`
- `/datasets/get-by-model-id`
- `/datasets/create`
- `/datasets/create-copy`
- `/datasets/update`
- `/datasets/delete`
- `/datasets/create-tag`
- `/datasets/tie-tags`
- `/datasets/untie-tags`

## Objects And Relation Chains

- `/objects/get-list`
- `/objects/get`
- `/objects/get-short`
- `/objects/get-ids`
- `/objects/create`
- `/objects/create-batch`
- `/objects/update`
- `/objects/update-batch`
- `/objects/delete`
- `/objects/delete-batch`
- `/objects/add-model-batch`
- `/objects/remove-model`
- `/objects/get-chain`
- `/objects/get-chain-by-relation-classes`
- `/objects/search-chain`

Relation objects may not appear in ordinary object lists. Use chain endpoints for relation-based tables and workflows.

## Dictionaries

- `/dictionaries/get-list`
- `/dictionaries/get-by-ids`
- `/dictionaries/create-node`
- `/dictionaries/update`
- `/dictionaries/update-node`
- `/dictionaries/delete-node`
- `/dictionary-elements/get-list`
- `/dictionary-elements/get-short`
- `/dictionary-elements/create`
- `/dictionary-elements/update`
- `/dictionary-elements/delete`

## Data

- `/data/get-list`
- `/data/get-list-min`
- `/data/get-list-multi`
- `/data/get-by-dataset-and-dimensions`
- `/data/get-objects`
- `/data/save`
- `/data/compare-indicator-values`
- `/data/get-data-conversion-errors-by-indicator`

Use `/data/save` for project data writes. Never write directly to the dataset database.

## Data Tables

- `/data-tables/get-list`
- `/data-tables/get-by-id`
- `/data-tables/get-constructor-data`
- `/data-tables/get-table-settings`
- `/data-tables/create`
- `/data-tables/update`
- `/data-tables/update-constructor-data`
- `/data-tables/update-table-settings`
- `/data-tables/delete`
- `/data-tables/copy`

If a deployment returns 404 for `/data-tables/update-constructor-data`, use `/data-tables/update`.

## Dashboards / Interfaces

- `/dashboards/get-list`
- `/dashboards/get-by-id`
- `/dashboards/get-tree`
- `/dashboards/tree-get-down`
- `/dashboards/tree-get-up`
- `/dashboards/tree-get-node-tree`
- `/dashboards/tree-search`
- `/dashboards/create-node`
- `/dashboards/update`
- `/dashboards/update-node`
- `/dashboards/delete-node`
- `/dashboards/move-node`
- `/cells/get-by-dashboard-id`
- `/cells/get-by-id`
- `/cells/create`
- `/cells/update`
- `/cells/delete`

Prefer `/dashboards/get-by-id` for complete dashboard JSON.

## Publications / Applications

- `/publications/get-list`
- `/publications/get-by-ids`
- `/publications/get-by-link`
- `/publications/get-tree`
- `/publications/create`
- `/publications/update`
- `/publications/delete`
- `/publications/update-access`
- `/publications/create-inner-node`
- `/publications/update-inner-node`
- `/publications/delete-inner-nodes`
- `/publications/move-inner-node`
- `/publications/list-access`

Verified caveat: `/publications/get-list` may return every publication visible to the user, not only the current `X-Project-UUID`. Always filter the response by `projectUuid` before using IDs from it.

For modal dashboards, add the dashboard to the publication inner tree and hide it from navigation if needed.

## Gantt

- `/gantts/get-list`
- `/gantts/get-by-id`
- `/gantts/get-by-model`
- `/gantts/get-structure`
- `/gantts/get-data-by-objects`
- `/gantts/get-data-paged`
- `/gantts/get-filters`
- `/gantts/create`
- `/gantts/update`
- `/gantts/add-objects`
- `/gantts/create-object`
- `/gantts/delete-object`
- `/gantts/create-relations`
- `/gantts/update-relations`
- `/gantts/save-data`
- `/gantts/create-option`
- `/gantts/update-option`
- `/gantts/delete-option`

## Files And Imports

These may affect larger project state. Use only when the task is explicitly about import/export or files.

- `/files/get-by-ids`
- `/files/upload`
- `/imports/create`
- `/imports/import`
- `/imports/import-one-step`
- `/imports/cancel`
- `/imports/send-report`
- `/imports/send-request`
- `/imports/delete`

## Backups

Backup endpoints are potentially broad and destructive. Do not use during ordinary project work.

- `/backups/save`
- `/backups/load`
- `/backups/delete`
- `/backups/get-list`
- `/backups/get-history`
