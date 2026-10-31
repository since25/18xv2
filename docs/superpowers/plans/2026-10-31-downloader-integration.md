# Downloader Integration Implementation Plan

> **For agentic workers:** When implementation is authorized, execute task-by-task in the current session by default. Use subagent-driven-development only when delegation is explicitly enabled and available. A plan-only request ends with this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect 18x_v2 to the RN Telegram downloader so 18x whitelist/blacklist rules produce reviewable package candidates, confirmed candidates create exact downloader batches, and downloader task/file progress is persisted in 18x.

**Architecture:** Add a synchronous HTTP client for the downloader Web API, SQLAlchemy models for remote package snapshots, package candidates, submission attempts, task snapshots, and sync runs, plus a service that performs idempotent synchronization and matching. Expose protected FastAPI routes and a React page for candidate review and task control; keep downloader runtime state and SQLite ownership on RN.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, httpx, Pydantic, React, Ant Design, pytest, Vitest.

## Global Constraints

- Use the existing `normalize_keyword_text` matcher and active keyword entries only.
- Match `title` with literal normalized substring semantics; blacklist matches exclude a package.
- Only stable remote packages become candidates; submissions require explicit user selection.
- Never persist downloader passwords, cookies, or raw authentication headers.
- Do not connect to or mutate the production RN server during tests.
- Do not perform Git operations or deployment.

---

### Task 1: Persist downloader integration state

**Files:**
- Create: `app/models/downloader.py`
- Create: `alembic/versions/20261031_0011_downloader_integration.py`
- Modify: `alembic/env.py`
- Modify: `tests/conftest.py`
- Test: `tests/downloader/test_models.py`

**Interfaces:**
- Produces SQLAlchemy models `DownloaderPackage`, `DownloaderPackageCandidate`, `DownloaderSubmission`, `DownloaderTaskSnapshot`, and `DownloaderSyncRun`.
- `DownloaderPackageCandidate` is unique on `(package_id, keyword_entry_id)` and stores `matched_term`, `match_reason`, and lifecycle `status`.

- [ ] **Step 1: Write model tests** for package/candidate uniqueness and default statuses.
- [ ] **Step 2: Run `pytest tests/downloader/test_models.py -q` and verify the new models are absent/failing.**
- [ ] **Step 3: Implement the models and Alembic revision**, importing the models from `alembic/env.py` and the shared test fixture.
- [ ] **Step 4: Run `pytest tests/downloader/test_models.py -q` and `pytest tests/test_migrations.py -q`.**
- [ ] **Step 5: Record changed files and verification in `progress/2026-10-31-downloader-integration.md`.**

### Task 2: Implement the RN downloader HTTP client

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Create: `app/services/downloader/__init__.py`
- Create: `app/services/downloader/client.py`
- Test: `tests/downloader/test_client.py`

**Interfaces:**
- `DownloaderClient(settings: DownloaderSettingsLike)` owns one `httpx.Client` per operation.
- `list_packages(cursor: str | None, page_size: int) -> dict`.
- `list_tasks() -> list[dict]`, `get_task(task_id: str) -> dict`, `get_dashboard() -> dict`.
- `submit_package(package_id: int, idempotency_key: str) -> dict`.
- `set_download_state(state: Literal["pause", "resume"]) -> dict`.
- `cancel_task(task_id: str) -> dict`, `retry_task(task_id: str) -> dict`.

- [ ] **Step 1: Add mock-transport tests** for password login, CSRF acquisition, package pagination, exact batch submission, pause/resume, cancel and retry.
- [ ] **Step 2: Run `pytest tests/downloader/test_client.py -q` and verify failure.**
- [ ] **Step 3: Add RN settings** (`DOWNLOADER_BASE_URL`, `DOWNLOADER_PASSWORD`, `DOWNLOADER_TIMEOUT_SECONDS`, `DOWNLOADER_SYNC_INTERVAL_SECONDS`, `DOWNLOADER_ENABLED`) and implement the client with safe error mapping.
- [ ] **Step 4: Run the client tests and a compile check.**
- [ ] **Step 5: Append verification to the progress log.**

### Task 3: Match packages and persist synchronization

**Files:**
- Create: `app/services/downloader/sync_service.py`
- Create: `app/schemas/downloader.py`
- Test: `tests/downloader/test_sync_service.py`

**Interfaces:**
- `DownloaderSyncService.sync_packages(db, client) -> SyncSummary`.
- `DownloaderSyncService.list_candidates(db, ...) -> tuple[list[dict], int]`.
- `DownloaderSyncService.select_candidate(db, candidate_id, selected) -> DownloaderPackageCandidate`.
- `DownloaderSyncService.submit_selected(db, client, candidate_ids) -> SubmissionSummary`.
- `DownloaderSyncService.sync_tasks(db, client) -> TaskSyncSummary`.

- [ ] **Step 1: Write tests** for canonical/alias whitelist hits, blacklist exclusion, stable-only filtering, stale candidate preservation, candidate selection, idempotent submission, and task/file snapshot upsert.
- [ ] **Step 2: Run `pytest tests/downloader/test_sync_service.py -q` and verify failure.**
- [ ] **Step 3: Implement matching with active `KeywordEntry` rows and `normalize_keyword_text`, package upsert, candidate lifecycle updates, submission records, and task snapshot syncing.**
- [ ] **Step 4: Run the focused service tests and existing keyword tests.**
- [ ] **Step 5: Append verification and rollback notes to the progress log.**

### Task 4: Expose protected FastAPI control routes

**Files:**
- Create: `app/api/routes/downloader.py`
- Modify: `app/main.py`
- Test: `tests/api/test_downloader_routes.py`

**Interfaces:**
- Implement the `/downloader` endpoints defined in the spec, using `get_settings`, `get_db`, and the service/client boundary.
- Return 502 for remote transport/auth failures and 409 for invalid candidate state or empty submissions.

- [ ] **Step 1: Write route tests** with a fake client/service for status, sync, candidate list/select, submit, task sync and control actions.
- [ ] **Step 2: Run `pytest tests/api/test_downloader_routes.py -q` and verify failure.**
- [ ] **Step 3: Implement the router, include it in `app.main`, and add startup recovery for unfinished sync runs without starting remote downloads.**
- [ ] **Step 4: Run route tests and the complete backend suite.**
- [ ] **Step 5: Append verification evidence to the progress log.**

### Task 5: Add the 18x downloader workbench

**Files:**
- Create: `frontend/src/api/downloader.ts`
- Create: `frontend/src/pages/DownloaderPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/layout/navigation.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/pages/DownloaderPage.test.tsx`

**Interfaces:**
- The page calls only `/api/downloader/*`, displays package candidates and explicit match reasons, and requires a second submit action to create remote batches.
- It shows remote task status and offers pause/resume, cancel, retry, and refresh actions.

- [ ] **Step 1: Write Vitest coverage** for package candidate rendering, select/submit flow, and task control actions.
- [ ] **Step 2: Run the focused frontend test and verify failure.**
- [ ] **Step 3: Implement the API types, page, route, navigation item, and existing visual-system styling.**
- [ ] **Step 4: Run the focused test, frontend lint, and production build.**
- [ ] **Step 5: Append UI verification and changed files to the progress log.**

### Task 6: Add periodic task synchronization and documentation

**Files:**
- Modify: `app/main.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Create: `tests/downloader/test_lifespan_sync.py`
- Create: `progress/2026-10-31-downloader-integration.md`

- [ ] **Step 1: Write a lifespan test** proving the sweeper is disabled when `DOWNLOADER_ENABLED=false` and uses a mocked client when enabled.
- [ ] **Step 2: Run the test and verify failure.**
- [ ] **Step 3: Add an asyncio sweeper that runs only package/task synchronization, never automatic downloads, and cancels cleanly on shutdown.**
- [ ] **Step 4: Run the full backend and frontend checks.**
- [ ] **Step 5: Record `What was done`, `Testing`, `Notes` with changed files and rollback instructions; leave the project inbox task in `review` if one exists.**
