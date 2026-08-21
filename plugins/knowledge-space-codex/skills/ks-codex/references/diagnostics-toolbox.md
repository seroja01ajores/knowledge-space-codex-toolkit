# KS Diagnostics Toolbox

Load this file only when diagnosing a KS interface or selecting a bundled
offline audit or planning script.

## Empty Interface Order

Check these causes in order and stop when evidence identifies the failing
layer:

1. The dashboard cell has no usable layout in
   `configuration.cells[*].settings.sizeAndContent`.
2. A table cell points to the wrong `tableTable` or model.
3. Constructor rows or columns reference the wrong class, dataset, indicator,
   dimension, or relation path.
4. Data is absent for the exact dataset, object, indicator, and dimensions.
5. The incoming event action does not match the receiving cell:
   - widget to ordinary object table: `filter`;
   - selected object to relation-scoped table: usually
     `tableFilterStructure` with `filter.tableCellSettings`;
   - object-card relation replacement: `changeRelationObject`;
   - dictionary or dataset dimension filtering: often
     `tableFilterStructure`;
   - nested dashboard placement: `sendEntity` to `getDashboard` plus `place`;
   - modal opening: prefer `showDashboard` with `showType: inWindow` over
     imported legacy `getDashboard` plus `modal`.
6. The publication omits the dashboard or its hidden modal dependency.
7. Frontend cache or session state is stale after a configuration write.
8. The route uses an entity UUID as `node` instead of the tree-node UUID from
   `/dashboards/tree-get-down` or a UI tree click.
9. JSON is valid but the frontend component fails. Inspect browser console,
   network, and rendered DOM before declaring the API configuration correct.

## Tool Selection

Run scripts for their output; do not load source code unless adapting the tool.

| Need | Script |
| --- | --- |
| Quick read-only overview | `ks_smoke_check.py` |
| Reusable project snapshot and audit bundle | `ks_readonly_audit_runner.py` |
| Compare sanitized snapshots | `ks_project_diff.py` |
| Integration-course audit | `ks_integration_readonly_audit.py` |
| BPMS references and run-safety warnings | `ks_bpms_audit.py` |
| Table constructor reference audit | `ks_table_audit.py` |
| Dashboard cells, events, coordinates, overlaps | `ks_dashboard_cell_report.py` |
| Offline dashboard layout dry run | `ks_dashboard_layout_plan.py` |
| Verified analyst-description targets | `ks_comment_audit.py` |
| Publication inner-node dry run | `ks_publication_patch_plan.py` |
| Patch effect and gate classification | `ks_safe_patch_lint.py` |

For generated patch batches or approved runtime effects, follow
`safe-patch-workflow.md`; this catalog does not grant execution permission.
