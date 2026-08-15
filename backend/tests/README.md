# Backend test suite

Automated regression tests, added to close open item #8 from
`Project_Handover_v10.md`. 51 tests across 10 files, ~45-50s total.

## One-time setup

```bash
# From backend/, with the venv already set up per the main setup steps:
psql -U postgres -h localhost -c "CREATE DATABASE patent_platform_test;"
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/patent_platform_test \
    alembic upgrade head
```

The suite seeds its own roles/permissions on first run (`seed_once` fixture
in `conftest.py`, session-scoped) — you do NOT need to run `python -m
app.seed` against the test database yourself.

## Running

```bash
pytest                      # everything
pytest tests/test_files.py  # one file
pytest -v                   # verbose, one line per test
pytest -k reject            # only tests matching "reject"
```

`conftest.py` forces `AI_PROVIDER=stub` and `STORAGE_PROVIDER=local`
regardless of what your local `.env` has set, so the suite never
accidentally makes a real network call to Gemini or R2 — it's fully
offline-safe.

## What's covered

- **`test_auth.py`** — dev-login for all 4 roles, per-email idempotency,
  RBAC enforcement, unauthenticated rejection.
- **`test_assignment_workflow.py`** — the full assign / reject / reassign /
  accept state machine, including cross-agent authorization and the
  Draft-vs-Under-Review assignment gating. This is the flow that was
  manually click-tested via Playwright in `Project_Handover_v10.md` §7.12;
  it's now checked on every run instead of only when someone remembers to
  click through it by hand.
- **`test_files.py`** — upload/list/download/delete round-trip with an
  actual byte-for-byte content check, blocked-extension rejection,
  visibility enforcement. Also encodes the §7.12 manual test.
- **`test_document_generation.py`** — full AI-draft + PDF/DOCX generation
  pipeline. `test_generate_pdf_document_end_to_end` directly re-exercises
  `run_generation_job()` in `app/services/document_service.py` — the exact
  function that had a real `NameError` bug, found only by a live browser
  session in `Project_Handover_v9.md` §7.11 (masked in the browser as an
  unrelated-looking CORS error). This test was verified to actually catch
  that bug: temporarily reintroducing an equivalent `NameError` made it
  fail loudly in under 4 seconds, instead of requiring a multi-step manual
  Playwright session to discover.
- **`test_admin_rbac.py`** — Pending Approvals (including the "select at
  least one role" validation), approve/reject, the Role & Permission
  Matrix (listing, toggling a grant), assign/revoke role for a user, and
  the Super-Admin-only authorization boundary (confirms plain Admin is
  correctly excluded from every RBAC-management endpoint). Encodes the
  §7.12 manual Admin/Super-Admin test. Since dev-login always creates
  `Approved` accounts, a genuinely `Pending` user needed a raw-SQL insert
  helper (`tests/helpers.py`'s `create_pending_user`) — same workaround
  the manual Playwright session used.
- **`test_comments.py`** — create/list round-trip (visible to both the
  innovator and the assigned agent, ordered oldest-first), visibility
  enforcement for an unrelated agent, the append-only design (no
  PATCH/DELETE route for an individual comment), empty-comment-text
  validation, and that posting a comment fires a `CommentAdded`
  notification to the *other* participant but never to the author (open
  item #28). Closes the "Comments" gap flagged in earlier revisions of
  this README.
- **`test_calendar.py`** — assigned-agent create/list/delete round-trip,
  the innovator-cannot-manage-events authorization boundary (only the
  assigned agent or an Admin/Super Admin may create/delete — the
  innovator can still list), invalid `event_type` rejection, and the
  cross-patent `/api/calendar/events` "my upcoming events" view scoped
  correctly per agent. Closes the "Calendar" gap flagged in earlier
  revisions of this README.
- **`test_notifications.py`** — list + unread-count, mark-one-read,
  mark-all-read, and cross-user isolation (a user can't read or mark read
  another user's notification, even with a known id). Reuses the
  comment-notification path from `test_comments.py` as a convenient real
  trigger. **Gotcha worth flagging for whoever extends this further**: the
  assign step itself fires an "Assigned" notification to the agent
  (`app/services/patent_service.py`), so any test that does an
  assign-then-accept setup and then checks notification counts starts
  from a baseline of 1, not 0 — my first draft assumed a clean inbox and
  had to be corrected to read the baseline and assert deltas instead of
  hardcoded absolutes. Not a bug, just a wrong assumption on my part;
  worth remembering before writing the next notification-adjacent test.
- **`test_document_generation_retry.py`** — closes open item #36. Adds
  `AlwaysFailStorageProvider` (`tests/helpers.py`) — a `StorageProvider`
  test double that always raises `StorageError` — and monkeypatches it
  into `app.api.documents.get_storage_provider` for exactly one call, to
  deterministically force a genuinely `Failed` document-generation job.
  This doesn't change any production code; it just gives tests a
  reliable way to trigger the existing, already-correct `StorageError ->
  Failed job` path in `run_generation_job()`. Covers both the actual
  "retry creates a new job that succeeds once storage works again" path
  (previously untested — flagged explicitly in
  `test_retry_is_rejected_for_a_completed_job`'s docstring) and the
  "retry against still-broken storage also comes back Failed, not forced
  to Completed" contract. Verified effective the same way
  `test_generate_pdf_document_end_to_end` was in §7.13: temporarily broke
  `retried_from_job_id` propagation in `app/api/documents.py`, confirmed
  both new tests failed loudly, then restored the file and confirmed all
  42 tests pass again.
- **`test_templates.py`** — closes open item #31 ("in-UI placeholder
  validation for Templates") and, along the way, adds the first test
  coverage at all for `app/api/templates.py` (upload/activate/delete/RBAC/
  document-type validation — none of it was automated before this file).
  Backend addition: `validate_template_placeholders()`
  (`app/services/document_service.py`) parses an uploaded .docx with the
  same docxtpl machinery the real merge uses and diffs its Jinja
  variables against the known set (`TITLE`, `WATERMARK_TEXT`, plus
  `SECTION_TYPES`) — surfaced only on the upload response itself
  (`TemplateOut.unknown_placeholders` / `.unused_known_placeholders` /
  `.template_parse_error`, all `None` on every other read) and shown as a
  dismissible warning banner in `TemplatesPanel.tsx`. This never blocks
  the upload — a bad template must still never take document generation
  down, per `build_docx_bytes()`'s own existing design; it only tells the
  admin sooner than "check the generated PDF and notice the section is
  missing."

  **A real repeatability bug this file surfaced**: `templates` was
  missing from `conftest.py`'s `_DATA_TABLES` truncation list, so
  Template rows silently accumulated across every test run in the same
  session — directly violating `clean_data_tables`'s own docstring
  promise ("all business-data tables... so tests never depend on
  ordering or leak state"). My first version of
  `test_new_upload_deactivates_previous_active_version` assumed a clean
  slate and asserted `version_number == 1`; it failed with `version_number
  == 4` because three earlier tests in the same file had already
  uploaded templates for the same `document_type` that were never
  cleaned up. Fixed by adding `"templates"` to `_DATA_TABLES` — not a
  fix to my test's assumption, an actual gap in the shared test
  infrastructure. Confirmed by running the full 51-test suite twice in a
  row afterward, both green.

## What's NOT covered yet (good next additions)

- Questionnaire save/submit validation rules (open items #9, #10 in the
  handover — still unconfirmed with the user, so no test encodes a
  specific answer yet).
- Any real (non-stub) Gemini or R2 test — blocked on missing credentials,
  see handover open items #15/#23.
- Fault-injection for a genuinely `Failed` document generation job (see
  the note in `test_retry_is_rejected_for_a_completed_job` — retry's
  "creates a new job" behavior is documented in the code but not asserted
  here, since nothing in this suite can currently force a real failure).

## Design notes for whoever extends this

- **Test isolation**: `conftest.py`'s `clean_data_tables` fixture
  `TRUNCATE`s all business-data tables after every test. Roles/permissions/
  users are NOT truncated — dev-login is idempotent per email, so tests
  create their own throwaway users freely without needing to clean them up.
  **Use a unique email per test** (or per scenario) to avoid any risk of
  cross-test interference, even though truncation resets IDs.
- **NullPool is load-bearing.** Do not remove the `poolclass=NullPool`
  override in `conftest.py` — without it, connections get bound to
  whichever pytest-asyncio event loop first touched them, causing
  `InterfaceError`/`RuntimeError` ("attached to a different loop") flakes
  as soon as more than one test runs. This is a common pain point with
  async SQLAlchemy + pytest-asyncio and cost real time to track down; see
  the comment in `conftest.py` for the full explanation.
- **Build fixtures through the real API** (`tests/helpers.py`'s
  `create_submitted_patent`), not direct DB inserts, wherever the
  mechanics being set up are also part of what's worth checking. This is
  the same standard the manual Playwright sessions held themselves to.
  Direct DB manipulation is still fine (and used) for state that dev-login
  genuinely can't produce, like a `Pending` (not auto-`Approved`) user —
  but **make any such direct-insert helper idempotent** (upsert on the
  natural key, e.g. email), same as dev-login already is. The `users`
  table is deliberately not truncated between tests, so a plain INSERT
  helper will throw a duplicate-key error the second time the suite runs
  in the same test-database session — this actually happened once while
  building `test_admin_rbac.py` (`create_pending_user`'s first version)
  and was caught by simply running the full suite twice in a row, which
  is worth doing as a matter of habit after adding any test that creates
  its own users directly.
