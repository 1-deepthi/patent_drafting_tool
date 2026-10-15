# API overview

Base URL: `VITE_API_URL` (default `http://localhost:8000`). Interactive docs: `GET /docs`.
Auth: `Authorization: Bearer <Firebase ID token>` unless noted. All paths below are relative to the base URL.

Conventions: `ADMIN` means `ADMIN` or `SUPER_ADMIN` where helpers use `is_admin()`; `SUPER_ADMIN`-only is called out explicitly. Errors are `{detail: string}`; `204` returns no body; downloads use signed URLs or `Content-Disposition: attachment`.

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | No | Service info `{name, version, docs, health}` |
| `GET` | `/health` | No | Firestore probe; `200 ok/connected` or `503 degraded` |

## Auth (`/api/auth`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/auth/me` | Approved user | Own `users/{uid}` profile (internal `_`-keys stripped) |
| `POST` | `/api/auth/sync` | Firebase user (any status) | Merge `{full_name, phone, organization, bio}` into profile |
| `POST` | `/api/auth/logout` | Firebase user | `auth.revoke_refresh_tokens(uid)`; client must also sign out |
| `GET` | `/api/auth/pending-users` | `ADMIN` | List `account_status == pending` |
| `POST` | `/api/auth/users/{user_id}/approve` | `ADMIN` | Set `approved`, `approved_by/at` |
| `POST` | `/api/auth/users/{user_id}/reject` | `ADMIN` | Set `rejected`, `rejected_by` |

## Teams (`/api/teams`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/teams` | Approved user | Create; forces `created_by/owner_uid = uid`, `member_uids = [uid]` |
| `GET` | `/api/teams` | Approved user | List visible (admin bypass, else creator/owner/member) |
| `GET` | `/api/teams/{team_id}` | Member-visible | Owned get |
| `PATCH` | `/api/teams/{team_id}` | Owner or `ADMIN` | Update; strips `id/created_by/owner_uid/member_uids` |
| `POST` | `/api/teams/{team_id}/members` | Owner or `ADMIN` | Add `{uid \| user_id}` |
| `DELETE` | `/api/teams/{team_id}/members/{user_id}` | Owner or `ADMIN` | Remove member |

## Patents (`/api/patents`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/patents` | Approved user | Create; defaults `title`, `status/workflow_status = draft` |
| `GET` | `/api/patents` | Approved user | List visible only |
| `GET` | `/api/patents/available-agents` | `ADMIN` | Approved users with `PATENT_AGENT` in `role_codes` |
| `GET` | `/api/patents/{patent_id}` | Visible | Get one |
| `PATCH` | `/api/patents/{patent_id}` | Visible + editable | Blocked once submitted/under_review/approved for non-admin/non-agent; strips protected fields |
| `POST` | `/api/patents/{patent_id}/submit` | Owner or `ADMIN` | Set `status/workflow_status = submitted` |
| `POST` | `/api/patents/{patent_id}/assign` | `ADMIN` | Assign validated agent UID; `assignment_status = pending` |
| `POST` | `/api/patents/{patent_id}/reassign` | `ADMIN` | Same as assign with reassignment semantics |
| `POST` | `/api/patents/{patent_id}/auto-assign` | `ADMIN` | Assign least-loaded approved agent |
| `POST` | `/api/patents/{patent_id}/assignment/accept` | Assigned agent or `ADMIN` | `accepted`, workflow → `under_review` |
| `POST` | `/api/patents/{patent_id}/assignment/reject` | Assigned agent or `ADMIN` | `rejected` + reason; clears `assigned_agent_uid` |

## Patent children (generic loop + fine-grained)

Resources: `applicants`, `inventors`, `comments`, `calendar-events` (create); plus `documents`, `draft-sections`, `questionnaire-versions` (read via loop).

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/{resource}` | Visible | List by `patent_id` filter |
| `POST` | `/api/patents/{patent_id}/{applicants\|inventors\|comments\|calendar-events}` | Visible | Create; auto-sets `author_uid/created_by` |
| `PATCH` | `/api/patents/{patent_id}/{applicants\|inventors\|comments\|calendar-events}/{item_id}` | Visible (+ author check for comments) | Partial update |
| `DELETE` | `/api/patents/{patent_id}/{resource}/{item_id}` | Visible | Delete; `204` |
| `POST` | `/api/patents/{patent_id}/applicants/reorder` | Visible | `{ordered_ids: []}` → `display_order` |
| `POST` | `/api/patents/{patent_id}/inventors/reorder` | Visible | Same for inventors |

## Questionnaire (`questionnaires`, doc ID = `patent_id`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/questionnaire` | Visible | Get or `{draft, answers: {}}` default |
| `PATCH` | `/api/patents/{patent_id}/questionnaire` | Visible | Merge + `updated_by/at` |
| `POST` | `/api/patents/{patent_id}/questionnaire/submit` | Visible | `status = submitted` |
| `GET` | `/api/patents/{patent_id}/questionnaire/versions` | Visible | From `questionnaire_versions` |

## Draft / AI (`draft_sections`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/patents/{patent_id}/draft/generate` | Visible | `{section_type}` (default `summary`); stub placeholder unless `AI_PROVIDER=gemini` + key; saves versioned section; includes not-legal-advice warning |
| `GET` | `/api/patents/{patent_id}/draft` | Visible | List `draft_sections` |
| `GET` | `/api/patents/{patent_id}/draft/{section_type}/versions` | Visible | Filter by section |

Section types: `summary`, `background`, `description`, `claims`, `abstract` (see `frontend/src/lib/types.ts` `SECTION_TYPES`).

## Files (Firestore `files` + Storage)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/files` | Visible | List |
| `POST` | `/api/patents/{patent_id}/files` | Visible | Multipart upload; validates non-empty, size cap, blocked extensions; stores `patents/{pid}/files/{uuid}_{name}` |
| `GET` | `/api/patents/{patent_id}/files/{file_id}/download` | Visible | v4 signed URL (300 s) |
| `DELETE` | `/api/patents/{patent_id}/files/{file_id}` | Uploader or `ADMIN` | Delete blob + doc; `204` |

## Documents (DOCX pipeline)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/patents/{patent_id}/documents/jobs` | Visible | List generation jobs |
| `GET` | `/api/patents/{patent_id}/documents/jobs/{job_id}` | Visible | Get job |
| `POST` | `/api/patents/{patent_id}/documents/generate` | Visible | Build DOCX (basic info + questionnaire), upload, record `documents` doc; `201` |
| `POST` | `/api/patents/{patent_id}/documents/jobs/{job_id}/retry` | Visible | Re-generate same `document_type` |
| `GET` | `/api/patents/{patent_id}/documents/{document_id}/download` | Visible | Signed URL (300 s) |
| `GET` | `/api/patents/{patent_id}/documents/{document_id}/versions` | Visible | Single-entry version list |

## Notifications / calendar / templates / reports / RBAC

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/notifications` | Approved user | Own (`recipient_uid == uid`) |
| `GET` | `/api/notifications/unread-count` | Approved user | `{count}` |
| `PATCH` | `/api/notifications/{notification_id}/read` | Owner | Mark one read |
| `POST` | `/api/notifications/read-all` | Approved user | Mark all read |
| `GET` | `/api/calendar/events` | Approved user | Own (`created_by`/`owner_uid == uid`) |
| `GET` | `/api/templates` | Approved user | List |
| `GET` | `/api/templates/document-types` | Approved user | Distinct types |
| `POST` | `/api/templates` | `ADMIN` | Multipart `.docx` → `templates/{type}/{uuid}_{name}` + doc |
| `POST` | `/api/templates/{template_id}/activate` | `ADMIN` | Deactivate siblings of same `document_type` |
| `DELETE` | `/api/templates/{template_id}` | `ADMIN` | Delete blob + doc |
| `GET` | `/api/reports/dashboard` | Approved user | `{total_patents, draft, submitted, under_review}` |
| `GET` | `/api/reports` | Approved user | Static catalog (`patents`, `assignments`) |
| `GET` | `/api/reports/{report_type}` | Approved user | Patents or assigned-only; `404` otherwise |
| `GET` | `/api/reports/{report_type}/export` | Approved user | JSON + `Content-Disposition: attachment` |
| `GET` | `/api/rbac/users` | `ADMIN` | `list_docs(users)` |
| `POST` | `/api/rbac/users/{user_id}/roles` | `SUPER_ADMIN` | Add `SUPER_ADMIN\|ADMIN\|PATENT_AGENT\|INNOVATOR` to `role_codes` |
| `DELETE` | `/api/rbac/users/{user_id}/roles/{role_code}` | `SUPER_ADMIN` | Remove (fallback `INNOVATOR`) |
| `GET` | `/api/rbac/matrix` | `ADMIN` | Static stub (editable matrix not implemented in Firebase migration) |
| `GET` | `/api/reports/permissions/matrix` | `ADMIN` | Same static stub |

> Legacy routers expose parallel paths (`/api/auth/dev-login`, `/api/auth/refresh`, `/api/auth/google/*`, `/api/rbac/matrix|toggle`, …) but are **not mounted** in `app/main.py` — do not build clients against them.
