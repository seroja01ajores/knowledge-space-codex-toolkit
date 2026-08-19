# Safe Full-project Clone and Restore

Use this pattern when the user needs a complete independent KS project clone,
not an empty project shell or a copied dashboard configuration.

## Capability Boundary

- Read-only source inventory: read-only.
- Creating/downloading a source backup: `approved_runtime`.
- Restoring the backup into a new project: `approved_destructive`.
- Deleting an accidental empty project: a separate exact destructive approval.

Do not write directly to PostgreSQL or project storage. Do not treat approval to
create a clone as approval to delete, overwrite, broaden access, or rerun with
different options.

## Reliable Workflow

1. Read the source project and bind its exact UUID and name.
2. Create a backup through the normal KS backup API/UI and record its hash and
   terminal status.
3. Restore to a new project. Do not create an empty target project first.
4. Preserve current-user-only access and disable automatic recalculation unless
   the approved plan explicitly says otherwise.
5. Wait for terminal restore status, then discover server-assigned UUIDs.
6. Read back models, classes, relations, dashboards, tree nodes, publications,
   and user access before calling the clone complete.
7. Verify the clone through the KS tree/browser as well as the API.

A verified stand used fields equivalent to:

```json
{
  "restoreAction": "restoreToNewProject",
  "entityRestoringMode": "fullRestoring",
  "decompress": true,
  "clearEntitiesCategory": ["ext"]
}
```

Treat this as an observed payload family, not universal API law. Capture or
read the current stand's UI/OpenAPI request and verify all options before an
approved restore.

## Empty-project Trap

A UI "copy settings" action can create a project with the desired name but no
models, dashboards, or tree. Do not infer clone success from project creation
or name alone. The proof is a complete restore status plus structural and
browser read-back.

## Guarded Removal of an Accidental Empty Project

Before `POST /projects/delete`:

1. Read the candidate project and require exact UUID and expected empty-project
   name.
2. Confirm it is not the source or intended full clone.
3. Confirm the project is actually empty through project-scoped inventory.
4. Obtain separate approval for that UUID.
5. Send only the official `{ "uuid": "<candidate-uuid>" }` payload.
6. Read the project list back and verify only the candidate disappeared.

Never broaden a deletion selector to a name prefix such as `*_v2`.
