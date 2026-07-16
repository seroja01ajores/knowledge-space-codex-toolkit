# KS API Map

Primary docs:

- Main docs: `https://main.ks.works/`
- Swagger UI: `https://ks.works/docs/#/`
- OpenAPI YAML: `https://ks.works/openapi.yaml`

The Swagger UI is JavaScript-rendered. For automation, fetch `openapi.yaml`.

## Base Rules

- Base URL usually ends with `/api`, for example `https://<host>/api`.
- All project work must pass `X-Project-UUID`.
- Most endpoints are `POST`.
- Payload casing is mixed:
  - many entity endpoints use `UUID`, `ModelUUID`, `TableUUID`, `DashboardUUID`;
  - data cells often use compact fields `d`, `i`, `o`, `m`, `v`.
- Always inspect JSON body for `error`, even when HTTP status is 200.

## Core Endpoints

Auth:

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`

Models, datasets, classes, indicators:

- `POST /models/get-with-datasets`
- `POST /datasets/get-list`
- `POST /datasets/get-by-model-id`
- `POST /classes/get-list`
- `POST /classes/get-by-ids`
- `POST /indicators/get-with-formulas`
- `POST /formulas/get-by-indicators`
- `POST /fields/get-by-entity`

Objects and relations:

- `POST /objects/get-list`
- `POST /objects/get`
- `POST /objects/get-short`
- `POST /objects/create`
- `POST /objects/create-batch`
- `POST /objects/update`
- `POST /objects/delete`
- `POST /objects/get-chain`
- `POST /objects/get-chain-by-relation-classes`

Dictionaries:

- `POST /dictionary-elements/get-list`
- `POST /dictionary-elements/create`
- `POST /dictionary-elements/update`
- `POST /dictionary-elements/delete`

Data:

- `POST /data/get-list`
- `POST /data/get-list-min`
- `POST /data/get-list-multi`
- `POST /data/get-by-dataset-and-dimensions`
- `POST /data/save`

Data tables:

- `POST /data-tables/get-list`
- `POST /data-tables/get-by-id`
- `POST /data-tables/get-table-settings`
- `POST /data-tables/create`
- `POST /data-tables/update`
- `POST /data-tables/update-table-settings`
- `POST /data-tables/update-constructor-data`

Dashboards/interfaces:

- `POST /dashboards/get-list`
- `POST /dashboards/get-by-id`
- `POST /dashboards/get-tree`
- `POST /dashboards/create-node`
- `POST /dashboards/update`
- `POST /cells/get-by-dashboard-id`

Publications/applications:

- `POST /publications/get-list`
- `POST /publications/get-by-link`
- `POST /publications/create`
- `POST /publications/update`
- `POST /publications/update-access`
- `POST /publications/create-inner-node`
- `POST /publications/update-inner-node`
- `POST /publications/get-tree`

Gantt:

- `POST /gantts/get-list`
- `POST /gantts/get-by-id`
- `POST /gantts/get-by-model`
- `POST /gantts/get-structure`
- `POST /gantts/save-data`
- `POST /gantts/update`

## Data Payloads

Read values:

```json
{
  "ModelUUID": "<model>",
  "DatasetsUUIDs": ["<dataset>"],
  "ObjectsUUIDs": ["<object>"],
  "IndicatorsUUIDs": ["<indicator>"],
  "PerPage": 1000,
  "WithEntityName": true
}
```

Save values:

```json
{
  "Data": [
    {
      "ModelUUID": "<model>",
      "d": "<dataset>",
      "i": "<indicator>",
      "o": "<object>",
      "m": {"<dictionary_uuid>": "<element_uuid>"},
      "v": {"type": "number", "data": 123}
    }
  ],
  "IsManual": true,
  "SkipGetPreviousData": false
}
```

For non-dimensional values, omit `m`.

Value examples:

```json
{"type": "string", "data": "Name"}
{"type": "number", "data": 12.5}
{"type": "date", "data": "2026-05-07"}
```

## Known API Quirks

- `/dashboards/get-by-id` returns the full dashboard configuration with `configuration.cells`. Prefer it when diagnosing interfaces.
- `/cells/get-by-dashboard-id` is documented with payload `{"uuid":"...", "withEvents":false}`, but some deployments return `{}` or fail when `withEvents:true`. Fall back to `/dashboards/get-by-id`.
- `/data-tables/get-by-id` expects `UUID`. Passing `TableUUID` can return an application-level error.
- `/data-tables/get-table-settings` expects `TableUUID`.
- `/data-tables/update-constructor-data` can be unavailable on older/self-hosted deployments. Fall back to `/data-tables/update` with `UUID`, `Name`, `Data`, and `ConstructorData`.
- `/gantts/get-structure` commonly expects `UUID`, `ModelUUID`, and `ShowEmptyTasks` with uppercase keys.
- Relation objects may be hidden from `/objects/get-list`; use `/objects/get-chain` or relation-class endpoints to inspect them.
