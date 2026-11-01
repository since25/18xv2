# RN Downloader Incremental History Implementation Plan

> **For agentic workers:** When implementation is authorized, execute task-by-task in the current session by default. Use subagent-driven-development only when delegation is explicitly enabled and available. A plan-only request ends with this plan. Steps use checkbox (`- [x]`) syntax.

**Goal:** Generate a new 18x candidate for each stable RN package revision, submit only newly available media in incremental mode, and persist task/file history in 18x.

**Architecture:** Extend the existing 18x package/candidate/submission models with revision and mode fields, add append-only task and file history tables, and keep the current latest snapshot tables for fast UI reads. Extend RN's HTTP batch endpoint with an optional incremental mode that filters out messages from previously completed package attempts; old callers keep full mode.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, httpx, React, Flask, SQLite, pytest, Vitest.

## Global Constraints

- Use HTTP between 18x and RN; do not share or directly open RN SQLite from 18x.
- Keep whitelist candidate generation and explicit user confirmation.
- Only stable packages are candidates; active blacklist terms exclude them.
- Incremental mode excludes only messages from prior fully completed package attempts.
- Preserve existing full-download API behavior for callers that omit `mode`.
- Do not deploy, push, or mutate production data during tests.

---

### Task 1: Extend the 18x schema for revisions and history

**Files:**
- Modify: `app/models/downloader.py`
- Create: `alembic/versions/20261031_0014_downloader_incremental_history.py`
- Modify: `alembic/env.py` only if new models need registration
- Test: `tests/downloader/test_models.py`

**Interfaces:**
- `DownloaderPackage.completed_revision: int | None`
- `DownloaderPackageCandidate.package_revision: int`
- `DownloaderSubmission.package_revision: int`, `download_mode: str`
- `DownloaderTaskHistory` and `DownloaderTaskFileHistory` append-only rows

- [x] **Step 1: Add failing model tests** for revision uniqueness, task history/file history persistence, and submission mode defaults.
- [x] **Step 2: Run `.venv/bin/pytest tests/downloader/test_models.py -q`; confirm the new fields/models fail before implementation.**
- [x] **Step 3: Add the models and migration.** Backfill candidate revisions from their package `index_revision`; preserve existing candidate rows and change uniqueness to include `package_revision`; default existing submission mode to `full`.
- [x] **Step 4: Run focused model and migration tests using a disposable SQLite database.**
- [x] **Step 5: Append the migration and rollback details to `progress/2026-10-31-downloader-incremental-history.md`.**

### Task 2: Make package matching revision-aware

**Files:**
- Modify: `app/services/downloader/sync_service.py`
- Modify: `app/schemas/downloader.py`
- Test: `tests/downloader/test_sync_service.py`

**Interfaces:**
- `sync_packages` creates one candidate per `(package, whitelist entry, index_revision)`.
- Candidate payloads include `package_revision` and `completed_revision`.

- [x] **Step 1: Add a failing test** where revision 3 is completed and revision 4 adds media; the second sync must create a new pending candidate while preserving the revision-3 candidate.
- [x] **Step 2: Run the focused test and confirm it fails because successful packages are currently excluded.**
- [x] **Step 3: Match a package when it is stable, unblocked, and either has no successful attempt or its current revision exceeds `completed_revision`; dismiss only pending/selected candidates from older revisions.**
- [x] **Step 4: Add tests for a title-only revision with no new media and for blacklist exclusion across revisions.**
- [x] **Step 5: Run `.venv/bin/pytest tests/downloader/test_sync_service.py -q`.**

### Task 3: Add RN incremental batch mode

**Files:**
- Modify: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/module/channel_library_store.py`
- Modify: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/module/channel_library_service.py`
- Modify: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/module/web.py`
- Modify: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/module/channel_library_store.py` schema version and migration block
- Test: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/tests/module/test_channel_library_store.py`
- Test: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/tests/module/test_channel_library_web.py`

**Interfaces:**
- `POST /api/packages/{package_id}/download-batch` accepts optional `{ "mode": "full" | "incremental" }`.
- Existing omitted mode remains `full`.
- Incremental mode creates no batch and returns `no_new_items` when all current messages were in prior completed attempts.

- [x] **Step 1: Add failing RN tests** for a package revision with 2 previously completed messages plus 18 new messages; assert the incremental batch contains 18 item snapshots, and assert the no-new-items response does not create a batch.
- [x] **Step 2: Run those tests and confirm the current endpoint rejects the body or includes all 20 messages.**
- [x] **Step 3: Add `download_mode` to the RN batch table with schema-version migration, thread it through store/service, and filter current item rows against prior completed package attempts when mode is incremental.**
- [x] **Step 4: Update the endpoint to validate `mode`, map no-new-items to a stable JSON error/result, and keep full mode behavior unchanged.**
- [x] **Step 5: Run the focused RN tests and the existing channel-library download/web suites.**

### Task 4: Submit revision candidates through incremental mode

**Files:**
- Modify: `app/services/downloader/client.py`
- Modify: `app/services/downloader/sync_service.py`
- Modify: `tests/downloader/test_client.py`
- Modify: `tests/downloader/test_sync_service.py`

**Interfaces:**
- `DownloaderClient.submit_package(package_id, idempotency_key, mode="incremental")` sends a JSON mode body.
- Idempotency key becomes `18x:{node}:package:{remote_id}:r{revision}:incremental`.

- [x] **Step 1: Add failing HTTP and service tests** for the mode body, revision key, and `no_new_items` mapping.
- [x] **Step 2: Run focused tests and confirm the current client sends no JSON mode and uses a revision-only key.**
- [x] **Step 3: Implement mode submission, persist `package_revision` and `download_mode`, and mark no-new-items candidates/submissions explicitly without creating a remote task.**
- [x] **Step 4: Run client and sync-service tests.**

### Task 5: Persist task and file history

**Files:**
- Modify: `app/services/downloader/sync_service.py`
- Create/modify: `app/api/routes/downloader.py`
- Modify: `app/schemas/downloader.py`
- Modify: `frontend/src/api/downloader.ts`
- Modify: `frontend/src/pages/DownloaderPage.tsx`
- Test: `tests/downloader/test_sync_service.py`
- Test: `tests/api/test_downloader_routes.py`
- Test: `frontend/src/pages/DownloaderPage.test.tsx`

**Interfaces:**
- `GET /api/downloader/tasks/{task_id}/history?limit=100` returns changed task snapshots with nested file snapshots.
- Repeated identical remote payloads append no duplicate history row.

- [x] **Step 1: Add failing backend tests** for changed/unchanged task payloads and file history rows.
- [x] **Step 2: Run focused backend tests and confirm history is currently absent.**
- [x] **Step 3: Hash canonical task payloads, append only changed histories, persist all returned file rows, and preserve the current latest snapshot upsert.**
- [x] **Step 4: Add the history route and a task-row detail view in the downloader page.**
- [x] **Step 5: Run backend focused tests, frontend tests, targeted ESLint, and the production frontend build.**

### Task 6: Full verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Create: `progress/2026-10-31-downloader-incremental-history.md`

- [x] **Step 1: Document revision candidates, incremental mode, history endpoints, and the no-new-items result.**
- [x] **Step 2: Run `.venv/bin/pytest tests -q`, the RN focused suite, `npm --prefix frontend test`, `npm --prefix frontend run build`, `python3 -m compileall -q app`, and `git diff --check`.**
- [x] **Step 3: Inspect the final diff and migration heads; record exact verification output and rollback instructions.**
