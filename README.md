# Knowledge Space Codex Toolkit

A portable, stand-agnostic Codex plugin for working with Knowledge Space (KS)
projects through the official API and for reviewing project architecture in an
editable diagram.

The toolkit combines two complementary workflows:

- **KS project engineering** — discovery, read-only audits, course and scratch
  project reconstruction, models, classes, indicators, formulas, objects,
  tables, dashboards, publications, Gantt, integrations, BPMS, safe writes and
  browser-assisted verification.
- **KS ↔ Diagramm round-trip** — bounded backup inspection, Diagramm schema
  1.2, all mapped indicators and attributes, per-class object counts,
  formula/indicator aggregates, source-bound change plans, cloned structural
  backup generation and isolated restore preflight.

The repository contains no fixed KS host, project UUID, customer data,
credential, token, cookie or real project backup.

## Why it is useful

| Task | Toolkit support |
| --- | --- |
| Understand an unfamiliar KS project | Read-only API snapshot plus structural and UI artifact audits |
| Recreate a training or reference project | Isolated scratch-project workflow with explicit verification |
| Repair classes, models, dashboards or publications | Dry-run plan, exact project binding, narrow writes and machine read-back |
| Work with integrations or BPMS | Separate exact-approved runtime gate; no blanket feature ban |
| See a large project as a diagram | Enriched Diagramm JSON with classes, relations, KS fields, indicators, formulas and object counts |
| Return diagram edits to KS | Source-hash-bound structural diff and cloned-backup build; no in-place overwrite |
| Learn an undocumented UI action | Redacted capture → compare → normalize → test → promote workflow |

## Safety by design

The safety layer is part of the product, not an optional checklist:

1. The stand URL and project UUID are declared in the reviewed plan and must
   exactly match the runtime environment.
2. Endpoints are canonicalized and classified by both API path and declared
   business effect.
3. Project writes, runtime actions, destructive actions and server work use
   different capability gates.
4. Project writes require read-before, one unambiguous payload source and
   non-empty machine-readable read-back checks. The reviewed `entityUuid`,
   mutation payload UUID and get-by-id verification UUID must be identical.
5. Runtime payload secrets may only come from purpose-created
   `KS_RUNTIME_PAYLOAD_*` variables and only into credential/source-connection
   fields; KS login credentials and target/action fields cannot be injected.
6. Reports redact embedded Bearer/Basic auth, credentialed URIs, JWT-like
   strings, private keys and configured secret values.
7. Local payload and output paths reject traversal, absolute paths and
   symlinks before any API side effect.
8. Backup conversion is offline. Live restore remains a separate
   exact-approved operation into a new scratch project.
9. All executable local inputs and output targets are preflighted as one batch
   before login. An uncertain network result stops the batch as
   `effect_unknown`, forbids automatic retry and triggers best-effort read-back.

See [SECURITY.md](SECURITY.md) for the threat model and approval boundaries.

## Current round-trip boundary

The read view is intentionally richer than the write profile. Diagramm can
display class structure, semantic relations, mapped KS fields/attributes,
indicators, formula provenance and object counts. The current
`structural-v0.1` write profile creates new classes and new semantic
relationships in a cloned backup.

Updates or deletes of existing entities, attribute/indicator/formula writes,
object mutations and live restore are not silently inferred from the diagram;
they remain deferred until a dedicated mapping and approval contract exists.

## Requirements

- Codex with plugin support;
- Python 3.10 or newer;
- `requests` for KS API scripts;
- `zstd` for packed KS backups;
- Node.js only for optional browser API capture.

```bash
python3 -m pip install -r plugins/knowledge-space-codex/requirements.txt
python3 plugins/knowledge-space-codex/skills/ks-codex/scripts/ks_environment_preflight.py
```

## Install

```bash
codex plugin marketplace add seroja01ajores/knowledge-space-codex-toolkit --ref main
codex plugin add knowledge-space-codex@ks-agent-local
```

After an update, refresh the marketplace entry, reinstall the plugin and start
a new Codex task so the refreshed skills are loaded:

```bash
codex plugin marketplace upgrade ks-agent-local
codex plugin add knowledge-space-codex@ks-agent-local
```

## Connect to a KS project

Supply the target only at runtime. Use either login/password or a token:

```text
KS_BASE_URL=https://<host>/api
KS_PROJECT_UUID=<project uuid>
KS_LOGIN=<login>
KS_PASSWORD=<password>
# or: KS_TOKEN=<token>
```

Keep values in the environment, Keychain or another approved secret manager.
Never commit them, source-system passwords, raw backups, snapshots or captures.

Recommended first prompt:

```text
Use $ks-codex. Run the environment preflight, verify the selected stand and
project UUID, then perform a read-only project audit. Do not write anything.
```

For a backup/diagram workflow:

```text
Use $ks-diagram-roundtrip. Work only on a copy of this backup, create a bounded
read model and Diagramm JSON, validate all artifacts and stop before live
restore.
```

## Public core and private overlay

The public plugin is reusable across KS installations. Organization-specific
stand profiles, credentials, real evidence, customer backups and learned local
patterns belong in a separate private overlay. The overlay may reference a
pinned public-core commit, but public builds never package the overlay.

This preserves the reusable capture/learning mechanism without publishing the
private material it learns from. See
[docs/private-overlay.md](docs/private-overlay.md) and
[docs/self-learning.md](docs/self-learning.md).

## Repository layout

- `plugins/knowledge-space-codex/` — canonical installable plugin;
- `plugins/knowledge-space-codex/skills/ks-codex/` — KS API/course/project skill;
- `plugins/knowledge-space-codex/skills/ks-diagram-roundtrip/` — offline diagram
  and cloned-backup skill;
- `tools/build_portable_plugin.py` — deterministic sanitized release builder;
- `docs/` — architecture, private-overlay and learning guidance.

## Validation and release

```bash
python3 tools/run_plugin_tests.py
python3 tools/test_build_portable_plugin.py
python3 tools/build_portable_plugin.py --output-dir dist
```

The release builder packages only the canonical plugin, rejects sensitive or
stand-specific artifacts and writes a deterministic ZIP, SHA-256 checksum and
JSON build report.

## Status

This toolkit is production-oriented but deliberately fail-closed. A successful
offline validation does not by itself authorize KS writes, integration runs,
backup restore or server maintenance. Those actions require the corresponding
reviewed plan, target binding and approval gate.
