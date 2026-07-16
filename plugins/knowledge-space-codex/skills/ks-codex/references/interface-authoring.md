# Interface Authoring

Use this reference when creating or repairing KS dashboards from a design brief, Figma/template layout, screenshot, or task such as "align everything left" or "remove overlaps".

## Design To KS Layout

KS dashboards are cell grids. Treat the source design as a structure first, not as pixels:

1. Identify screens: main dashboard, nested dashboard areas, modal dashboards, and publication/application nodes.
2. Identify blocks: Gantt, table, widget/card, filter, navigator, chart, button row, static text, nested dashboard placeholder.
3. Convert each visible block to a dashboard cell with stable `settings.sizeAndContent`.
4. Convert the design frame to the KS coordinate grid:
   - `left`, `top`, `width`, `height` use percent-like values from `0` to `10000`;
   - `left + width <= 10000`;
   - `top + height <= 10000`;
   - keep gaps explicit, usually `100` to `250` grid units for dense enterprise dashboards.
5. Keep table-heavy screens readable. A table with many grouped columns usually needs full width; if two half-width tables wrap headers letter-by-letter, stack them vertically or move one into a nested/modal dashboard.
6. Make fixed-format controls predictable: reserve enough height for button rows, filters, tabs, and Gantt toolbars so labels and icons do not overlap the next cell.
7. Create modal dashboards as separate dashboards and include them in the publication/application, often hidden.

Do not map every decorative design layer to a KS cell. Only create cells that have runtime meaning or are needed for a clear working interface.

For a Figma/template frame, normalize coordinates before writing KS JSON:

```text
ks_left   = round(figma_x / frame_width * 10000)
ks_top    = round(figma_y / frame_height * 10000)
ks_width  = round(figma_width / frame_width * 10000)
ks_height = round(figma_height / frame_height * 10000)
```

Then snap near edges/gaps to stable grid values. Prefer a small number of meaningful KS cells over a pixel-perfect copy of every design layer. Translate Figma components by function: primary data grid -> `table`, card/list -> `WIDGET` or table fallback, chart -> `chart`, tab/segmented control -> `buttons`, overlay/dialog -> modal dashboard, navigation/tree -> `NAVIGATOR` or dashboard tree.

When using an existing dashboard as a source of cell templates, copy only behavior that belongs to the new user flow. Do not copy a stateful modal/open button into a layout-only test unless the dashboard also includes and verifies the required selected-object workflow; otherwise the modal can open with a stale global/settings variable from a previous screen. For read-only layout training, prefer Gantt/table/chart/filter blocks and omit mutating or stateful action buttons.

## Figma Template Workflow

Without direct Figma API access, ask for a screenshot, exported frame specs, or a simple block list. With Figma API access, extract frame size, node names, node bounds, component names, and visible text. Then:

1. Choose the KS screen type: main dashboard, nested dashboard, modal dashboard, or application publication node.
2. Group Figma layers into runtime blocks, not decorative layers. Ignore shadows, background rectangles, ornamental icons, and marketing-only content.
3. Build a block map with `name`, `purpose`, `source bounds`, `KS cell type`, `data source`, `events`, and `risk`.
4. Convert bounds to `0..10000`, then snap to a small grid and reserve explicit gaps.
5. Choose KS cell types by behavior:
   - repeated records -> `table` or `WIDGET`;
   - KPI/card list -> `WIDGET`, or `table` fallback if widgets render blank;
   - timeline -> `gantt`;
   - chart visual -> `chart`;
   - form/action strip -> `buttons`;
   - dropdown/selector panel -> `filter`;
   - embedded page -> nested `dashboard`;
   - dialog -> separate modal dashboard.
6. Prepare the dashboard patch plan before writing. Include all before/after coordinates and any copied source dashboard/table UUIDs.
7. After writing, verify read-back, cell report, browser screenshot, and the real user scenario.

If the Figma template has dense tables, bias toward function over visual symmetry: give grouped tables enough width, move secondary content to a lower band or modal, and keep buttons out of table header areas.

## Recommended Patch Plan

Before writing a dashboard layout change, prepare a small table:

```text
dashboard: <name> / <uuid>
cell: <name> / <uuid>
before: left=<n> top=<n> width=<n> height=<n>
after:  left=<n> top=<n> width=<n> height=<n>
reason: <overlap/readability/alignment/design mapping>
```

Then:

1. Read with `POST /dashboards/get-by-id`.
2. Patch the full dashboard object offline.
3. Write the raw dashboard object with `POST /dashboards/update`; do not wrap it in `{"dashboard": ...}`.
4. Read back and compare exact cells.
5. Browser-check user-facing pages after cache refresh/reload.

## Common Layout Edits

Align a group to the left:

- choose the anchor `left` value;
- set all target cells to the same `left`;
- preserve widths unless the task asks to resize;
- check `left + width` after alignment.

For tasks such as "align everything left":

- define the target set from visible business cells only;
- exclude full-screen virtual/action cells, hidden helper cells, modal dashboards, and nested dashboards unless the task explicitly includes them;
- keep `top`, `height`, events, and referenced entity UUIDs unchanged;
- resize only when the aligned cell would exceed `10000`;
- read back the dashboard and run a cell report before browser verification.

Normalize button rows:

- set the row cell height greater than the button pixel height plus padding;
- set each button `sizeStyles.height` and `sizeStyles.width` consistently;
- keep `buttonsColumns` aligned with the visible button count.

Remove overlapping blocks:

- classify virtual/background cells separately from real controls;
- move or resize only real visible cells unless the virtual cell is known to block clicks;
- check both API rectangles and browser screenshot because valid rectangles can still render badly when table headers wrap.

Repair cramped tables:

- prefer wider table cells before changing table definitions;
- for modal dashboards, increase `showDashboard.windowSize` before changing content;
- if grouped headers still wrap too much, stack tables vertically or split the flow into nested dashboards/tabs.
- when converting a Figma side panel that contains a grouped table, allocate extra width early; tables with dataset/dictionary column groups can wrap headers letter-by-letter in narrow right columns even when there is no geometric overlap.

## Comments And Descriptions

Use comments to help analysts understand why an element exists, not to hide configuration.

Rules:

- Prefer official `description`, `comment`, `note`, or help/tooltip fields only after verifying that the entity type supports them through get/update APIs or UI capture.
- On observed KS dashboards, classes, and data tables, `/fields/get-by-entity` may return empty `fields`; do not invent custom field writes when no field exists.
- Dashboard entities support a top-level `description` through `/dashboards/get-by-id` and `/dashboards/update`. Preserve the existing dashboard object and update only `description` when adding analyst-facing rationale.
- Dashboard cells in `/dashboards/get-by-id` do not necessarily have standalone `description` fields. Use `settings.name.value` only for short constructor/internal labels, not long comments.
- Good dashboard descriptions state the purpose and safety boundary of the screen, for example that a dashboard is a training layout made from read-only blocks and should not be treated as the production workflow.
- Do not store credentials, source connection strings, tokens, customer secrets, or personal data in comments.
- Do not replace user-facing labels with internal comments.
- For dashboard cells, `settings.name.value` is mainly a constructor/internal cell name. It can be useful for short labels like `Вложенный интерфейс` or `Ресурсы работы`, especially when `showName` is false, but do not use it for long implementation notes.
- Table configs can contain `commentsSettings`, `displayCommentsByDefault`, or `blockCommentsReply`, but enabling table comment UI is separate from writing analyst documentation. Verify the actual comment backend/UI before using these settings as "comments".
- For project documentation, keep longer rationale in external docs or a dedicated analyst-facing description field if KS exposes one for that entity.

Observed `description` support on KS 1.7-style projects:

```text
project:      description in /projects/get-by-id
dashboard:    description + descriptionStatus in /dashboards/get-list and /dashboards/get-by-id
class:        description + descriptionStatus in /classes/get-list
indicator:    description + descriptionStatus in /indicators/get and /indicators/get-list
dataset:      description in /datasets/get-by-model-id
gantt:        description + descriptionStatus in /gantts/get-list
dictionary:   description + descriptionStatus in /dictionaries/get-list
data table:   no ordinary description observed in /data-tables/get-list or /data-tables/get-by-id on the tested stand
dashboard cell: no standalone description observed in /dashboards/get-by-id cells
```

For data tables and cells, put rationale in the parent dashboard description or external analyst documentation unless a stand exposes verified custom fields. For indicators/classes, keep descriptions short and semantic: what the entity means, dimensions/datasets it expects, and important formula or relation assumptions.

Good comment content:

```text
Filters assigned-resource table by selected work saved in variable `работа`.
```

Bad comment content:

```text
Stores source credentials or tokens here.
```


## Offline Training Tools

Use these tools before layout/comment writes when a project snapshot is available:

```bash
python3 scripts/ks_dashboard_layout_plan.py snapshot.json --dashboard "<name or uuid>" --include-type buttons --output layout.md --plan-output layout_plan.json
python3 scripts/ks_comment_audit.py snapshot.json --output comments.md --plan-output comments_plan.json
python3 scripts/ks_safe_patch_lint.py layout_plan.json --strict
```

`ks_dashboard_layout_plan.py` is for dry-run layout tasks such as left alignment. It records exact cell UUIDs, before/after rectangles, and changes only `settings.sizeAndContent` fields in the plan.

`ks_comment_audit.py` distinguishes verified description fields from unsupported comment targets. On tested KS 1.7-style snapshots, dashboard descriptions are safe to plan through `/dashboards/update`, while dashboard cells and ordinary data tables should not receive invented comment metadata.

## Browser Verification Checklist

After API layout work, verify the actual user flow:

- view mode opens the intended dashboard through the publication/tree route;
- switch buttons change nested dashboard content;
- modal buttons open and close the target dashboard;
- tables show readable headers and at least expected rows/empty states;
- buttons do not sit under tables or other cells;
- no skeleton loaders remain forever;
- console/network errors are understood before calling the screen complete.

API read-back proves persistence. Browser verification proves the interface works for users.
