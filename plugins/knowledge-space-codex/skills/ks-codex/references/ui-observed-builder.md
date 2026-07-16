# UI-Observed Builder API

This file summarizes normalized patterns learned from redacted KS web-UI
observations. They are valuable for building projects from scratch because some
payload shapes are not obvious from OpenAPI. Raw captures and stand-specific
evidence belong in a separate private overlay, never in the portable plugin.

Treat the captures as empirical UI behavior, not a complete public API guarantee.

## UI Headers

Most UI JSON requests include:

```http
Accept: application/json, text/plain, */*
Content-Type: application/json
X-Lang: ru_RU
X-Project-UUID: <projectUuid>
X-Project-Locales: ru_RU
X-Tab-Session-UUID: <tabSessionUuid>
X-User-Location: Europe/Moscow
X-CSRF-Token: <redacted>
```

For token-based API work, `Authorization: Bearer <token>` plus `X-Project-UUID` is usually enough. Do not ask users to paste cookies, CSRF tokens, JWTs, or passwords into chat.

## Constructor Navigation

Common tree read pattern:

```json
{
  "perPage": 50,
  "nodeUuid": null,
  "root": null,
  "nodeNum": 0,
  "sortBy": "createdAt",
  "sortDesc": false,
  "filter": {
    "nodeTypes": [],
    "openedNodesUUIDs": []
  }
}
```

Section entry points:

- Dictionaries: `POST /api/dictionaries/tree-get-down`
- Classes: `POST /api/classes/tree-get-down`
- Models: `POST /api/models/tree-get-down-flat`
- Interfaces: `POST /api/dashboards/tree-get-down`
- Applications: `POST /api/publications/get-list`, `POST /api/publications/tree-get-down`
- Integrations: `POST /api/integrator/tree-get-down`
- Business processes: `POST /api/processes/tree-get-down`
- Files: `POST /api/files/get-list`

Search often uses `tree-get-node-tree` with `filter.term`.

## Dashboard Routes And Tree Nodes

Dashboards have two identifiers that matter in the UI:

- dashboard/entity UUID: used by `/dashboards/get-by-id`, `/dashboards/update`, nested dashboard references, and publication inner nodes;
- tree node UUID: used in the constructor route query parameter `node`.

Do not assume they are the same. A route with `node=<dashboardUuid>` can show the tree but leave the workspace blank or reopen another cached dashboard. Prefer:

1. Read `/api/dashboards/tree-get-down` and recursively expand folders until the dashboard node is found.
2. Use the node's `uuid` as the route `node`.
3. Use the node's `referenceUuid` or backing dashboard UUID as `/admin/dashboard/<dashboardUuid>`.
4. If browser access is available, click the dashboard in the tree once and record the resulting URL.

Stable constructor route shape:

```text
#/admin/dashboard/<dashboardUuid>?treeType=dashboard&node=<dashboardTreeNodeUuid>&projectUuid=<projectUuid>&viewMode=true
```

Folders can hide important interfaces. Expand project folders before concluding a dashboard is missing from the UI.

Typing non-Latin text into the tree search can be unreliable in some automation/browser surfaces. If search input fails, use API tree traversal or click visible folders/items instead of retrying text entry.

## Create Dictionary And Element

```json
POST /api/dictionaries/create-node
{
  "name": "<dictionaryName>",
  "type": "dictionary",
  "description": "",
  "parentUuid": null,
  "previousUuid": null,
  "localNames": [
    {"code": "ru_RU", "name": "<dictionaryName>", "short": ""}
  ]
}
```

Verify with `/api/dictionaries/get-by-ids`.

```json
POST /api/dictionary-elements/create
{
  "dictionaryUuid": "<dictionaryUuid>",
  "name": "<elementName>",
  "shortName": "<shortName>",
  "localNames": [
    {"code": "ru_RU", "name": "<elementName>", "short": "<shortName>"}
  ]
}
```

Verify with `/api/dictionary-elements/get-list`.

## Create Class, Indicator, Relation

Class:

```json
POST /api/classes/create-node
{
  "name": "<className>",
  "previousUuid": null,
  "parentUuid": null,
  "type": "class",
  "localNames": [
    {"code": "ru_RU", "name": "<className>", "short": ""}
  ]
}
```

Open class card:

```json
POST /api/classes/get-by-ids
{
  "uuids": ["<classUuid>"],
  "withRelations": true,
  "withIndicators": false
}
```

Indicator inside class:

```json
POST /api/classes/create-class-node
{
  "name": "<indicatorName>",
  "localNames": [
    {"code": "ru_RU", "name": "<indicatorName>", "short": ""}
  ],
  "parentUuid": "<classNodeUuid>",
  "previousUuid": null,
  "type": "indicator",
  "classUuid": "<classUuid>",
  "dataType": "number"
}
```

Observed `dataType` examples include `number` and string-like types depending on UI selection. Verify actual indicator card with `/api/indicators/get`.

Class dimension:

```json
POST /api/classes/add-dimension
{
  "classUuid": "<classUuid>",
  "dictionaryUuid": "<dictionaryUuid>"
}
```

Relation class:

```json
POST /api/classes/create-class-node
{
  "name": "<relationName>",
  "localNames": [
    {"code": "ru_RU", "name": "<relationName>", "short": ""}
  ],
  "relatedSourceUuid": "<sourceClassUuid>",
  "relatedDestinationUuid": "<destinationClassUuid>",
  "previousUuid": null,
  "parentUuid": "<sourceClassNodeUuid>",
  "type": "class"
}
```

## Create Model And Dataset

```json
POST /api/models/create-node
{
  "name": "<modelName>",
  "parentUuid": null,
  "previousUuid": null,
  "type": "model",
  "localNames": [
    {"code": "ru_RU", "name": "<modelName>", "short": ""}
  ],
  "createDefaultDataset": true
}
```

`createDefaultDataset: true` creates a default dataset automatically.

Additional dataset:

```json
POST /api/datasets/create
{
  "name": "<datasetName>",
  "shortName": "<shortName>",
  "modelUuid": "<modelUuid>",
  "default": null,
  "readOnly": null,
  "description": "",
  "calcMode": "automatic",
  "localNames": [
    {"code": "ru_RU", "name": "<datasetName>", "short": "<shortName>"}
  ]
}
```

Verify with `/api/datasets/get-by-model-id`.

## Create Interface

Interfaces are dashboards.

```json
POST /api/dashboards/create-node
{
  "uuid": null,
  "name": "<interfaceName>",
  "type": "dashboard",
  "parentUuid": null,
  "previousUuid": null,
  "configuration": {
    "gridType": null,
    "events": [],
    "settings": {},
    "cells": [],
    "version": 2,
    "gridSize": 10,
    "gridGlueDistance": 10,
    "resizable": true
  },
  "height": 100,
  "width": 100,
  "unitType": "percents",
  "localNames": [
    {"code": "ru_RU", "name": "<interfaceName>", "short": ""}
  ]
}
```

Editor changes are usually saved with `POST /api/dashboards/update` and the full dashboard configuration.

Minimum durable cell shape:

```json
{
  "uuid": "<cellUuid>",
  "virtual": false,
  "tags": null,
  "entity": null,
  "events": [],
  "settings": {
    "name": {
      "value": "Ячейка 0",
      "showName": true,
      "size": "12",
      "color": "#000000",
      "paddingV": "5",
      "paddingH": "5",
      "align": "left"
    },
    "sizeAndContent": {
      "left": {"value": 0, "unit": "percents"},
      "top": {"value": 0, "unit": "percents"},
      "width": {"value": 10000, "unit": "percents", "fixed": false},
      "height": {"value": 10000, "unit": "percents", "fixed": false},
      "contentSize": {"width": 100, "unit": "percents", "height": 100},
      "contentAlign": {"vertical": "flex-start", "horizontal": "flex-start"},
      "resizerSides": ["left", "right", "top", "bottom"]
    },
    "cellStyle": {"visible": true},
    "defaultText": {
      "text": "",
      "backgroundColor": "#E3E7F7",
      "fontColor": "#777F87",
      "fontSize": 12,
      "font": "var(--mainFont)",
      "margin": 6,
      "alignV": "center",
      "alignH": "center"
    }
  }
}
```

Binding a cell to a widget/control is done by setting `configuration.cells[*].entity.type`, for example:

```json
{"type": "buttons", "hide": false}
```

Other observed UI entity choices include table, filter, chart, Gantt, object card, buttons, and business-process widgets.

## API-First UI Build Loop

For interface work, use this loop:

1. Read existing dashboard JSON and all referenced entities.
2. Map each visible block to a cell: type, entity references, events, tags, and layout.
3. Validate table constructor paths and data availability before changing dashboard events.
4. Patch dashboard JSON through `/dashboards/update`.
5. Re-read the dashboard and compare the exact edited cells.
6. Launch the interface only for high-risk checks: widget rendering, nested dashboard switching, modal opening/closing, Gantt selection, charts, and layout overlap.

An API-only pass can prove references and data exist, but cannot prove browser rendering. Mark final visual behavior as unverified if no browser check was performed.

## Create Application / Publication

Direct bulk creation:

```json
POST /api/publications/create
{
  "publications": [
    {
      "name": "<applicationName>",
      "projectUuid": "<projectUuid>",
      "isSystem": false,
      "link": "<custom-or-generated-link>"
    }
  ]
}
```

Application tree creation through UI:

```json
POST /api/publications/create-node
{
  "name": "<applicationName>",
  "type": "publication",
  "parentUuid": null,
  "previousUuid": null,
  "publication": {
    "name": "<applicationName>",
    "projectUuid": "<projectUuid>",
    "isSystem": false,
    "link": "<custom-or-generated-link>"
  },
  "localNames": [
    {"code": "ru_RU", "name": "<applicationName>", "short": ""}
  ]
}
```

Open by id:

```json
POST /api/publications/get-by-ids
{
  "uuids": ["<publicationUuid>"],
  "withData": true
}
```

Update access:

```json
POST /api/publications/update-access
{
  "uuid": "<publicationUuid>",
  "accessType": "link",
  "actionType": "view",
  "link": "<publication-link>",
  "users": [],
  "roles": []
}
```

Inner dashboard node:

```json
POST /api/publications/create-inner-node
{
  "publicationUuid": "<publicationUuid>",
  "name": "<dashboardName>",
  "type": "dashboard",
  "parentUuid": null,
  "previousUuid": null,
  "referenceUuid": "<dashboardUuid>",
  "isHidden": false
}
```

For modal dashboards, create an inner node with `isHidden: true`.

## Files, Integrations, Processes

These captures are useful for read-only navigation but higher-risk for mutations.

Files:

- list: `POST /api/files/get-list`
- metadata: `POST /api/files/get-file-info`, `POST /api/files/get-by-ids`
- content/download: `POST /api/files/get`, `GET /api/files/download`
- mutating: upload and delete endpoints require explicit approval.

Integrations:

- read tree: `POST /api/integrator/tree-get-down`
- read lists: `POST /api/integrator/get-list`, `/api/integrator/get-sources-list`, `/api/integration-table/get-list`
- mutating/run endpoints such as `integrate`, `integrate-modular`, connection checks, password updates, and source updates are high-risk.

Business processes:

- read tree/list: `POST /api/processes/tree-get-down`, `/api/processes/get-list`, `/api/processes/get-tree`
- enabling/running/updating processes requires explicit approval.

## Verification Checklist

After any approved write:

1. Re-read the exact entity by UUID.
2. Re-read the containing tree/list.
3. Confirm visible name, type, parent location, and key references.
4. Report created/updated UUIDs and any uncertainty.
