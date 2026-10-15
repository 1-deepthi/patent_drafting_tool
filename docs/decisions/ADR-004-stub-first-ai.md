# ADR-004: Stub-first AI drafting with optional Gemini provider

## Status
Accepted

## Date
2026-10-16

## Context
Draft generation (`POST /api/patents/{id}/draft/generate`) can call an external LLM, but the project must work fully offline: local development without API keys, CI without network credentials, and tests that never touch the network (`backend/tests/conftest.py` forces `AI_PROVIDER=stub`). Generated text is a draft aid, never filed directly.

## Decision
`AI_PROVIDER=stub` is the default. The stub returns a clearly labelled placeholder plus a not-legal-advice warning and still persists a versioned `draft_sections` record, so the whole workflow is exercisable without keys. `AI_PROVIDER=gemini` with `GEMINI_API_KEY` selects the real provider (`GEMINI_MODEL`, default `gemini-2.0-flash`); `factory.get_ai_provider()` falls back to stub unless both are set.

## Alternatives Considered

### Gemini by default, stub only in tests
- Pros: real drafts out of the box.
- Cons: first run requires a key; CI needs a secret; accidental key-less calls fail confusingly instead of degrading gracefully.
- Rejected: raises the floor for contributors and breaks offline setup.

### No stub — error when unconfigured
- Pros: honest about missing capability.
- Cons: blocks the entire draft workflow (versions, documents UI, agent walkthroughs) for anyone without a key.
- Rejected: the workflow, not just the prose, is what needs testing.

## Consequences
- Placeholder content must stay obviously non-final; the warning travels with every stub response.
- Provider selection is a Strategy (`app/services/ai/`); adding a provider means a new module + factory branch, no endpoint changes.
- Never commit `GEMINI_API_KEY`; rotation procedures in `SECURITY.md` apply.
