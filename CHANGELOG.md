# Changelog

All notable public, stand-agnostic changes are recorded here. Private overlay
evidence, stand profiles, customer data and credentials are intentionally not
part of this changelog or repository.

Release tags use Semantic Versioning. Local development builds may append a
single `+codex.<cachebuster>` identifier without changing the release line.

## [0.5.0] - 2026-08-21

### Added

- Structured capability planning with Direct, Coordinated and read-only
  Discovery routes and no numeric limit on selected KS areas.
- Phase-scoped adaptive context packs bound to task plans and resource hashes.
- Compact resumable handoffs that preserve facts, unknowns, approvals,
  artifacts and verification state without raw responses.
- Bounded private knowledge retrieval and knowledge-card lifecycle 1.1 with
  applicability, freshness, rejected hypotheses, supersession and promotion
  evidence.
- Execution receipts that bind plans, executor reports and persisted artifact
  hashes without authorizing execution or retry.
- Product-shaped patterns for health reports, lineage and impact maps,
  interface-event diagrams, parity checks, constructors, incidents, iframe
  session isolation and safe repair packs.

### Changed

- Detailed resources load only for the active phase while the complete task map
  remains available for coordination.
- Natural-language interpretation remains with Codex; deterministic scripts
  validate structured selections and actual endpoint/payload effects instead
  of maintaining a custom keyword or morphology layer.
- Private knowledge retrieval defaults to bounded, current, verified evidence;
  stale or review-due evidence requires explicit inclusion.
- Offline project comparison fails closed when either snapshot contains
  collection errors instead of inferring missing or extra entities from partial
  evidence.
- Dashboard audits separate structural risks from cells that require browser
  DOM, console and network verification, including dynamic iframes.
- Backup guidance distinguishes immutable zstd restore artifacts from
  decompressed JSON inspection copies and strengthens restore read-back checks.
- Portable builds validate declared resources, reject generated knowledge
  databases and verify release metadata against the plugin version.

### Security

- Planning, handoff, retrieved knowledge and receipt artifacts are explicitly
  non-authorizing and cannot lower execution gates.
- Lifecycle promotion requires independent review, public-redaction review,
  evidence hashes and resolved unknowns.
- Receipt artifact paths reject traversal, absolute paths and symlink
  components before hashing.
- Incomplete snapshot comparisons return a non-zero status and cannot be used
  to authorize restore, write, cleanup or deletion.

## [0.4.0] - 2026-08-19

### Added

- Session-scoped dynamic IFRAME routing through KS dashboard variables.
- Portable HTML, button-action and IFRAME-cell templates.
- Multi-user external web-service contract and isolation checklist.
- Safe full-project clone/restore guidance and guarded accidental-clone removal.
- Semantic relationship normalization and optional formula-dependency layer.

### Changed

- Both skills route the new workflows to dedicated references.
- README installation instructions, release notes and version policy point to
  `v0.4.0`.
- Plugin metadata exposes the new capabilities and starter prompts.

## [0.3.0] - 2026-07-16

### Added

- Capability-gated KS project writes and exact-approved runtime flows.
- Portable KS backup to Diagramm JSON round-trip tooling.
- Safe restore/read-back guidance and expanded Russian documentation.

[0.5.0]: https://github.com/seroja01ajores/knowledge-space-codex-toolkit/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/seroja01ajores/knowledge-space-codex-toolkit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/seroja01ajores/knowledge-space-codex-toolkit/releases/tag/v0.3.0
