# KS Project Audit

Use this checklist before editing a whole project or diagnosing empty UI.

## 1. Project Context

Record:

- server base URL;
- `ProjectUUID`;
- user account;
- target model UUID(s);
- target publication/application UUID(s);
- whether the task is read-only or write-enabled.

Never infer the project from visible UI text alone. Confirm via API.

For UI work, also record both dashboard UUID and dashboard tree node UUID. Breadcrumb text and cached tree state can be stale; `X-Project-UUID` and API reads are the source of truth.

## 2. Model Structure

Read:

- models and datasets;
- class list;
- indicators and formulas;
- dictionaries and dictionary elements;
- objects and object counts by class.

For relation-heavy projects, identify:

- relation class UUID;
- source class;
- destination class;
- relation object UUIDs;
- indicators that live on relation objects.

## 3. Data Completeness

For every table or widget, map the display path:

```text
dataset -> object/class/relation path -> indicator -> optional dimensions
```

Then query `/data/get-list` for exactly those datasets, objects/classes, indicators, and dimensions.

A table can be correctly configured and still blank if values are missing for:

- the selected dataset;
- the relation object rather than the destination object;
- the selected dictionary element;
- a hidden/common dataset expected by formulas.

## 4. Data Tables

Read each table with `/data-tables/get-by-id`.

Check:

- `data.constructorData.rows`;
- `data.constructorData.columns`;
- `data.constructorData.filters`;
- do not treat legacy top-level `rows`, `columns`, or `filters` being empty/null as proof that the table is empty;
- dataset nodes include all datasets exposed by filters;
- indicator nodes include the indicators users expect to see;
- dimensional indicators have a dictionary/dimension field in the constructor if the UI must expose dimensions;
- related-object tables use a correct relation path, not only destination class.


Use `scripts/ks_table_audit.py` on snapshots for a first pass over constructor axes, field types, and model/class/indicator/dictionary references. Treat dataset and object UUIDs as unvalidated when the snapshot does not include dataset/object registries; do not turn those into patch plans without a direct API read-back.

For related-object rows, look for:

```json
{
  "fieldType": "relatedObjectsClass",
  "data": {
    "classUuid": "<start_resource_class>",
    "classesPath": ["<relation_class>", "<destination_class>"],
    "fullChain": true,
    "hideObjectRelations": false
  }
}
```

For selected-work assignment modals, the related-object row is usually `resource -> assignment relation -> work`, and the table cell should listen with `action: "tableFilterStructure"` plus `filter.tableCellSettings.fieldUuid=<row_uuid>` and `objectChainPartIndex: 1`. A plain `classObjects` relation row or `changeRelationObject` event can pass JSON validation while showing unrelated assignments in the launched UI.

## 5. Dashboards

Read dashboards with `/dashboards/get-by-id`.

Check every cell:

- `entity.type`;
- reference fields such as `tableTable`, `tableModel`, dashboard `value.uuid`, Gantt `value.uuid`;
- `settings.name.value`;
- `settings.sizeAndContent`;
- top-level `events`;
- entity-level events such as `widgetEvents`, `buttonsElements[*].events`, `iconsElements[*].events`.

Blank white areas often mean missing `settings.sizeAndContent`, oversized cells, or overlapping cell layout.

Also check:

- the dashboard appears in `/dashboards/tree-get-down` and has a real tree node;
- the route uses the tree node UUID, not just the dashboard UUID;
- nested dashboard cells reference existing dashboards;
- incoming events point to the correct source cell UUIDs;
- table/detail cells that should react to a selected object have matching tags and actions.

For widgets and flat lists, do not stop at config validation. They can render blank cards or default numeric values even when the widget JSON is accepted. Prefer a browser check or a table fallback if the widget cannot be proven visually.

## 6. Publication/Application

Read `/publications/get-list` or `/publications/get-by-link`.

For `/publications/get-list`, filter the returned array by `projectUuid == ProjectUUID` before using it. This endpoint can return publications from other projects visible to the current user.

Check:

- publication is active;
- access type is suitable (`link`, user/role access, etc.);
- main dashboard is in `innerTree` and visible;
- modal dashboards are also in `innerTree`, usually hidden;
- nested dashboards do not need to be visible in the publication, but referenced dashboards must exist.

## 7. Gantt

Read:

- `/gantts/get-list` or `/gantts/get-by-model`;
- `/gantts/get-structure` for final tree.

Check:

- task objects are present;
- nesting and sequence relations exist;
- Gantt cell events generate the object tag expected by downstream cells;
- on verified KS 1.7 frontend builds, Gantt selected-object saving uses `action: "save"` and the real Gantt cell UUID in `uuids`, not legacy `saveValue`/`self`;
- custom control opens the modal dashboard if required.

For Gantt-driven modals, test a leaf task, not only a parent/group task. Parent rows can have valid labels but no meaningful resource/cost values.

## 8. Completion Criteria

A KS project is not complete until:

- API state matches the requested model/data/UI configuration;
- every user-facing table has data for its filters;
- dashboard events match the intended interaction;
- publication contains the required dashboards;
- browser behavior has been checked or clearly marked as unverified;
- modal assignment tables are proven to show the selected context, not all rows from the relation class;
- charts/widgets are checked for real values rather than placeholders such as `0`, `0.00`, or blank cards.
