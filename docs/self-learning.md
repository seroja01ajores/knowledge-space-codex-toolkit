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

