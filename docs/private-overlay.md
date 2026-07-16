# Public core and private overlay

Use two separate trust zones.

## Public core

The public repository contains portable skills, scripts, redacted references,
synthetic tests and release tooling. It must work without knowledge of any
particular KS stand.

## Private overlay

Keep these outside the public repository:

- stand profiles and project aliases;
- Keychain/secret-manager references and credential rotation notes;
- real API/UI captures, HAR files and screenshots;
- project snapshots, diffs, evaluation results and learned evidence;
- customer/course backups and Diagramm artifacts produced from them;
- organization-specific endpoint observations and rollback runbooks.

Credentials themselves should remain in Keychain, environment injection or an
approved secret manager, not in overlay Markdown or Git history.

## Recommended layout

```text
knowledge-space-codex-private/
  core.lock.json              # pinned public repository commit and version
  stand-profiles/             # non-secret aliases plus secret references
  learned-evidence/           # redacted captures and comparisons
  project-runs/               # ignored backup/diagram run directories
  runbooks/                   # organization-specific verified procedures
```

Pin the public core by commit. Upgrade it in a review branch, run public tests
plus private synthetic/evaluation tests, then update `core.lock.json`. Never
copy the private overlay into the plugin release directory.

## Continuity rule

Publishing a new public core must not delete, rewrite or make public the
existing private repository. Before any repository rename or visibility
change, create and verify a private full-history Git bundle and retain the
original private remote under a distinct name.

