# Evidence-driven self-learning

The plugin preserves a reusable learning workflow for KS behavior that is
missing or ambiguous in documentation. It does not autonomously train a model
or publish observed customer data.

## Workflow

1. **Capture** one exact UI action in an isolated scratch project. Redact auth,
   cookies, hostnames, personal data and unrelated responses.
2. **Compare** before/after API state and identify the smallest payload fields
   responsible for the behavior.
3. **Normalize** identifiers, names, timestamps and stand-specific values into
   placeholders or synthetic fixtures.
4. **Classify** endpoint and business effect using the safety model. Runtime or
   destructive behavior never inherits permission from the capture.
5. **Test** the normalized rule with offline regressions and, where necessary,
   a separately approved scratch-project check.
6. **Promote** only the sanitized stable pattern into public references or
   scripts. Keep raw evidence and uncertain hypotheses in the private overlay.

## Promotion criteria

A learned pattern is public-ready only when it:

- contains no customer data, real UUIDs, credentials, private hosts or absolute
  local paths;
- has a documented source/target entity shape and safety classification;
- separates machine checks from browser-only checks;
- includes a synthetic regression when it changes executable behavior;
- remains portable across stands or explicitly documents a version constraint.

Contradictory observations stay private until reproduced. A newer observation
does not silently overwrite a verified rule; record the compatibility boundary
and add a regression for both behaviors when possible.

## Operational artifacts

Version 0.6 keeps two portable contracts and adds an evidence lifecycle:

- `knowledge-card.schema.json` describes one bounded unit of reusable evidence;
- `ks_knowledge.py` validates cards, creates a derived local FTS5 index,
  returns compact matches, reports freshness and checks promotion readiness.

New cards use schema 1.1. It adds affected capabilities and endpoint families,
the required safety gate, rejected hypotheses, remaining unknowns, freshness
dates, independent review, redaction review and promotion evidence hashes.
Schema 1.0 remains readable but is reported as unknown freshness until migrated.

The public plugin never ships a populated knowledge database. Build the index
from the private overlay and keep the database outside the plugin directory:

```bash
python3 scripts/ks_knowledge.py validate \
  --cards-root knowledge-cards

python3 scripts/ks_knowledge.py index \
  --cards-root knowledge-cards \
  --database-root indexes \
  --database ks-experience.sqlite

python3 scripts/ks_knowledge.py search \
  --database-root indexes \
  --database ks-experience.sqlite \
  --query 'iframe does not refresh after filter change' \
  --domain dashboard-ui

python3 scripts/ks_knowledge.py lifecycle-report \
  --cards-root knowledge-cards
```

Search is evidence retrieval, not authorization. Every returned card retains
its status, scope, KS-version constraints, confidence and source hashes. Live
state and the governing safety gate must still be checked.

Search returns at most five results per pass, prefers schema 1.1 cards and
excludes review-due cards by default. Use `--include-review-due` only for
maintenance or contradiction analysis, never to silently treat stale evidence
as current. Rebuild version 1.0 derived indexes after upgrading; source cards
are not modified.

## Lifecycle

The lifecycle report is read-only and deterministic with an optional
`--as-of` timestamp. It identifies:

- fresh, review-due, unknown-freshness, unverified and superseded cards;
- legacy 1.0 cards that need migration;
- promotion-ready cards;
- exact blockers for every candidate, verified or promoted card.

Verified and promoted 1.1 cards require verifiedAt and a future reviewAfter.
Promoted cards additionally require independent review, public redaction
review and evidence hashes. Supersession targets must exist and cycles fail
validation.

No command automatically changes status, refreshes a date, promotes a card or
copies private content into the plugin.

## Vector-ready boundary

The card schema is intentionally independent of a retrieval backend. A future
private provider may combine lexical and vector ranking, but it must apply the
same metadata and access filters before returning at most five compact cards.
Embeddings and vector indexes are derived private artifacts, never public
source material or a replacement for exact identifiers and API read-back.

## Candidate handoff

A solved unfamiliar task should produce a candidate only when it contains a
reusable decision. Store a redacted problem signature, KS version and scope,
affected capabilities and endpoint families, the verified solution, rejected
hypotheses, evidence hashes, verification state, required safety gate, and
remaining unknowns.

The candidate remains private and unpromoted. Promotion requires independent
API read-back, browser evidence when material, normalization, and public
redaction review. A retrieved card cannot authorize execution.
