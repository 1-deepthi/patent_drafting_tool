# Security Policy

## Supported versions

| Version / branch | Supported |
|---|---|
| `main` (active development) | Yes — security fixes land here first |
| Tagged releases `vX.Y.Z` (once published) | Latest tag only; older tags are not patched |
| Legacy Postgres/SQLAlchemy path in-tree | Not a supported deployment target; do not run it in production |
| Any fork or deployment with modified auth guards | Not supported — verify `require_roles` / `ProtectedRoute` are intact |

We have not yet published a stable release. Until `v1.0.0`, treat `main` as the only supported line and keep deployments updated on every merge.

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Instead, use one of these private channels:

1. **Preferred:** [GitHub Security Advisories — New draft advisory](https://github.com/auraflaa/patent_drafting_tool/security/advisories/new) (private by default).
2. **Fallback:** email **priyangshumukherjee07@gmail.com** with subject `[SECURITY] patent_drafting_tool: <short summary>`.

Include:

- Affected component and version/commit (`backend/app/api/...`, `frontend/src/...`, Docker tag).
- Steps to reproduce or proof of concept (redacted credentials).
- Impact assessment (what an attacker can read, modify, or escalate to).
- Your contact details and preferred disclosure timeline.

### What happens next

- **Acknowledgement** within **48 hours**.
- **Triage and initial assessment** within **5 business days**.
- **Fix + advisory** as fast as scope allows; we will coordinate a disclosure date with you before publishing.
- We will credit reporters in the advisory unless you ask to stay anonymous.

Reports about missing hardening without exploitability (e.g. "add header X") are welcome as regular issues — mark them `security-hardening`, not `vulnerability`.

## Scope and hardening notes

This project handles invention disclosures, identity data, and legal drafts. Treat all of it as sensitive.

Current controls (active Firebase path):

- Firebase ID-token verification with revocation check (`check_revoked=True`); role checks via `require_roles` and `is_admin`; Firestore visibility helpers restrict reads to creators/owners/members/assignees.
- Account gating: new users are `pending` until approved; bootstrap admin is a single configured email.
- Upload validation: non-empty, `MAX_UPLOAD_SIZE_BYTES` cap, `BLOCKED_UPLOAD_EXTENSIONS` deny-list.
- Transport: CORS allow-list (`CORS_ORIGINS`), trusted hosts (`ALLOWED_HOSTS`), HTTPS required in production.
- Production expectations from `DEPLOYMENT.md` §3: `ENVIRONMENT=production`, no `*` CORS, no `localhost` origins, `STORAGE_PROVIDER=r2` / Firebase bucket (never `local`), distinct ≥32-char secrets, single backend replica (in-memory rate limiting).

Known limitations (do not rely on these for security):

- Firestore Security Rules **do not** replace backend authorization — the Admin SDK bypasses them; all checks live in `app/core/security.py` and `app/services/repository.py`.
- Rate limiting is **per-process in-memory**; it is not shared across replicas.
- Generated patent text is a **draft, not legal advice**; it must not be filed without professional review.
- Service-account JSON and `.env` files are **never** committed; rotation is required if exposed (deleting a later commit is not enough — revoke the key).

## Out of scope

- Social engineering, physical attacks, or third-party services (Firebase, Google, hosting) themselves.
- Denial-of-service via traffic floods (report tuning ideas as hardening issues).
- Vulnerabilities in the archived Postgres path — note them as migration debt, not live vulnerabilities, unless the active path is also affected.

## Safe harbor

We support good-faith research: do not access other users' data, do not disrupt services, delete any data you inadvertently access, and give us reasonable time to fix before disclosure. We will not pursue legal action against researchers who follow this policy.
