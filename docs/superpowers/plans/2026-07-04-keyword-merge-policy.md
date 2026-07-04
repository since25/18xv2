# Keyword Merge Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persisted keyword merge policy so low-priority whitelist keywords only affect organize grouping when no normal whitelist keyword matches the same folder.

**Architecture:** Store `merge_policy` on `keyword_entries` with `normal` as the default and `fallback_only` for low-priority terms. Thread the field through Pydantic schemas, registry service, keyword APIs, organize-task resolution, and the React keyword management page.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, Pydantic, pytest, React, TypeScript, Ant Design, Vite/Vitest.

## Global Constraints

- Existing keywords must keep current behavior after migration by defaulting to `normal`.
- `keyword_hits` must still record every hit; filtering happens only when generating organize tasks or listing ambiguity conflicts.
- `generate_tasks_from_keyword_hits(keyword_entry_id=...)` must stay unchanged and honor explicit user selection.
- Frontend must support creating and editing keyword priority from the keyword management UI.
- Do not overwrite unrelated existing worktree changes; read current files before editing files that are already modified.

---

## File Structure

- Modify `app/models/keywords.py`: add persisted `KeywordEntry.merge_policy`.
- Create `alembic/versions/20260704_0008_keyword_merge_policy.py`: add and remove the column.
- Modify `app/schemas/keywords.py`: add `KeywordMergePolicy` literal and expose it in create/update/response models.
- Modify `app/services/keywords/registry_service.py`: accept, validate, persist, log, and batch-import merge policy.
- Modify `app/api/routes/keywords.py`: pass `merge_policy` through create/update/import routes.
- Modify `app/services/tasks/organize_task_service.py`: filter `fallback_only` entries after existing specificity resolution and before combination/conflict logic.
- Modify `tests/services/test_organize_task_service.py`: cover generated task behavior and conflict behavior.
- Modify `tests/services/test_keyword_registry.py`: cover registry create/update/import persistence.
- Modify `tests/api/test_keyword_routes.py`: cover API validation and response serialization.
- Modify `tests/test_migrations.py`: cover migration metadata for the new column.
- Modify `frontend/src/api/types.ts`: add `KeywordMergePolicy` and payload/response fields.
- Modify `frontend/src/pages/KeywordsPage.tsx`: add list tag, create selector, edit selector, and update payload.
- Add or update frontend tests near existing page/API tests if present; otherwise rely on `npm run build` typecheck.

---

### Task 1: Persist Keyword Merge Policy

**Files:**
- Modify: `app/models/keywords.py`
- Create: `alembic/versions/20260704_0008_keyword_merge_policy.py`
- Modify: `app/schemas/keywords.py`
- Modify: `app/services/keywords/registry_service.py`
- Modify: `app/api/routes/keywords.py`
- Test: `tests/services/test_keyword_registry.py`
- Test: `tests/api/test_keyword_routes.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: `KeywordEntry.merge_policy: str`
- Produces: `KeywordMergePolicy = Literal["normal", "fallback_only"]`
- Produces: `KeywordRegistryService.create_entry(..., merge_policy: str = "normal") -> KeywordEntry`
- Produces: `KeywordRegistryService.update_entry(..., merge_policy: str | None = None) -> KeywordEntry`
- Consumes: existing `normalize_keyword_text()`, `KeywordEntryCreateRequest`, `KeywordEntryUpdateRequest`, and keyword routes.

- [ ] **Step 1: Write failing registry tests**

Add tests to `tests/services/test_keyword_registry.py`:

```python
def test_create_entry_defaults_merge_policy_to_normal(db_session):
    service = KeywordRegistryService(db_session)

    entry = service.create_entry(canonical_name="口巾SANG", keyword_type="whitelist")

    assert entry.merge_policy == "normal"


def test_create_and_update_entry_persist_fallback_only_policy(db_session):
    service = KeywordRegistryService(db_session)

    entry = service.create_entry(
        canonical_name="露脸_泄密_反差_电报",
        keyword_type="whitelist",
        merge_policy="fallback_only",
    )

    assert entry.merge_policy == "fallback_only"

    updated = service.update_entry(entry.id, merge_policy="normal")

    assert updated.merge_policy == "normal"
```

- [ ] **Step 2: Write failing API tests**

Add tests to `tests/api/test_keyword_routes.py`:

```python
def test_create_keyword_accepts_merge_policy(client):
    response = client.post(
        "/api/keywords",
        json={
            "canonical_name": "露脸_泄密_反差_电报",
            "keyword_type": "whitelist",
            "merge_policy": "fallback_only",
            "aliases": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["merge_policy"] == "fallback_only"


def test_update_keyword_accepts_merge_policy(client):
    created = client.post(
        "/api/keywords",
        json={"canonical_name": "口巾SANG", "keyword_type": "whitelist", "aliases": []},
    ).json()

    response = client.patch(
        f"/api/keywords/{created['id']}",
        json={"merge_policy": "fallback_only"},
    )

    assert response.status_code == 200
    assert response.json()["merge_policy"] == "fallback_only"


def test_keyword_merge_policy_rejects_unknown_value(client):
    response = client.post(
        "/api/keywords",
        json={
            "canonical_name": "泛化词",
            "keyword_type": "whitelist",
            "merge_policy": "low",
            "aliases": [],
        },
    )

    assert response.status_code == 422
```

- [ ] **Step 3: Write failing migration test**

Extend `tests/test_migrations.py` with a metadata assertion that upgrades expose `keyword_entries.merge_policy`:

```python
def test_keyword_entries_has_merge_policy_column(alembic_engine):
    from sqlalchemy import inspect

    inspector = inspect(alembic_engine)
    columns = {column["name"]: column for column in inspector.get_columns("keyword_entries")}

    assert "merge_policy" in columns
    assert columns["merge_policy"]["nullable"] is False
```

If `tests/test_migrations.py` uses a different fixture name, adapt only the fixture call site to the existing fixture while keeping the assertion unchanged.

- [ ] **Step 4: Run tests to verify failure**

Run:

```bash
pytest tests/services/test_keyword_registry.py tests/api/test_keyword_routes.py tests/test_migrations.py -q
```

Expected: failures mention missing `merge_policy` attribute, unexpected keyword argument, or missing migration column.

- [ ] **Step 5: Add model column**

In `app/models/keywords.py`, add the field after `status`:

```python
    merge_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="normal", server_default="normal", index=True)
```

- [ ] **Step 6: Add Alembic migration**

Create `alembic/versions/20260704_0008_keyword_merge_policy.py`:

```python
"""add keyword merge policy

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "keyword_entries",
        sa.Column("merge_policy", sa.String(32), nullable=False, server_default="normal"),
    )
    op.create_index("ix_keyword_entries_merge_policy", "keyword_entries", ["merge_policy"])


def downgrade() -> None:
    op.drop_index("ix_keyword_entries_merge_policy", table_name="keyword_entries")
    op.drop_column("keyword_entries", "merge_policy")
```

- [ ] **Step 7: Add schema field and validation**

In `app/schemas/keywords.py`, add:

```python
KeywordMergePolicy = Literal["normal", "fallback_only"]
```

Add fields:

```python
class KeywordEntryCreateRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    keyword_type: KeywordType
    merge_policy: KeywordMergePolicy = "normal"
    aliases: list[str] = Field(default_factory=list, max_length=200)
    note: str | None = None


class KeywordEntryUpdateRequest(BaseModel):
    canonical_name: str | None = Field(default=None, min_length=1, max_length=255)
    keyword_type: KeywordType | None = None
    merge_policy: KeywordMergePolicy | None = None
    status: str | None = Field(default=None, max_length=32)
    note: str | None = None


class KeywordEntryBatchImportRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=500)
    keyword_type: KeywordType
    merge_policy: KeywordMergePolicy = "normal"
```

Add `merge_policy: KeywordMergePolicy` to `KeywordEntryResponse`.

- [ ] **Step 8: Thread policy through registry service**

In `KeywordRegistryService.create_entry()`, add parameter and assignment:

```python
        merge_policy: str = "normal",
```

```python
        entry = KeywordEntry(
            canonical_name=canonical_name.strip(),
            canonical_name_normalized=normalized,
            keyword_type=keyword_type,
            merge_policy=merge_policy,
            note=note,
        )
```

If an entry already exists, do not change its policy from `create_entry()`; policy changes should use `update_entry()`.

In `update_entry()`, add parameter:

```python
        merge_policy: str | None = None,
```

and update:

```python
        if merge_policy:
            entry.merge_policy = merge_policy
```

In `record_hits()`, add parameter:

```python
        merge_policy: str = "normal",
```

and pass it to `create_entry(..., merge_policy=merge_policy)`.

Include `"merge_policy": entry.merge_policy` in create/update operation log detail.

- [ ] **Step 9: Thread policy through API routes**

In `app/api/routes/keywords.py`, pass payload fields:

```python
        merge_policy=payload.merge_policy,
```

for `create_keyword()`, `update_keyword()`, `batch_import_keywords()` via `record_hits()`, and legacy `create_keyword_library_entries()` with default `"normal"`.

- [ ] **Step 10: Run backend tests**

Run:

```bash
pytest tests/services/test_keyword_registry.py tests/api/test_keyword_routes.py tests/test_migrations.py -q
```

Expected: all selected tests pass.

- [ ] **Step 11: Commit**

```bash
git add app/models/keywords.py alembic/versions/20260704_0008_keyword_merge_policy.py app/schemas/keywords.py app/services/keywords/registry_service.py app/api/routes/keywords.py tests/services/test_keyword_registry.py tests/api/test_keyword_routes.py tests/test_migrations.py
git commit -m "feat: persist keyword merge policy"
```

---

### Task 2: Apply Merge Policy To Organize Grouping

**Files:**
- Modify: `app/services/tasks/organize_task_service.py`
- Test: `tests/services/test_organize_task_service.py`

**Interfaces:**
- Consumes: `KeywordEntry.merge_policy`
- Produces: `OrganizeTaskService._apply_merge_policy(keyword_ids: set[int], entry_by_id: dict[int, KeywordEntry]) -> set[int]`
- Produces: generated organize tasks that exclude `fallback_only` keywords whenever a normal keyword remains.

- [ ] **Step 1: Write failing organize tests**

Add tests to `tests/services/test_organize_task_service.py`:

```python
def test_generate_import_hits_ignores_fallback_keyword_when_normal_keyword_matches(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("口巾SANG", "口巾SANG"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[1])
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id == keyword_ids[0]
    assert task.matched_canonical_name == "口巾SANG"
    assert "口巾SANG/专辑X" in task.target_path
    assert "露脸_泄密_反差_电报" not in task.target_path


def test_generate_import_hits_uses_fallback_keyword_when_it_is_the_only_match(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[("露脸_泄密_反差_电报", "露脸_泄密_反差_电报")],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[0])
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id == keyword_ids[0]
    assert task.matched_canonical_name == "露脸_泄密_反差_电报"
    assert "露脸_泄密_反差_电报/专辑X" in task.target_path


def test_generate_import_hits_combines_normal_keywords_after_filtering_fallback(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("A", "A"),
            ("B", "B"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[2])
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    result = OrganizeTaskService(db_session).generate_tasks_from_import_hits(import_id=import_id)

    assert result.created_count == 1
    task = result.tasks[0]
    assert task.keyword_entry_id is None
    assert task.matched_canonical_name == "A + B"
    assert "A__B/专辑X" in task.target_path
    assert "露脸_泄密_反差_电报" not in task.target_path


def test_list_ambiguous_conflicts_filters_fallback_keyword_when_normal_keywords_exist(db_session: Session):
    import_id, keyword_ids = _seed_import(
        db_session,
        hits=[
            ("A", "A"),
            ("B", "B"),
            ("C", "C"),
            ("D", "D"),
            ("露脸_泄密_反差_电报", "露脸_泄密_反差_电报"),
        ],
    )
    fallback_entry = db_session.get(KeywordEntry, keyword_ids[4])
    fallback_entry.merge_policy = "fallback_only"
    db_session.commit()

    conflicts = OrganizeTaskService(db_session).list_ambiguous_conflicts(import_id=import_id)

    assert len(conflicts) == 1
    assert conflicts[0].keywords == ["A", "B", "C", "D"]
    assert "露脸_泄密_反差_电报" not in conflicts[0].keywords
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/services/test_organize_task_service.py -q
```

Expected: new assertions fail because fallback keywords still participate in combined directories and conflicts.

- [ ] **Step 3: Add merge-policy helper**

In `OrganizeTaskService`, add:

```python
    @staticmethod
    def _apply_merge_policy(keyword_ids: set[int], entry_by_id: dict[int, KeywordEntry]) -> set[int]:
        if len(keyword_ids) <= 1:
            return keyword_ids
        normal_ids = {
            keyword_id
            for keyword_id in keyword_ids
            if entry_by_id[keyword_id].merge_policy == "normal"
        }
        if normal_ids:
            return normal_ids
        return keyword_ids
```

- [ ] **Step 4: Use helper in task generation**

In `generate_tasks_from_import_hits()`, after:

```python
            keyword_ids = self._resolve_specific_keyword_ids(source_hits)
```

add:

```python
            keyword_ids = self._apply_merge_policy(keyword_ids, entry_by_id)
```

- [ ] **Step 5: Use helper in conflict listing**

In `list_ambiguous_conflicts()`, after:

```python
            keyword_ids = self._resolve_specific_keyword_ids(source_hits)
```

add:

```python
            keyword_ids = self._apply_merge_policy(keyword_ids, entry_by_id)
```

- [ ] **Step 6: Run organize tests**

Run:

```bash
pytest tests/services/test_organize_task_service.py -q
```

Expected: all organize service tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/services/tasks/organize_task_service.py tests/services/test_organize_task_service.py
git commit -m "feat: apply keyword merge policy to organize tasks"
```

---

### Task 3: Add Frontend Priority Editing

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/KeywordsPage.tsx`

**Interfaces:**
- Consumes: backend `KeywordEntry.merge_policy`
- Produces: `KeywordMergePolicy = 'normal' | 'fallback_only'`
- Produces: create and edit forms that submit `merge_policy`

- [ ] **Step 1: Update API types**

In `frontend/src/api/types.ts`, add:

```ts
export type KeywordMergePolicy = 'normal' | 'fallback_only'
```

Add to `KeywordEntry`:

```ts
  merge_policy: KeywordMergePolicy
```

Add to `KeywordEntryCreatePayload`:

```ts
  merge_policy: KeywordMergePolicy
```

Add to `KeywordEntryUpdatePayload`:

```ts
  merge_policy?: KeywordMergePolicy
```

- [ ] **Step 2: Add frontend option constants**

In `frontend/src/pages/KeywordsPage.tsx`, import `KeywordMergePolicy` and add:

```ts
const MERGE_POLICY_OPTIONS: Array<{ label: string; value: KeywordMergePolicy; help: string }> = [
  { label: '普通', value: 'normal', help: '可参与组合目录' },
  { label: '低优先级', value: 'fallback_only', help: '仅在没有其他普通白名单命中时生效' },
]

const MERGE_POLICY_LABEL: Record<KeywordMergePolicy, string> = {
  normal: '普通',
  fallback_only: '低优先级',
}
```

- [ ] **Step 3: Include merge policy in create and update payloads**

Set create default:

```tsx
<Form
  form={createForm}
  layout="vertical"
  initialValues={{ keyword_type: 'whitelist', merge_policy: 'normal', aliases: [] }}
  onFinish={handleCreate}
>
```

In `handleCreate()`, ensure the payload includes the value:

```ts
        merge_policy: values.merge_policy ?? 'normal',
```

Update edit form type:

```ts
  const [editForm] = Form.useForm<{
    canonical_name: string
    keyword_type: KeywordEntry['keyword_type']
    merge_policy: KeywordMergePolicy
    note: string | null
  }>()
```

In `handleUpdate()`, send:

```ts
        merge_policy: values.merge_policy,
```

- [ ] **Step 4: Add create selector**

In the create form, add:

```tsx
<Form.Item
  label="整理优先级"
  name="merge_policy"
  rules={[{ required: true, message: '请选择整理优先级' }]}
>
  <Select options={MERGE_POLICY_OPTIONS.map(({ label, value }) => ({ label, value }))} />
</Form.Item>
<Text type="secondary">
  低优先级关键词只在没有其他普通白名单命中时参与整理。
</Text>
```

- [ ] **Step 5: Display policy in the table**

Inside the keyword column meta tags, add:

```tsx
<Tag color={record.merge_policy === 'fallback_only' ? 'gold' : 'default'}>
  {MERGE_POLICY_LABEL[record.merge_policy]}
</Tag>
```

- [ ] **Step 6: Populate and edit policy in modal**

Where the edit modal opens, include:

```ts
editForm.setFieldsValue({
  canonical_name: record.canonical_name,
  keyword_type: record.keyword_type,
  merge_policy: record.merge_policy ?? 'normal',
  note: record.note,
})
```

Inside the edit modal form, add:

```tsx
<Form.Item
  label="整理优先级"
  name="merge_policy"
  rules={[{ required: true, message: '请选择整理优先级' }]}
>
  <Select options={MERGE_POLICY_OPTIONS.map(({ label, value }) => ({ label, value }))} />
</Form.Item>
```

- [ ] **Step 7: Run frontend checks**

Run:

```bash
cd frontend && npm run build
```

Expected: TypeScript build succeeds.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/pages/KeywordsPage.tsx
git commit -m "feat: edit keyword merge policy in frontend"
```

---

### Task 4: Full Verification And Integration Cleanup

**Files:**
- Review: `app/models/keywords.py`
- Review: `app/schemas/keywords.py`
- Review: `app/services/keywords/registry_service.py`
- Review: `app/services/tasks/organize_task_service.py`
- Review: `frontend/src/pages/KeywordsPage.tsx`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: verified full-stack behavior and clean working tree for this feature.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
pytest tests/services/test_keyword_registry.py tests/services/test_organize_task_service.py tests/api/test_keyword_routes.py tests/test_migrations.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: build completes successfully.

- [ ] **Step 3: Run relevant broader tests**

Run:

```bash
pytest tests/api/test_keyword_routes.py tests/services/test_keyword_registry.py tests/services/test_organize_task_service.py tests/services/test_hit_rebuild_service.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Inspect generated migration order**

Run:

```bash
python -m alembic heads
```

Expected: one head exists and includes revision `0008`.

- [ ] **Step 5: Check git diff**

Run:

```bash
git diff --stat
git diff -- app/services/tasks/organize_task_service.py frontend/src/pages/KeywordsPage.tsx
```

Expected: diff only contains merge-policy related changes.

- [ ] **Step 6: Commit verification adjustments if any were made**

If Step 5 revealed small merge-policy cleanup changes, commit them:

```bash
git add app/models/keywords.py app/schemas/keywords.py app/services/keywords/registry_service.py app/services/tasks/organize_task_service.py app/api/routes/keywords.py tests/services/test_keyword_registry.py tests/services/test_organize_task_service.py tests/api/test_keyword_routes.py tests/test_migrations.py frontend/src/api/types.ts frontend/src/pages/KeywordsPage.tsx
git commit -m "test: verify keyword merge policy flow"
```

If no files changed after prior commits, skip this step.
