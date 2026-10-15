# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once releases begin.

## [Unreleased]

### Added

- Full open-source documentation set: detailed `README.md`, `CONTRIBUTING.md`, Contributor Covenant `CODE_OF_CONDUCT.md`, `SECURITY.md`, `ACCESSIBILITY.md` (WCAG 2.2 AA target), `SUPPORT.md`, and `docs/` guides (`GETTING_STARTED`, `ARCHITECTURE`, `API_OVERVIEW`, `DEVELOPMENT`, `DOCKER`).
- GitHub community health files: PR template, bug/feature/docs issue forms, `config.yml`, `CODEOWNERS`, `dependabot.yml`, Discussions-ready links.
- CI/CD: `ci.yml` (backend compile + pytest, frontend lint + build on `ubuntu`/`windows`/`macos`), `docker.yml` (backend + frontend image builds + backend `/health` smoke test), `codeql.yml` (CodeQL for Python + JavaScript).
- Apache-2.0 `LICENSE` with `SPDX-License-Identifier` notice.
- Root `.editorconfig`, `.nvmrc` (Node 20), `backend/.python-version` (3.13), hardened root `.gitignore`.

### Changed

- `README.md` rewritten from a one-line stub to a complete product, setup, configuration, and operations guide.
- `DEPLOYMENT.md` retained as the production deployment reference; linked from README and `docs/` instead of duplicated.

### Known gaps (tracked, not yet fixed — no code changes in this release)

- Backend is dual-stack: active Firebase routers (`auth`, `resources`) vs unmounted legacy Postgres/SQLAlchemy code (`models/`, `alembic/`, 13 routers, `tests/`). Migration validation still required.
- `backend/tests/` target the legacy SQL API (dev-login, Postgres `TRUNCATE`) and need environment alignment for the Firebase path.
- Frontend has no unit-test runner yet; verification is `tsc` + `vite build` + manual role walkthroughs.

## [0.1.0] - 2026-10-15 (pre-revolution baseline)

Baseline inherited from prior development (see git history):

- `58362d3 Implement patent workflow, reports, testing, and deployment`
- `8232dfb Integrate Firebase backend`

Included: role-based dashboards (Innovator / Agent / Admin / Super Admin), patent assignment state machine, questionnaire + versions, stub/Gemini draft generation, DOCX generation, file uploads, comments, calendar, notifications, templates, reports, Docker images, and Compose for local full-stack testing.
