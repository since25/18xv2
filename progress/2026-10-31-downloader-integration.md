# 2026-10-31 Downloader integration

## What was done

- Added the first persistence layer for RN downloader integration: remote package snapshots, whitelist match candidates, submission attempts, task snapshots, and sync runs.
- Added Alembic revision `20261031_0011` and registered the models for migrations and test databases.
- Added model constraints for package identity, candidate identity, submission idempotency, and remote task identity.

## Testing

- `.venv/bin/pytest tests/downloader/test_models.py -q` — 2 passed.
- `.venv/bin/pytest tests/test_migrations.py -q` — 2 passed.

## Notes

- Changed files: `app/models/downloader.py`, `alembic/versions/20261031_0011_downloader_integration.py`, `alembic/env.py`, `tests/conftest.py`, `tests/downloader/test_models.py`.
- Rollback: run the Alembic downgrade for revision `20261031_0011`; no production database was contacted.

## Task 2 — HTTP client

### What was done

- Added configurable RN downloader endpoint, password, timeout, node key, and sync interval settings.
- Implemented a short-lived authenticated HTTP client that logs in, obtains a CSRF token, reads packages/tasks/dashboard, submits exact package batches, and controls pause/resume/cancel/retry.
- Remote errors are mapped to safe codes without exposing the configured password.

### Testing

- `.venv/bin/pytest tests/downloader/test_client.py -q` — 3 passed using `httpx.MockTransport`.

### Notes

- Changed files: `.env.example`, `app/core/config.py`, `app/services/downloader/__init__.py`, `app/services/downloader/client.py`, `tests/downloader/test_client.py`.
- Rollback: remove the new settings and downloader client files; no remote calls were made.

## Task 3 — package matching and task persistence

### What was done

- Added package synchronization with stable-boundary filtering, active whitelist/alias matching, and active blacklist exclusion.
- Added candidate selection lifecycle, exact package submission with idempotency keys, and local submission records.
- Added task and current-file progress snapshot upsert with safe JSON persistence.

### Testing

- `.venv/bin/pytest tests/downloader/test_sync_service.py -q` — 2 passed with a fake downloader.

### Notes

- Changed files: `app/services/downloader/sync_service.py`, `tests/downloader/test_sync_service.py`.
- Rollback: remove the service and test files; persistence tables remain independently removable through the migration downgrade.

## Task 4 — protected API routes

### What was done

- Added `/downloader` routes for status, package sync/list/select, exact batch submission, task snapshots, task sync, pause/resume, cancel, and retry.
- Registered the router in `app.main`; all routes inherit the existing authentication middleware.
- Mapped remote transport/auth failures to a safe 502 contract and invalid local state to 409.

### Testing

- `.venv/bin/pytest tests/api/test_downloader_routes.py -q` — 2 passed with a fake client and isolated database.

### Notes

- Changed files: `app/schemas/downloader.py`, `app/api/routes/downloader.py`, `app/main.py`, `tests/api/test_downloader_routes.py`.
- Rollback: remove the router include and the new route/schema files; no external service was contacted.

## Task 5 — downloader workbench

### What was done

- Added the React API wrapper and `/downloader` page.
- Added package candidate search, whitelist match display, local selection persistence, explicit confirmation/download action, task progress table, and pause/resume/cancel/retry controls.
- Registered the page in the main router and Workflow navigation.

### Testing

- `npm --prefix frontend test -- --run src/pages/DownloaderPage.test.tsx` — 1 passed.
- `npm --prefix frontend run build` — passed.
- Targeted ESLint for the new downloader files — passed with 0 errors.
- Full frontend lint still reports pre-existing errors in `EmbyMediaActionsPage.tsx` and `ReviewIntakePage.tsx`.

### Notes

- Changed files: `frontend/src/api/downloader.ts`, `frontend/src/pages/DownloaderPage.tsx`, `frontend/src/pages/DownloaderPage.test.tsx`, `frontend/src/App.tsx`, `frontend/src/layout/navigation.tsx`.
- Rollback: remove the page/API files and the route/navigation entries; no remote service was contacted.

## Task 6 — periodic synchronization

### What was done

- Added a lifespan-owned RN downloader sweeper that starts only when `DOWNLOADER_ENABLED=true` and `DOWNLOADER_BASE_URL` is configured.
- The sweeper performs package/task synchronization only; it never creates download batches automatically and shuts down cleanly with the app.

### Testing

- `.venv/bin/pytest tests/downloader/test_lifespan_sync.py -q` — 1 passed.
- `.venv/bin/pytest tests -q` — 352 passed.
- `npm --prefix frontend test` — 8 files / 21 tests passed.
- `npm --prefix frontend run build` — passed.
- `git diff --check` — passed.
- Post-review regression check: `.venv/bin/pytest tests/downloader tests/api/test_downloader_routes.py -q` — 10 passed; frontend build rerun successfully after the final client error mapping adjustment.

### Notes

- Changed files: `app/main.py`, `tests/downloader/test_lifespan_sync.py`.
- Rollback: remove the sweeper helper/task block; the integration remains manual-only through the protected routes.

## Final verification

### What was done

- Completed the whitelist → package candidate → explicit package submission → task progress workflow.
- Added user-facing configuration and development documentation.
- Kept production RN access disabled by default and did not deploy or mutate external state.

### Testing

- Backend: `.venv/bin/pytest tests -q` — 352 passed.
- Frontend: `npm --prefix frontend test` — 8 files / 21 tests passed.
- Frontend build: `npm --prefix frontend run build` — passed.
- New-file ESLint: downloader frontend files passed with 0 errors.
- Full frontend lint retains two pre-existing errors in `EmbyMediaActionsPage.tsx` and `ReviewIntakePage.tsx`; they are outside this change.
- Static checks: `python3 -m compileall -q app`, `git diff --check` — passed.
- Migration smoke test: `DATABASE_URL=sqlite:///tmp-test .venv/bin/alembic upgrade head` on a disposable SQLite file — passed through `20261031_0011`.

### Notes

- Changed files: see `git status --short`; no Git commit, push, deployment, or production RN request was performed.
- Rollback: disable `DOWNLOADER_ENABLED`, remove the downloader router/page, and run Alembic downgrade for `20261031_0011` if the schema must be removed.
