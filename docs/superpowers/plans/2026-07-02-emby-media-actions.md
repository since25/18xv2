# Emby Media Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent `emby_media_actions` workflow so IINA can submit the current Emby playback item, 18x_v2 can generate safe delete plans, and the Web UI can review metadata snapshots and apply Emby-specific actor black/white lists.

**Architecture:** Add a new backend domain with SQLAlchemy models, Pydantic schemas, focused services, FastAPI routes, IINA helper scripts, and a review page. IINA only submits context; backend creates draft plans and metadata candidates; destructive deletes run only after Web UI confirmation and only through local path guards plus the existing 115 OpenAPI client.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic Settings, pytest, React 19, Ant Design 6, Vite, IINA/mpv Lua scripting.

## Global Constraints

- New module name is `emby_media_actions`; do not merge this workflow into `review_intake`.
- IINA submits current playback context only; it must not delete files or directly mutate black/white lists.
- 115 remote deletion uses the existing `18x_v2` 115 OpenAPI client only; do not implement Alist API deletion.
- Every delete starts as a `draft` plan and requires Web UI confirmation before real deletion.
- TV scope selection happens in Web UI: `episode`, `season`, or `series`.
- Metadata intake stores a full NFO/Emby snapshot before the user chooses actors.
- Actor lists use `emby_blacklist` and `emby_whitelist`.
- Do not use inode or hardlink count to infer relationships. `inode` and `link_count` may be stored as diagnostics only.
- Local delete paths must be under configured allow-list roots. Paths outside allow-list roots are blocked and never deleted.
- macOS development uses fixtures and dry-run; real server paths are only deleted when the backend runs where those paths are mounted.
- Code comments should be Chinese when comments are needed.

---

## File Structure

- Create `app/models/emby_media_actions.py`
  - SQLAlchemy models for mappings, mapping paths, delete plans, delete items, metadata snapshots, and metadata candidates.

- Modify `app/models/__init__.py`
  - Import the new model module for test metadata creation.

- Modify `alembic/env.py`
  - Import `app.models.emby_media_actions` so autogenerate and migrations see the tables.

- Create `alembic/versions/20260702_0008_emby_media_actions.py`
  - Migration for the new tables and indexes.

- Modify `app/core/config.py`
  - Add Emby and media action settings with CSV parsing.

- Create `app/schemas/emby_media_actions.py`
  - Request and response models for intake, mappings, delete plans, metadata candidates, and actor apply operations.

- Create `app/services/emby_media_actions/strm_mapping_service.py`
  - URL normalization, STRM reading, URL-to-local-path scanning, root classification, and `/d/115_OPEN/...` path decoding.

- Create `app/services/emby_media_actions/path_guard.py`
  - Local path allow-list checks and safe file deletion helpers.

- Create `app/services/emby_media_actions/emby_client.py`
  - Small Emby API client with injectable HTTP transport for tests.

- Create `app/services/emby_media_actions/nfo_parser.py`
  - XML/NFO actor extraction and snapshot parsing helpers.

- Create `app/services/emby_media_actions/delete_plan_service.py`
  - Draft plan generation, scope expansion, dry-run, and confirmed execution.

- Create `app/services/emby_media_actions/metadata_candidate_service.py`
  - Snapshot creation and applying selected actors to keyword registry.

- Create `app/services/emby_media_actions/__init__.py`
  - Package marker and exported service names.

- Create `app/api/routes/emby_media_actions.py`
  - FastAPI route handlers.

- Modify `app/main.py`
  - Import and include the new router.

- Create `tests/emby_media_actions/test_strm_mapping_service.py`
  - Unit tests for URL normalization, path decoding, root classification, and STRM scanning.

- Create `tests/emby_media_actions/test_path_guard.py`
  - Unit tests for allowed root checks and dry-run delete behavior.

- Create `tests/emby_media_actions/test_delete_plan_service.py`
  - Service tests for draft plan creation and confirmed execution.

- Create `tests/emby_media_actions/test_metadata_candidate_service.py`
  - Service tests for NFO snapshots and actor keyword application.

- Create `tests/api/test_emby_media_actions_routes.py`
  - API tests for intake, plan detail, confirm, candidate creation, and actor apply.

- Modify `tests/conftest.py`
  - Import the new models so `Base.metadata.create_all()` includes them.

- Create `scripts/emby_media_action_shortcut.py`
  - Authenticated CLI helper used by IINA.

- Create `scripts/iina_emby_media_actions.lua`
  - IINA bindings for delete plan, blacklist candidate, and whitelist candidate.

- Create `frontend/src/api/embyMediaActions.ts`
  - Frontend API client and types for the new workflow.

- Create `frontend/src/pages/EmbyMediaActionsPage.tsx`
  - Review UI for delete plans and metadata candidates.

- Modify `frontend/src/App.tsx`
  - Add route `/emby-media-actions`.

- Modify `frontend/src/layout/navigation.tsx`
  - Add navigation item.

- Modify `frontend/src/index.css`
  - Add small layout classes for the new page, following existing panels and dense workbench style.

---

### Task 1: Models, Migration, And Settings

**Files:**
- Create: `app/models/emby_media_actions.py`
- Modify: `app/models/__init__.py`
- Modify: `alembic/env.py`
- Create: `alembic/versions/20260702_0008_emby_media_actions.py`
- Modify: `app/core/config.py`
- Modify: `tests/conftest.py`
- Test: `tests/emby_media_actions/test_models_and_settings.py`

**Interfaces:**
- Produces SQLAlchemy classes:
  - `EmbyMediaMapping`
  - `EmbyMediaMappingPath`
  - `EmbyDeletePlan`
  - `EmbyDeletePlanItem`
  - `EmbyMetadataSnapshot`
  - `EmbyMetadataCandidate`
- Produces settings fields:
  - `emby_base_url: str | None`
  - `emby_api_key: str | None`
  - `emby_media_actions_enabled: bool`
  - `emby_media_actions_strm_roots: list[str]`
  - `emby_media_actions_organized_roots: list[str]`
  - `emby_media_actions_source_roots: list[str]`
  - `emby_media_actions_delete_dry_run_default: bool`

- [ ] **Step 1: Write failing model/settings tests**

Create `tests/emby_media_actions/test_models_and_settings.py`:

```python
from __future__ import annotations

from sqlalchemy import inspect

from app.core.config import Settings
from app.db.base import Base
from app.models.emby_media_actions import EmbyDeletePlan, EmbyMediaMapping, EmbyMediaMappingPath


def test_emby_media_action_tables_are_registered() -> None:
    table_names = set(Base.metadata.tables)

    assert "emby_media_mappings" in table_names
    assert "emby_media_mapping_paths" in table_names
    assert "emby_delete_plans" in table_names
    assert "emby_delete_plan_items" in table_names
    assert "emby_metadata_snapshots" in table_names
    assert "emby_metadata_candidates" in table_names


def test_mapping_relationships_persist(db_session) -> None:
    mapping = EmbyMediaMapping(
        emby_item_id="item-1",
        emby_item_type="Movie",
        emby_title="美国队长",
        alist_url="http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv",
        alist_mount_name="115_OPEN",
        remote_provider="115",
        remote_path="/电影/a.mkv",
        remote_file_id="115-file-1",
    )
    mapping.paths.append(
        EmbyMediaMappingPath(
            path_role="source_strm",
            path="/mnt/cache/docker1/alist-strm/video/alist_mv1/a.strm",
            root_name="alist_mv1",
            root_path="/mnt/cache/docker1/alist-strm/video/alist_mv1",
            file_size=120,
            inode=11,
            link_count=1,
        )
    )
    db_session.add(mapping)
    db_session.commit()

    saved = db_session.get(EmbyMediaMapping, mapping.id)
    assert saved is not None
    assert saved.paths[0].path_role == "source_strm"
    assert saved.paths[0].link_count == 1


def test_delete_plan_defaults(db_session) -> None:
    plan = EmbyDeletePlan(
        source="iina_lua",
        emby_item_id="item-1",
        scope="movie",
        status="draft",
        summary="美国队长",
    )
    db_session.add(plan)
    db_session.commit()

    saved = db_session.get(EmbyDeletePlan, plan.id)
    assert saved is not None
    assert saved.status == "draft"
    assert saved.total_items == 0


def test_settings_parse_emby_media_action_csv_values() -> None:
    settings = Settings(
        EMBY_MEDIA_ACTIONS_STRM_ROOTS="/a,/b",
        EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS="/organized",
        EMBY_MEDIA_ACTIONS_SOURCE_ROOTS="/source-a,/source-b",
    )

    assert settings.emby_media_actions_strm_roots == ["/a", "/b"]
    assert settings.emby_media_actions_organized_roots == ["/organized"]
    assert settings.emby_media_actions_source_roots == ["/source-a", "/source-b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/emby_media_actions/test_models_and_settings.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.emby_media_actions'`.

- [ ] **Step 3: Add SQLAlchemy models**

Create `app/models/emby_media_actions.py` with declarative models. Use Chinese comments only for non-obvious safety fields:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EmbyMediaMapping(Base):
    __tablename__ = "emby_media_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    emby_item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    emby_title: Mapped[str] = mapped_column(String(512), nullable=False)
    emby_series_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    emby_season_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    emby_episode_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    alist_url: Mapped[str] = mapped_column(Text, nullable=False)
    alist_mount_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="115", index=True)
    remote_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    remote_pick_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_sha1: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    paths: Mapped[list["EmbyMediaMappingPath"]] = relationship(back_populates="mapping", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("emby_item_id", "alist_url", name="uq_emby_media_mappings_item_url"),
        Index("ix_emby_media_mappings_remote_path", "remote_provider", "remote_file_id"),
    )


class EmbyMediaMappingPath(Base):
    __tablename__ = "emby_media_mapping_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mapping_id: Mapped[int] = mapped_column(ForeignKey("emby_media_mappings.id", ondelete="CASCADE"), nullable=False, index=True)
    path_role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    root_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    mapping: Mapped[EmbyMediaMapping] = relationship(back_populates="paths")

    __table_args__ = (UniqueConstraint("mapping_id", "path", name="uq_emby_media_mapping_paths_mapping_path"),)


class EmbyDeletePlan(Base):
    __tablename__ = "emby_delete_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="iina_lua")
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["EmbyDeletePlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class EmbyDeletePlanItem(Base):
    __tablename__ = "emby_delete_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("emby_delete_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    group: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    plan: Mapped[EmbyDeletePlan] = relationship(back_populates="items")


class EmbyMetadataSnapshot(Base):
    __tablename__ = "emby_metadata_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mapping_id: Mapped[int | None] = mapped_column(ForeignKey("emby_media_mappings.id", ondelete="SET NULL"), nullable=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    nfo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    nfo_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    emby_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    actors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmbyMetadataCandidate(Base):
    __tablename__ = "emby_metadata_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_list: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    emby_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("emby_metadata_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    selected_actors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    applied_keyword_entry_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    snapshot: Mapped[EmbyMetadataSnapshot] = relationship()
```

- [ ] **Step 4: Register models in imports**

Modify `app/models/__init__.py` by adding:

```python
from app.models import emby_media_actions as emby_media_actions
```

Modify `alembic/env.py` by adding near the other model imports:

```python
import app.models.emby_media_actions  # noqa: E402, F401
```

Modify `tests/conftest.py` by adding:

```python
from app.models import emby_media_actions as _emby_media_actions_models  # noqa: F401
```

- [ ] **Step 5: Add settings**

In `app/core/config.py`, add fields to `Settings`:

```python
    # Emby media actions
    emby_base_url: str | None = Field(default=None, alias="EMBY_BASE_URL")
    emby_api_key: str | None = Field(default=None, alias="EMBY_API_KEY")
    emby_media_actions_enabled: bool = Field(default=False, alias="EMBY_MEDIA_ACTIONS_ENABLED")
    emby_media_actions_strm_roots: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_MEDIA_ACTIONS_STRM_ROOTS")
    emby_media_actions_organized_roots: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS")
    emby_media_actions_source_roots: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_MEDIA_ACTIONS_SOURCE_ROOTS")
    emby_media_actions_delete_dry_run_default: bool = Field(default=True, alias="EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT")
```

Update the existing `@field_validator` decorator so it includes the three new list fields:

```python
    @field_validator(
        "test_allowed_root_ids",
        "test_allowed_path_prefixes",
        "local_path_presets",
        "emby_media_actions_strm_roots",
        "emby_media_actions_organized_roots",
        "emby_media_actions_source_roots",
        mode="before",
    )
```

- [ ] **Step 6: Add migration**

Create `alembic/versions/20260702_0008_emby_media_actions.py` with explicit `op.create_table()` calls matching the models. Use:

```python
revision = "20260702_0008"
down_revision = "20260702_0007"
```

The downgrade must drop tables in reverse dependency order:

```python
op.drop_table("emby_metadata_candidates")
op.drop_table("emby_metadata_snapshots")
op.drop_table("emby_delete_plan_items")
op.drop_table("emby_delete_plans")
op.drop_table("emby_media_mapping_paths")
op.drop_table("emby_media_mappings")
```

- [ ] **Step 7: Run tests**

Run:

```bash
pytest tests/emby_media_actions/test_models_and_settings.py -v
```

Expected: PASS.

- [ ] **Step 8: Run migration smoke test**

Run:

```bash
DATABASE_URL=sqlite:///./data/test_emby_media_actions_migration.db alembic upgrade head
```

Expected: command exits 0 and creates the new tables.

- [ ] **Step 9: Commit**

```bash
git add app/models/emby_media_actions.py app/models/__init__.py app/core/config.py alembic/env.py alembic/versions/20260702_0008_emby_media_actions.py tests/conftest.py tests/emby_media_actions/test_models_and_settings.py
git commit -m "feat: add emby media action models"
```

---

### Task 2: STRM Mapping And Path Guard Services

**Files:**
- Create: `app/services/emby_media_actions/__init__.py`
- Create: `app/services/emby_media_actions/strm_mapping_service.py`
- Create: `app/services/emby_media_actions/path_guard.py`
- Test: `tests/emby_media_actions/test_strm_mapping_service.py`
- Test: `tests/emby_media_actions/test_path_guard.py`

**Interfaces:**
- Produces:
  - `normalize_stream_url(value: str) -> str`
  - `decode_115_open_path(url: str) -> Decoded115Path`
  - `StrmMappingService.scan_for_url(url: str) -> list[LocalStrmMatch]`
  - `PathGuard.classify(path: str) -> GuardDecision`
  - `PathGuard.delete_path(path: str, dry_run: bool) -> GuardDeleteResult`

- [ ] **Step 1: Write failing STRM mapping tests**

Create `tests/emby_media_actions/test_strm_mapping_service.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.services.emby_media_actions.strm_mapping_service import (
    StrmMappingService,
    decode_115_open_path,
    normalize_stream_url,
)


def test_normalize_stream_url_decodes_host_case_and_trailing_spaces() -> None:
    assert normalize_stream_url(" HTTP://192.168.70.138:5244/d/115_OPEN/a%20b.mkv \n") == (
        "http://192.168.70.138:5244/d/115_OPEN/a%20b.mkv"
    )


def test_decode_115_open_path() -> None:
    decoded = decode_115_open_path(
        "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a%20b.mkv"
    )

    assert decoded.mount_name == "115_OPEN"
    assert decoded.remote_path == "/电影/a b.mkv"


def test_scan_for_url_returns_source_and_organized_matches(tmp_path: Path) -> None:
    source_root = tmp_path / "alist_mv1"
    organized_root = tmp_path / "mp302_mv"
    source_root.mkdir()
    organized_root.mkdir()
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv"
    (source_root / "a.strm").write_text(url + "\n", encoding="utf-8")
    (organized_root / "a.strm").write_text(url, encoding="utf-8")
    (organized_root / "other.strm").write_text("http://example.invalid/other.mkv", encoding="utf-8")

    service = StrmMappingService(
        strm_roots=[str(tmp_path)],
        source_roots=[str(source_root)],
        organized_roots=[str(organized_root)],
    )

    matches = service.scan_for_url(url)

    assert [match.path_role for match in matches] == ["source_strm", "organized_strm"]
    assert {match.root_name for match in matches} == {"alist_mv1", "mp302_mv"}
```

- [ ] **Step 2: Write failing path guard tests**

Create `tests/emby_media_actions/test_path_guard.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.services.emby_media_actions.path_guard import PathGuard


def test_path_guard_blocks_outside_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    guard = PathGuard(allowed_roots=[str(allowed)])
    decision = guard.classify(str(outside / "a.strm"))

    assert decision.allowed is False
    assert decision.reason == "path_outside_allowed_roots"


def test_path_guard_dry_run_does_not_delete(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "a.strm"
    target.write_text("url", encoding="utf-8")

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(target), dry_run=True)

    assert result.status == "dry_run"
    assert target.exists()


def test_path_guard_real_delete_removes_file(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "a.strm"
    target.write_text("url", encoding="utf-8")

    guard = PathGuard(allowed_roots=[str(allowed)])
    result = guard.delete_path(str(target), dry_run=False)

    assert result.status == "deleted"
    assert not target.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/emby_media_actions/test_strm_mapping_service.py tests/emby_media_actions/test_path_guard.py -v
```

Expected: FAIL with missing service modules.

- [ ] **Step 4: Implement STRM mapping service**

Create `app/services/emby_media_actions/strm_mapping_service.py` with these public dataclasses and functions:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class Decoded115Path:
    mount_name: str
    remote_path: str


@dataclass(frozen=True, slots=True)
class LocalStrmMatch:
    path: str
    path_role: str
    root_name: str
    root_path: str
    file_size: int | None
    inode: int | None
    link_count: int | None


def normalize_stream_url(value: str) -> str:
    cleaned = value.strip()
    parts = urlsplit(cleaned)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


def decode_115_open_path(url: str) -> Decoded115Path:
    parts = urlsplit(normalize_stream_url(url))
    prefix = "/d/"
    if not parts.path.startswith(prefix):
        raise ValueError("stream URL is not an Alist /d/ path")
    remaining = parts.path[len(prefix):]
    mount_name, _, encoded_path = remaining.partition("/")
    if mount_name != "115_OPEN":
        raise ValueError("stream URL is not under /d/115_OPEN")
    remote_path = "/" + unquote(encoded_path).lstrip("/")
    return Decoded115Path(mount_name=mount_name, remote_path=remote_path)


class StrmMappingService:
    def __init__(self, *, strm_roots: list[str], source_roots: list[str], organized_roots: list[str]) -> None:
        self.strm_roots = [Path(item).expanduser().resolve() for item in strm_roots]
        self.source_roots = [Path(item).expanduser().resolve() for item in source_roots]
        self.organized_roots = [Path(item).expanduser().resolve() for item in organized_roots]

    def scan_for_url(self, url: str) -> list[LocalStrmMatch]:
        target = normalize_stream_url(url)
        matches: list[LocalStrmMatch] = []
        for root in self.strm_roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.strm")):
                if self._read_first_line(path) != target:
                    continue
                stat = path.stat()
                matches.append(
                    LocalStrmMatch(
                        path=str(path),
                        path_role=self._classify_path(path),
                        root_name=self._root_name(path),
                        root_path=str(self._matching_root(path) or root),
                        file_size=stat.st_size,
                        inode=stat.st_ino,
                        link_count=stat.st_nlink,
                    )
                )
        return sorted(matches, key=lambda item: (item.path_role, item.path))

    @staticmethod
    def _read_first_line(path: Path) -> str:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as file:
                return normalize_stream_url(file.readline())
        except OSError:
            return ""

    def _classify_path(self, path: Path) -> str:
        resolved = path.resolve()
        if any(self._is_relative_to(resolved, root) for root in self.source_roots):
            return "source_strm"
        if any(self._is_relative_to(resolved, root) for root in self.organized_roots):
            return "organized_strm"
        return "unknown_strm"

    def _matching_root(self, path: Path) -> Path | None:
        resolved = path.resolve()
        for root in self.source_roots + self.organized_roots + self.strm_roots:
            if self._is_relative_to(resolved, root):
                return root
        return None

    def _root_name(self, path: Path) -> str:
        root = self._matching_root(path)
        return root.name if root is not None else path.parent.name

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
```

- [ ] **Step 5: Implement path guard**

Create `app/services/emby_media_actions/path_guard.py`:

```python
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GuardDecision:
    allowed: bool
    path: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class GuardDeleteResult:
    path: str
    entry_type: str
    status: str
    error_message: str | None = None


class PathGuard:
    def __init__(self, allowed_roots: list[str]) -> None:
        self.allowed_roots = [Path(item).expanduser().resolve() for item in allowed_roots]

    def classify(self, path: str) -> GuardDecision:
        resolved = Path(path).expanduser().resolve()
        for root in self.allowed_roots:
            if self._is_relative_to(resolved, root):
                return GuardDecision(True, str(resolved), None)
        return GuardDecision(False, str(resolved), "path_outside_allowed_roots")

    def delete_path(self, path: str, *, dry_run: bool) -> GuardDeleteResult:
        decision = self.classify(path)
        if not decision.allowed:
            return GuardDeleteResult(decision.path, self._entry_type(decision.path), "blocked", decision.reason)
        if dry_run:
            return GuardDeleteResult(decision.path, self._entry_type(decision.path), "dry_run")
        if not os.path.exists(decision.path):
            return GuardDeleteResult(decision.path, "missing", "not_found", "path_not_found")
        if os.path.isdir(decision.path):
            shutil.rmtree(decision.path)
            return GuardDeleteResult(decision.path, "dir", "deleted")
        os.remove(decision.path)
        return GuardDeleteResult(decision.path, "file", "deleted")

    @staticmethod
    def _entry_type(path: str) -> str:
        if os.path.isdir(path):
            return "dir"
        if os.path.isfile(path):
            return "file"
        return "missing"

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/emby_media_actions/test_strm_mapping_service.py tests/emby_media_actions/test_path_guard.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/emby_media_actions tests/emby_media_actions/test_strm_mapping_service.py tests/emby_media_actions/test_path_guard.py
git commit -m "feat: add emby strm mapping services"
```

---

### Task 3: Emby Client And NFO Parsing

**Files:**
- Create: `app/services/emby_media_actions/emby_client.py`
- Create: `app/services/emby_media_actions/nfo_parser.py`
- Test: `tests/emby_media_actions/test_emby_client.py`
- Test: `tests/emby_media_actions/test_nfo_parser.py`

**Interfaces:**
- Produces:
  - `EmbyItemContext`
  - `EmbyClient.get_item(item_id: str) -> dict`
  - `EmbyClient.find_items_by_title(title: str) -> list[dict]`
  - `build_item_context(payload: dict) -> EmbyItemContext`
  - `parse_nfo_actors(xml_text: str) -> list[ParsedActor]`

- [ ] **Step 1: Write failing tests**

Create `tests/emby_media_actions/test_nfo_parser.py`:

```python
from __future__ import annotations

from app.services.emby_media_actions.nfo_parser import parse_nfo_actors


def test_parse_nfo_actors_extracts_names_and_roles() -> None:
    xml = """
    <movie>
      <title>测试电影</title>
      <actor><name>演员A</name><role>角色A</role><tmdbid>101</tmdbid></actor>
      <actor><name>演员B</name></actor>
    </movie>
    """

    actors = parse_nfo_actors(xml)

    assert actors[0].name == "演员A"
    assert actors[0].role == "角色A"
    assert actors[0].provider_ids["tmdb"] == "101"
    assert actors[1].name == "演员B"
```

Create `tests/emby_media_actions/test_emby_client.py`:

```python
from __future__ import annotations

from app.services.emby_media_actions.emby_client import build_item_context


def test_build_item_context_for_episode() -> None:
    payload = {
        "Id": "episode-1",
        "Type": "Episode",
        "Name": "第 3 集",
        "SeriesId": "series-1",
        "SeasonId": "season-1",
        "MediaSources": [{"Path": "/mnt/media/a.strm"}],
        "People": [{"Name": "演员A", "Type": "Actor"}],
    }

    context = build_item_context(payload)

    assert context.emby_item_id == "episode-1"
    assert context.item_type == "Episode"
    assert context.series_id == "series-1"
    assert context.primary_path == "/mnt/media/a.strm"
    assert context.actors == [{"name": "演员A", "role": None, "provider_ids": {}}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/emby_media_actions/test_emby_client.py tests/emby_media_actions/test_nfo_parser.py -v
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement NFO parser**

Create `app/services/emby_media_actions/nfo_parser.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET


@dataclass(frozen=True, slots=True)
class ParsedActor:
    name: str
    role: str | None
    provider_ids: dict[str, str]


def parse_nfo_actors(xml_text: str) -> list[ParsedActor]:
    root = ET.fromstring(xml_text)
    actors: list[ParsedActor] = []
    for actor in root.findall(".//actor"):
        name = (actor.findtext("name") or "").strip()
        if not name:
            continue
        provider_ids: dict[str, str] = {}
        tmdb_id = (actor.findtext("tmdbid") or "").strip()
        if tmdb_id:
            provider_ids["tmdb"] = tmdb_id
        imdb_id = (actor.findtext("imdbid") or "").strip()
        if imdb_id:
            provider_ids["imdb"] = imdb_id
        actors.append(
            ParsedActor(
                name=name,
                role=(actor.findtext("role") or "").strip() or None,
                provider_ids=provider_ids,
            )
        )
    return actors
```

- [ ] **Step 4: Implement Emby item context builder**

Create `app/services/emby_media_actions/emby_client.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


class HttpGetter(Protocol):
    def get(self, url: str, *, params: dict[str, str], timeout: float) -> httpx.Response:
        ...


@dataclass(frozen=True, slots=True)
class EmbyItemContext:
    emby_item_id: str
    item_type: str
    title: str
    series_id: str | None
    season_id: str | None
    primary_path: str | None
    media_sources: list[dict]
    actors: list[dict[str, object]]
    raw: dict


def build_item_context(payload: dict) -> EmbyItemContext:
    media_sources = list(payload.get("MediaSources") or [])
    primary_path = None
    if media_sources:
        primary_path = media_sources[0].get("Path")
    actors = []
    for person in payload.get("People") or []:
        if person.get("Type") != "Actor":
            continue
        actors.append(
            {
                "name": person.get("Name"),
                "role": person.get("Role"),
                "provider_ids": person.get("ProviderIds") or {},
            }
        )
    return EmbyItemContext(
        emby_item_id=str(payload["Id"]),
        item_type=str(payload.get("Type") or "Unknown"),
        title=str(payload.get("Name") or ""),
        series_id=payload.get("SeriesId"),
        season_id=payload.get("SeasonId"),
        primary_path=primary_path,
        media_sources=media_sources,
        actors=actors,
        raw=payload,
    )


class EmbyClient:
    def __init__(self, *, base_url: str, api_key: str, http_getter: HttpGetter | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.http_getter = http_getter or httpx

    def get_item(self, item_id: str) -> dict:
        response = self.http_getter.get(
            f"{self.base_url}/emby/Items/{item_id}",
            params={"api_key": self.api_key, "Fields": "Path,MediaSources,People,ProviderIds"},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()

    def find_items_by_title(self, title: str) -> list[dict]:
        response = self.http_getter.get(
            f"{self.base_url}/emby/Items",
            params={"api_key": self.api_key, "SearchTerm": title, "Recursive": "true", "Fields": "Path,MediaSources,People,ProviderIds"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("Items") or [])
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/emby_media_actions/test_emby_client.py tests/emby_media_actions/test_nfo_parser.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/emby_media_actions/emby_client.py app/services/emby_media_actions/nfo_parser.py tests/emby_media_actions/test_emby_client.py tests/emby_media_actions/test_nfo_parser.py
git commit -m "feat: add emby metadata parsers"
```

---

### Task 4: Delete Plan Service

**Files:**
- Create: `app/services/emby_media_actions/delete_plan_service.py`
- Test: `tests/emby_media_actions/test_delete_plan_service.py`

**Interfaces:**
- Consumes:
  - `EmbyMediaMapping`
  - `PathGuard`
  - `Real115Client.delete_node(file_id: str, dry_run: bool)`
- Produces:
  - `EmbyDeletePlanService.create_plan_from_mapping(mapping_id: int, scope: str, source: str) -> EmbyDeletePlan`
  - `EmbyDeletePlanService.execute_plan(plan_id: int, confirm: bool) -> EmbyDeleteSummary`

- [ ] **Step 1: Write failing tests**

Create `tests/emby_media_actions/test_delete_plan_service.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.models.emby_media_actions import EmbyMediaMapping, EmbyMediaMappingPath
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService


def _mapping(db_session, tmp_path: Path) -> EmbyMediaMapping:
    source_root = tmp_path / "source"
    organized_root = tmp_path / "organized"
    source_root.mkdir()
    organized_root.mkdir()
    source = source_root / "a.strm"
    organized = organized_root / "a.strm"
    source.write_text("url", encoding="utf-8")
    organized.write_text("url", encoding="utf-8")
    mapping = EmbyMediaMapping(
        emby_item_id="item-1",
        emby_item_type="Movie",
        emby_title="测试电影",
        alist_url="http://example.test/d/115_OPEN/a.mkv",
        alist_mount_name="115_OPEN",
        remote_provider="115",
        remote_path="/a.mkv",
        remote_file_id="remote-1",
    )
    mapping.paths.extend(
        [
            EmbyMediaMappingPath(path_role="source_strm", path=str(source), root_name="source", root_path=str(source_root)),
            EmbyMediaMappingPath(path_role="organized_strm", path=str(organized), root_name="organized", root_path=str(organized_root)),
        ]
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


def test_create_plan_from_mapping_groups_items(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    service = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)])

    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    assert plan.status == "draft"
    assert plan.total_items == 3
    assert [item.group for item in sorted(plan.items, key=lambda item: item.group)] == [
        "emby_library",
        "remote_115",
        "source_strm",
    ]


def test_execute_plan_requires_confirm(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    plan = EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)]).create_plan_from_mapping(
        mapping_id=mapping.id,
        scope="movie",
        source="test",
    )

    with pytest.raises(ValueError, match="confirm must be true"):
        EmbyDeletePlanService(db_session, client_115=None, allowed_roots=[str(tmp_path)]).execute_plan(plan.id, confirm=False)


def test_execute_plan_deletes_local_and_remote(db_session, tmp_path: Path) -> None:
    mapping = _mapping(db_session, tmp_path)
    fake = Fake115Client()
    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/a.mkv", parent_id="0", is_file=True))
    service = EmbyDeletePlanService(db_session, client_115=fake, allowed_roots=[str(tmp_path)])
    plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source="test")

    summary = service.execute_plan(plan.id, confirm=True)

    assert summary.deleted == 3
    assert summary.failed == 0
    assert "remote-1" not in fake.nodes
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/emby_media_actions/test_delete_plan_service.py -v
```

Expected: FAIL with missing `delete_plan_service`.

- [ ] **Step 3: Implement delete plan service**

Create `app/services/emby_media_actions/delete_plan_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.emby_media_actions import EmbyDeletePlan, EmbyDeletePlanItem, EmbyMediaMapping
from app.services.emby_media_actions.path_guard import PathGuard


@dataclass(frozen=True, slots=True)
class EmbyDeleteSummary:
    plan_id: int
    total: int
    deleted: int
    failed: int
    blocked: int


class EmbyDeletePlanService:
    def __init__(self, db: Session, client_115, allowed_roots: list[str]) -> None:
        self.db = db
        self.client_115 = client_115
        self.path_guard = PathGuard(allowed_roots)

    def create_plan_from_mapping(self, *, mapping_id: int, scope: str, source: str) -> EmbyDeletePlan:
        mapping = self.db.get(EmbyMediaMapping, mapping_id)
        if mapping is None:
            raise LookupError("mapping not found")
        plan = EmbyDeletePlan(
            source=source,
            emby_item_id=mapping.emby_item_id,
            scope=scope,
            status="draft",
            summary=mapping.emby_title,
        )
        self.db.add(plan)
        self.db.flush()
        for path in mapping.paths:
            if path.path_role == "source_strm":
                group = "source_strm"
            elif path.path_role == "organized_strm":
                group = "emby_library"
            else:
                continue
            decision = self.path_guard.classify(path.path)
            self.db.add(
                EmbyDeletePlanItem(
                    plan_id=plan.id,
                    group=group,
                    target_type="file",
                    target_path=path.path,
                    display_name=path.path.rsplit("/", 1)[-1],
                    status="blocked" if not decision.allowed else "pending",
                    blocked_reason=decision.reason,
                    dry_run_result="blocked" if not decision.allowed else "dry_run",
                )
            )
        if mapping.remote_file_id:
            self.db.add(
                EmbyDeletePlanItem(
                    plan_id=plan.id,
                    group="remote_115",
                    target_type="remote_file",
                    remote_file_id=mapping.remote_file_id,
                    target_path=mapping.remote_path,
                    display_name=mapping.remote_path.rsplit("/", 1)[-1] if mapping.remote_path else mapping.remote_file_id,
                    status="pending",
                    dry_run_result="dry_run",
                )
            )
        self.db.flush()
        plan.total_items = len(plan.items)
        plan.blocked_count = sum(1 for item in plan.items if item.status == "blocked")
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def execute_plan(self, plan_id: int, *, confirm: bool) -> EmbyDeleteSummary:
        if not confirm:
            raise ValueError("confirm must be true")
        plan = self.db.get(EmbyDeletePlan, plan_id)
        if plan is None:
            raise LookupError("delete plan not found")
        if plan.status not in {"draft", "confirmed", "failed"}:
            raise ValueError("delete plan is not executable")
        plan.status = "running"
        plan.confirmed_at = plan.confirmed_at or datetime.now(UTC)
        plan.started_at = datetime.now(UTC)
        self.db.commit()
        deleted = failed = blocked = 0
        for item in sorted(plan.items, key=lambda row: row.id):
            if item.status == "blocked":
                blocked += 1
                continue
            try:
                if item.group == "remote_115":
                    if not self.client_115:
                        raise ValueError("115 client is required")
                    if not item.remote_file_id:
                        raise ValueError("remote_file_id is required")
                    self.client_115.delete_node(item.remote_file_id, dry_run=False)
                else:
                    if not item.target_path:
                        raise ValueError("target_path is required")
                    result = self.path_guard.delete_path(item.target_path, dry_run=False)
                    if result.status != "deleted":
                        raise ValueError(result.error_message or result.status)
                item.status = "deleted"
                item.executed_at = datetime.now(UTC)
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                item.status = "failed"
                item.error_message = str(exc)
                failed += 1
            self.db.commit()
        plan.deleted_count = deleted
        plan.failed_count = failed
        plan.blocked_count = blocked
        plan.status = "completed" if failed == 0 else "failed"
        plan.finished_at = datetime.now(UTC)
        self.db.commit()
        return EmbyDeleteSummary(plan.id, len(plan.items), deleted, failed, blocked)
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/emby_media_actions/test_delete_plan_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/emby_media_actions/delete_plan_service.py tests/emby_media_actions/test_delete_plan_service.py
git commit -m "feat: add emby delete plan service"
```

---

### Task 5: Metadata Candidate Service

**Files:**
- Create: `app/services/emby_media_actions/metadata_candidate_service.py`
- Test: `tests/emby_media_actions/test_metadata_candidate_service.py`

**Interfaces:**
- Consumes:
  - `parse_nfo_actors(xml_text: str)`
  - `KeywordRegistryService.create_entry(...)`
- Produces:
  - `EmbyMetadataCandidateService.create_candidate(...) -> EmbyMetadataCandidate`
  - `EmbyMetadataCandidateService.apply_actors(candidate_id: int, actors: list[str], note: str | None) -> EmbyMetadataCandidate`

- [ ] **Step 1: Write failing tests**

Create `tests/emby_media_actions/test_metadata_candidate_service.py`:

```python
from __future__ import annotations

from app.models.keywords import KeywordEntry
from app.services.emby_media_actions.metadata_candidate_service import EmbyMetadataCandidateService


def test_create_candidate_stores_snapshot(db_session) -> None:
    service = EmbyMetadataCandidateService(db_session)
    candidate = service.create_candidate(
        target_list="emby_blacklist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml="<movie><actor><name>演员A</name></actor></movie>",
        emby_payload={"Id": "item-1", "Name": "测试电影"},
        actors=[{"name": "演员A", "role": None, "provider_ids": {}}],
        source_path="/media/a.nfo",
    )

    assert candidate.status == "pending"
    assert candidate.snapshot.title == "测试电影"
    assert "演员A" in candidate.snapshot.actors_json


def test_apply_actors_creates_emby_keyword_entries(db_session) -> None:
    service = EmbyMetadataCandidateService(db_session)
    candidate = service.create_candidate(
        target_list="emby_whitelist",
        emby_item_id="item-1",
        title="测试电影",
        nfo_xml="<movie><actor><name>演员A</name></actor></movie>",
        emby_payload={"Id": "item-1", "Name": "测试电影"},
        actors=[{"name": "演员A", "role": None, "provider_ids": {}}],
        source_path="/media/a.nfo",
    )

    applied = service.apply_actors(candidate_id=candidate.id, actors=["演员A"], note="喜欢")

    assert applied.status == "applied"
    entry = db_session.query(KeywordEntry).filter_by(canonical_name="演员A").one()
    assert entry.keyword_type == "emby_whitelist"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/emby_media_actions/test_metadata_candidate_service.py -v
```

Expected: FAIL with missing service module.

- [ ] **Step 3: Implement metadata candidate service**

Create `app/services/emby_media_actions/metadata_candidate_service.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
import json

from sqlalchemy.orm import Session

from app.models.emby_media_actions import EmbyMetadataCandidate, EmbyMetadataSnapshot
from app.services.keywords.registry_service import KeywordRegistryService, normalize_keyword_text

VALID_TARGET_LISTS = {"emby_blacklist", "emby_whitelist"}


class EmbyMetadataCandidateService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_candidate(
        self,
        *,
        target_list: str,
        emby_item_id: str,
        title: str,
        nfo_xml: str | None,
        emby_payload: dict,
        actors: list[dict],
        source_path: str | None,
        mapping_id: int | None = None,
    ) -> EmbyMetadataCandidate:
        if target_list not in VALID_TARGET_LISTS:
            raise ValueError("target_list must be emby_blacklist or emby_whitelist")
        snapshot = EmbyMetadataSnapshot(
            emby_item_id=emby_item_id,
            mapping_id=mapping_id,
            snapshot_type="nfo_emby",
            title=title,
            nfo_path=source_path,
            nfo_xml=nfo_xml,
            emby_json=json.dumps(emby_payload, ensure_ascii=False),
            actors_json=json.dumps(actors, ensure_ascii=False),
        )
        self.db.add(snapshot)
        self.db.flush()
        candidate = EmbyMetadataCandidate(
            target_list=target_list,
            emby_item_id=emby_item_id,
            snapshot_id=snapshot.id,
            status="pending",
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def apply_actors(self, *, candidate_id: int, actors: list[str], note: str | None) -> EmbyMetadataCandidate:
        candidate = self.db.get(EmbyMetadataCandidate, candidate_id)
        if candidate is None:
            raise LookupError("metadata candidate not found")
        if candidate.status == "applied":
            raise ValueError("metadata candidate already applied")
        cleaned = [actor.strip() for actor in actors if actor.strip()]
        if not cleaned:
            raise ValueError("at least one actor is required")
        registry = KeywordRegistryService(self.db)
        entry_ids: list[int] = []
        for actor in dict.fromkeys(cleaned):
            normalized_actor = normalize_keyword_text(actor)
            existing = registry.find_entry_by_keyword(normalized_actor)
            if existing is None:
                entry = registry.create_entry(
                    canonical_name=actor,
                    keyword_type=candidate.target_list,
                    note=note,
                    source="emby_media_actions",
                )
            elif existing.keyword_type != candidate.target_list:
                raise ValueError(f"actor {actor} already exists in {existing.keyword_type}")
            else:
                entry = existing
            entry_ids.append(entry.id)
        candidate.selected_actors_json = json.dumps(cleaned, ensure_ascii=False)
        candidate.applied_keyword_entry_ids_json = json.dumps(entry_ids)
        candidate.note = note
        candidate.status = "applied"
        candidate.applied_at = datetime.now(UTC)
        self.db.commit()
        registry.sync_legacy_library()
        self.db.refresh(candidate)
        return candidate
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/emby_media_actions/test_metadata_candidate_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/emby_media_actions/metadata_candidate_service.py tests/emby_media_actions/test_metadata_candidate_service.py
git commit -m "feat: add emby metadata candidates"
```

---

### Task 6: API Schemas And Routes

**Files:**
- Create: `app/schemas/emby_media_actions.py`
- Create: `app/api/routes/emby_media_actions.py`
- Modify: `app/main.py`
- Test: `tests/api/test_emby_media_actions_routes.py`

**Interfaces:**
- Consumes services from Tasks 2-5.
- Produces routes:
  - `POST /api/emby-media-actions/intake`
  - `GET /api/emby-media-actions/delete-plans/{id}`
  - `POST /api/emby-media-actions/delete-plans/{id}/confirm`
  - `GET /api/emby-media-actions/metadata-candidates/{id}`
  - `POST /api/emby-media-actions/metadata-candidates/{id}/apply`

- [ ] **Step 1: Write failing API tests**

Create `tests/api/test_emby_media_actions_routes.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import emby_media_actions as _emby_media_actions  # noqa: F401
from app.models import keywords as _keywords  # noqa: F401
from app.models import tree as _tree  # noqa: F401
from app.services.client_115.client import Fake115Client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_STORE_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_STRM_ROOTS", str(tmp_path))
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_SOURCE_ROOTS", str(tmp_path / "source"))
    monkeypatch.setenv("EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS", str(tmp_path / "organized"))
    from app.core.config import get_settings
    get_settings.cache_clear()

    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app import main as _main
    from app.api import deps

    def override_get_db():
        db = Factory()
        try:
            yield db
        finally:
            db.close()

    _main.app.dependency_overrides[deps.get_db] = override_get_db
    _main.app.state.client_115 = Fake115Client()
    yield TestClient(_main.app, raise_server_exceptions=False)
    _main.app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_metadata_candidate_apply_route(client: TestClient) -> None:
    created = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "metadata_blacklist",
            "path": "/media/a.strm",
            "title": "测试电影",
            "emby_item_id": "item-1",
            "nfo_xml": "<movie><actor><name>演员A</name></actor></movie>",
            "actors": [{"name": "演员A", "role": None, "provider_ids": {}}],
        },
    )

    assert created.status_code == 200
    candidate_id = created.json()["metadata_candidate"]["id"]

    applied = client.post(
        f"/emby-media-actions/metadata-candidates/{candidate_id}/apply",
        json={"actors": ["演员A"], "note": "确认"},
    )

    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/api/test_emby_media_actions_routes.py -v
```

Expected: FAIL with 404 for `/emby-media-actions/intake`.

- [ ] **Step 3: Add schemas**

Create `app/schemas/emby_media_actions.py` with Pydantic models:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EmbyAction = Literal["delete_plan", "metadata_blacklist", "metadata_whitelist"]


class EmbyActorPayload(BaseModel):
    name: str
    role: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)


class EmbyMediaIntakeRequest(BaseModel):
    action: EmbyAction
    path: str | None = None
    url: str | None = None
    title: str | None = None
    emby_item_id: str | None = None
    source: str = "iina_lua"
    nfo_xml: str | None = None
    actors: list[EmbyActorPayload] = Field(default_factory=list)


class EmbyMetadataCandidateResponse(BaseModel):
    id: int
    target_list: str
    status: str
    emby_item_id: str
    snapshot_id: int
    created_at: datetime
    applied_at: datetime | None

    model_config = {"from_attributes": True}


class EmbyDeletePlanItemResponse(BaseModel):
    id: int
    group: str
    target_type: str
    target_path: str | None
    remote_file_id: str | None
    display_name: str
    status: str
    blocked_reason: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class EmbyDeletePlanResponse(BaseModel):
    id: int
    source: str
    emby_item_id: str
    scope: str
    status: str
    summary: str
    total_items: int
    deleted_count: int
    failed_count: int
    blocked_count: int
    items: list[EmbyDeletePlanItemResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EmbyMediaIntakeResponse(BaseModel):
    ok: bool
    delete_plan: EmbyDeletePlanResponse | None = None
    metadata_candidate: EmbyMetadataCandidateResponse | None = None


class EmbyMetadataApplyRequest(BaseModel):
    actors: list[str]
    note: str | None = None


class EmbyDeleteConfirmRequest(BaseModel):
    confirm: bool = False
```

- [ ] **Step 4: Add routes**

Create `app/api/routes/emby_media_actions.py`. For the first API slice, support metadata candidate intake and wire delete confirm/detail to the service. If `delete_plan` intake cannot build a mapping from URL yet, return HTTP 400 with `detail="delete_plan intake requires a resolved mapping"`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.emby_media_actions import EmbyDeletePlan, EmbyMetadataCandidate
from app.schemas.emby_media_actions import (
    EmbyDeleteConfirmRequest,
    EmbyDeletePlanResponse,
    EmbyMediaIntakeRequest,
    EmbyMediaIntakeResponse,
    EmbyMetadataApplyRequest,
    EmbyMetadataCandidateResponse,
)
from app.services.emby_media_actions.delete_plan_service import EmbyDeletePlanService
from app.services.emby_media_actions.metadata_candidate_service import EmbyMetadataCandidateService

router = APIRouter(prefix="/emby-media-actions", tags=["emby-media-actions"])


def _delete_plan_response(plan: EmbyDeletePlan) -> EmbyDeletePlanResponse:
    return EmbyDeletePlanResponse.model_validate(plan)


@router.post("/intake", response_model=EmbyMediaIntakeResponse)
def intake(payload: EmbyMediaIntakeRequest, db: Session = Depends(get_db)) -> EmbyMediaIntakeResponse:
    if payload.action in {"metadata_blacklist", "metadata_whitelist"}:
        if not payload.emby_item_id:
            raise HTTPException(status_code=400, detail="emby_item_id is required")
        target_list = "emby_blacklist" if payload.action == "metadata_blacklist" else "emby_whitelist"
        candidate = EmbyMetadataCandidateService(db).create_candidate(
            target_list=target_list,
            emby_item_id=payload.emby_item_id,
            title=payload.title or payload.emby_item_id,
            nfo_xml=payload.nfo_xml,
            emby_payload={"Id": payload.emby_item_id, "Name": payload.title},
            actors=[actor.model_dump() for actor in payload.actors],
            source_path=payload.path,
        )
        return EmbyMediaIntakeResponse(ok=True, metadata_candidate=EmbyMetadataCandidateResponse.model_validate(candidate))
    raise HTTPException(status_code=400, detail="delete_plan intake requires a resolved mapping")


@router.get("/delete-plans/{plan_id}", response_model=EmbyDeletePlanResponse)
def get_delete_plan(plan_id: int, db: Session = Depends(get_db)) -> EmbyDeletePlanResponse:
    plan = db.get(EmbyDeletePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="delete plan not found")
    return _delete_plan_response(plan)


@router.post("/delete-plans/{plan_id}/confirm")
def confirm_delete_plan(plan_id: int, payload: EmbyDeleteConfirmRequest, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    try:
        summary = EmbyDeletePlanService(
            db,
            client_115=getattr(request.app.state, "client_115", None),
            allowed_roots=settings.emby_media_actions_source_roots + settings.emby_media_actions_organized_roots,
        ).execute_plan(plan_id, confirm=payload.confirm)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"plan_id": summary.plan_id, "total": summary.total, "deleted": summary.deleted, "failed": summary.failed, "blocked": summary.blocked}


@router.get("/metadata-candidates/{candidate_id}", response_model=EmbyMetadataCandidateResponse)
def get_metadata_candidate(candidate_id: int, db: Session = Depends(get_db)) -> EmbyMetadataCandidateResponse:
    candidate = db.get(EmbyMetadataCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="metadata candidate not found")
    return EmbyMetadataCandidateResponse.model_validate(candidate)


@router.post("/metadata-candidates/{candidate_id}/apply", response_model=EmbyMetadataCandidateResponse)
def apply_metadata_candidate(candidate_id: int, payload: EmbyMetadataApplyRequest, db: Session = Depends(get_db)) -> EmbyMetadataCandidateResponse:
    try:
        candidate = EmbyMetadataCandidateService(db).apply_actors(candidate_id=candidate_id, actors=payload.actors, note=payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmbyMetadataCandidateResponse.model_validate(candidate)
```

- [ ] **Step 5: Register router**

Modify `app/main.py` import list to include `emby_media_actions`, and add:

```python
app.include_router(emby_media_actions.router)
```

Place it near `review_intake.router`.

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/api/test_emby_media_actions_routes.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/emby_media_actions.py app/api/routes/emby_media_actions.py app/main.py tests/api/test_emby_media_actions_routes.py
git commit -m "feat: add emby media action api"
```

---

### Task 7: Mapping Intake For Delete Plans

**Files:**
- Modify: `app/api/routes/emby_media_actions.py`
- Modify: `app/services/emby_media_actions/delete_plan_service.py`
- Test: `tests/api/test_emby_media_actions_routes.py`

**Interfaces:**
- Consumes:
  - `StrmMappingService.scan_for_url(url: str)`
  - `decode_115_open_path(url: str)`
  - `client_115.get_file(path=remote_path)`
- Produces:
  - `POST /api/emby-media-actions/intake` with `action="delete_plan"` returns `delete_plan`.

- [ ] **Step 1: Add failing delete-plan intake test**

Append this test to `tests/api/test_emby_media_actions_routes.py`:

```python
def test_delete_plan_intake_resolves_strm_and_creates_plan(client: TestClient, tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    organized = tmp_path / "organized"
    source.mkdir(exist_ok=True)
    organized.mkdir(exist_ok=True)
    url = "http://192.168.70.138:5244/d/115_OPEN/%E7%94%B5%E5%BD%B1/a.mkv"
    (source / "a.strm").write_text(url, encoding="utf-8")
    (organized / "a.strm").write_text(url, encoding="utf-8")

    from app.services.client_115.schemas import NodePayload
    fake = client.app.state.client_115
    fake.add_node(NodePayload(id="remote-1", name="a.mkv", path="/电影/a.mkv", parent_id="0", is_file=True))

    response = client.post(
        "/emby-media-actions/intake",
        json={
            "action": "delete_plan",
            "url": url,
            "title": "测试电影",
            "emby_item_id": "item-1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["delete_plan"]["status"] == "draft"
    assert data["delete_plan"]["total_items"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/api/test_emby_media_actions_routes.py::test_delete_plan_intake_resolves_strm_and_creates_plan -v
```

Expected: FAIL with HTTP 400 `delete_plan intake requires a resolved mapping`.

- [ ] **Step 3: Add mapping creation helper to delete plan service**

In `app/services/emby_media_actions/delete_plan_service.py`, add a method:

```python
    def create_mapping_from_matches(
        self,
        *,
        emby_item_id: str,
        emby_item_type: str,
        emby_title: str,
        alist_url: str,
        mount_name: str,
        remote_path: str,
        remote_file_id: str | None,
        matches,
    ) -> EmbyMediaMapping:
        mapping = EmbyMediaMapping(
            emby_item_id=emby_item_id,
            emby_item_type=emby_item_type,
            emby_title=emby_title,
            alist_url=alist_url,
            alist_mount_name=mount_name,
            remote_provider="115",
            remote_path=remote_path,
            remote_file_id=remote_file_id,
        )
        self.db.add(mapping)
        self.db.flush()
        for match in matches:
            mapping.paths.append(
                EmbyMediaMappingPath(
                    path_role=match.path_role,
                    path=match.path,
                    root_name=match.root_name,
                    root_path=match.root_path,
                    file_size=match.file_size,
                    inode=match.inode,
                    link_count=match.link_count,
                )
            )
        self.db.commit()
        self.db.refresh(mapping)
        return mapping
```

Also import `EmbyMediaMappingPath`.

- [ ] **Step 4: Wire delete-plan intake route**

Replace the HTTP 400 branch for `payload.action == "delete_plan"` in `app/api/routes/emby_media_actions.py` with:

```python
    if payload.action == "delete_plan":
        if not payload.emby_item_id:
            raise HTTPException(status_code=400, detail="emby_item_id is required")
        stream_url = payload.url
        if not stream_url and payload.path and payload.path.endswith(".strm"):
            try:
                with open(payload.path, "r", encoding="utf-8", errors="ignore") as file:
                    stream_url = file.readline().strip()
            except OSError as exc:
                raise HTTPException(status_code=400, detail=f"cannot read strm path: {exc}") from exc
        if not stream_url:
            raise HTTPException(status_code=400, detail="url or readable strm path is required")

        settings = get_settings()
        decoded = decode_115_open_path(stream_url)
        matches = StrmMappingService(
            strm_roots=settings.emby_media_actions_strm_roots,
            source_roots=settings.emby_media_actions_source_roots,
            organized_roots=settings.emby_media_actions_organized_roots,
        ).scan_for_url(stream_url)
        remote_file_id = None
        client_115 = getattr(request.app.state, "client_115", None)
        if client_115 is not None:
            try:
                remote_payload = client_115.get_file(path=decoded.remote_path)
                remote_file_id = str((remote_payload.get("data") or {}).get("file_id") or "")
            except Exception:
                remote_file_id = None
        service = EmbyDeletePlanService(
            db,
            client_115=client_115,
            allowed_roots=settings.emby_media_actions_source_roots + settings.emby_media_actions_organized_roots,
        )
        mapping = service.create_mapping_from_matches(
            emby_item_id=payload.emby_item_id,
            emby_item_type="Unknown",
            emby_title=payload.title or payload.emby_item_id,
            alist_url=stream_url,
            mount_name=decoded.mount_name,
            remote_path=decoded.remote_path,
            remote_file_id=remote_file_id or None,
            matches=matches,
        )
        plan = service.create_plan_from_mapping(mapping_id=mapping.id, scope="movie", source=payload.source)
        return EmbyMediaIntakeResponse(ok=True, delete_plan=_delete_plan_response(plan))
```

Add imports:

```python
from app.services.emby_media_actions.strm_mapping_service import StrmMappingService, decode_115_open_path
```

Change the `intake` route signature to include `request: Request`.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/api/test_emby_media_actions_routes.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/routes/emby_media_actions.py app/services/emby_media_actions/delete_plan_service.py tests/api/test_emby_media_actions_routes.py
git commit -m "feat: resolve emby delete plan intake"
```

---

### Task 8: IINA Helper And Lua Script

**Files:**
- Create: `scripts/emby_media_action_shortcut.py`
- Create: `scripts/iina_emby_media_actions.lua`
- Test: `tests/emby_media_actions/test_iina_helper.py`

**Interfaces:**
- Produces CLI:
  - `python scripts/emby_media_action_shortcut.py delete-plan --path <path> --base-url <url>`
  - `python scripts/emby_media_action_shortcut.py blacklist --path <path> --base-url <url>`
  - `python scripts/emby_media_action_shortcut.py whitelist --path <path> --base-url <url>`
- Produces IINA bindings:
  - `script-binding iina_emby_media_actions/emby-delete-plan`
  - `script-binding iina_emby_media_actions/emby-blacklist-candidate`
  - `script-binding iina_emby_media_actions/emby-whitelist-candidate`

- [ ] **Step 1: Write helper argument tests**

Create `tests/emby_media_actions/test_iina_helper.py`:

```python
from __future__ import annotations

from scripts.emby_media_action_shortcut import build_payload


def test_build_payload_for_delete_plan() -> None:
    payload = build_payload("delete-plan", "/media/a.strm", "iina_lua")

    assert payload["action"] == "delete_plan"
    assert payload["path"] == "/media/a.strm"
    assert payload["source"] == "iina_lua"


def test_build_payload_for_blacklist() -> None:
    payload = build_payload("blacklist", "/media/a.strm", "iina_lua")

    assert payload["action"] == "metadata_blacklist"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/emby_media_actions/test_iina_helper.py -v
```

Expected: FAIL with missing helper module.

- [ ] **Step 3: Implement helper**

Create `scripts/emby_media_action_shortcut.py` by copying the authentication/cookie pattern from `scripts/review_intake_shortcut.py`. Add this function exactly so tests can import it:

```python
def build_payload(action: str, path: str, source: str) -> dict:
    action_map = {
        "delete-plan": "delete_plan",
        "blacklist": "metadata_blacklist",
        "whitelist": "metadata_whitelist",
    }
    return {"action": action_map[action], "path": path, "source": source}
```

The CLI should:

```python
parser.add_argument("action", choices=["delete-plan", "blacklist", "whitelist"])
parser.add_argument("--path", required=True)
parser.add_argument("--base-url", default=os.getenv("EMBY_MEDIA_ACTIONS_BASE_URL", "http://127.0.0.1:8000"))
```

Post to:

```python
url = f"{base_url}/emby-media-actions/intake"
```

Print:

```python
print(f"已提交 Emby 媒体动作：{args.action}")
```

- [ ] **Step 4: Implement Lua script**

Create `scripts/iina_emby_media_actions.lua` using the current `iina_review_intake.lua` style. Use these environment names:

```lua
local helper = os.getenv("EMBY_MEDIA_ACTIONS_HELPER")
  or "/Users/wangyichuan/Desktop/wangcodemac/18x_v2/scripts/emby_media_action_shortcut.py"
local python = os.getenv("EMBY_MEDIA_ACTIONS_PYTHON")
  or "/Users/wangyichuan/Desktop/wangcodemac/18x_v2/.venv/bin/python"
local base_url = os.getenv("EMBY_MEDIA_ACTIONS_BASE_URL")
  or "http://192.168.70.138:8010/api"
local log_path = os.getenv("EMBY_MEDIA_ACTIONS_LOG")
  or "/Users/wangyichuan/Library/Application Support/com.colliderli.iina/scripts/emby_media_actions.log"
```

Register:

```lua
mp.add_key_binding(nil, "emby-delete-plan", function()
  submit("delete-plan")
end)

mp.add_key_binding(nil, "emby-blacklist-candidate", function()
  submit("blacklist")
end)

mp.add_key_binding(nil, "emby-whitelist-candidate", function()
  submit("whitelist")
end)
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
pytest tests/emby_media_actions/test_iina_helper.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/emby_media_action_shortcut.py scripts/iina_emby_media_actions.lua tests/emby_media_actions/test_iina_helper.py
git commit -m "feat: add iina emby media actions shortcut"
```

---

### Task 9: Frontend Review Page

**Files:**
- Create: `frontend/src/api/embyMediaActions.ts`
- Create: `frontend/src/pages/EmbyMediaActionsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/layout/navigation.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes:
  - `GET /emby-media-actions/delete-plans/{id}`
  - `POST /emby-media-actions/delete-plans/{id}/confirm`
  - `GET /emby-media-actions/metadata-candidates/{id}`
  - `POST /emby-media-actions/metadata-candidates/{id}/apply`
- Produces route:
  - `/emby-media-actions`

- [ ] **Step 1: Add frontend API types**

Create `frontend/src/api/embyMediaActions.ts`:

```ts
import { api } from './client'

export interface EmbyDeletePlanItem {
  id: number
  group: string
  target_type: string
  target_path: string | null
  remote_file_id: string | null
  display_name: string
  status: string
  blocked_reason: string | null
  error_message: string | null
}

export interface EmbyDeletePlan {
  id: number
  source: string
  emby_item_id: string
  scope: string
  status: string
  summary: string
  total_items: number
  deleted_count: number
  failed_count: number
  blocked_count: number
  items: EmbyDeletePlanItem[]
}

export interface EmbyMetadataCandidate {
  id: number
  target_list: string
  status: string
  emby_item_id: string
  snapshot_id: number
  created_at: string
  applied_at: string | null
}

export function getEmbyDeletePlan(id: number) {
  return api.get<EmbyDeletePlan>(`/emby-media-actions/delete-plans/${id}`)
}

export function confirmEmbyDeletePlan(id: number) {
  return api.post<{ plan_id: number; total: number; deleted: number; failed: number; blocked: number }>(
    `/emby-media-actions/delete-plans/${id}/confirm`,
    { confirm: true },
  )
}

export function getEmbyMetadataCandidate(id: number) {
  return api.get<EmbyMetadataCandidate>(`/emby-media-actions/metadata-candidates/${id}`)
}

export function applyEmbyMetadataCandidate(id: number, actors: string[], note: string | null) {
  return api.post<EmbyMetadataCandidate>(`/emby-media-actions/metadata-candidates/${id}/apply`, { actors, note })
}
```

- [ ] **Step 2: Create page**

Create `frontend/src/pages/EmbyMediaActionsPage.tsx` with a compact operations UI:

```tsx
import { useState } from 'react'
import { Button, Card, Descriptions, Form, Input, Popconfirm, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  applyEmbyMetadataCandidate,
  confirmEmbyDeletePlan,
  getEmbyDeletePlan,
  getEmbyMetadataCandidate,
  type EmbyDeletePlan,
  type EmbyDeletePlanItem,
  type EmbyMetadataCandidate,
} from '@/api/embyMediaActions'
import PageScaffold from '@/layout/PageScaffold'

const { Text } = Typography

export default function EmbyMediaActionsPage() {
  const [planId, setPlanId] = useState('')
  const [candidateId, setCandidateId] = useState('')
  const [plan, setPlan] = useState<EmbyDeletePlan | null>(null)
  const [candidate, setCandidate] = useState<EmbyMetadataCandidate | null>(null)
  const [loading, setLoading] = useState(false)
  const [messageApi, holder] = message.useMessage()

  const columns: ColumnsType<EmbyDeletePlanItem> = [
    { title: '分组', dataIndex: 'group', width: 130 },
    { title: '名称', dataIndex: 'display_name' },
    { title: '状态', dataIndex: 'status', width: 120 },
    { title: '路径', dataIndex: 'target_path', ellipsis: true },
    { title: '阻止原因', dataIndex: 'blocked_reason', width: 180 },
  ]

  const loadPlan = async () => {
    setLoading(true)
    try {
      setPlan(await getEmbyDeletePlan(Number(planId)))
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载删除计划失败')
    } finally {
      setLoading(false)
    }
  }

  const confirmPlan = async () => {
    if (!plan) return
    setLoading(true)
    try {
      await confirmEmbyDeletePlan(plan.id)
      setPlan(await getEmbyDeletePlan(plan.id))
      void messageApi.success('删除计划已执行')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '执行删除计划失败')
    } finally {
      setLoading(false)
    }
  }

  const loadCandidate = async () => {
    setLoading(true)
    try {
      setCandidate(await getEmbyMetadataCandidate(Number(candidateId)))
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '加载名单候选失败')
    } finally {
      setLoading(false)
    }
  }

  const applyCandidate = async (values: { actors: string; note?: string }) => {
    if (!candidate) return
    const actors = values.actors.split('\n').map((item) => item.trim()).filter(Boolean)
    setLoading(true)
    try {
      setCandidate(await applyEmbyMetadataCandidate(candidate.id, actors, values.note || null))
      void messageApi.success('演员名单已写入')
    } catch (error) {
      void messageApi.error(error instanceof Error ? error.message : '写入演员名单失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageScaffold title="Emby 媒体动作" description="审核 IINA 提交的删除计划和演员名单候选。">
      {holder}
      <div className="emby-media-actions-grid">
        <Card title="删除计划" className="soft-card">
          <Space.Compact>
            <Input placeholder="Plan ID" value={planId} onChange={(event) => setPlanId(event.target.value)} />
            <Button onClick={loadPlan} loading={loading}>加载</Button>
          </Space.Compact>
          {plan && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="标题">{plan.summary}</Descriptions.Item>
                <Descriptions.Item label="状态">{plan.status}</Descriptions.Item>
                <Descriptions.Item label="总数">{plan.total_items}</Descriptions.Item>
                <Descriptions.Item label="阻止">{plan.blocked_count}</Descriptions.Item>
              </Descriptions>
              <Table rowKey="id" size="small" columns={columns} dataSource={plan.items} pagination={false} />
              <Popconfirm
                title="确认执行删除计划"
                description="这会删除本地 STRM/整理产物，并通过 115 OpenAPI 删除网盘原文件。"
                okText="确认删除"
                cancelText="取消"
                onConfirm={confirmPlan}
                disabled={plan.status !== 'draft'}
              >
                <Button danger type="primary" disabled={plan.status !== 'draft'} loading={loading}>
                  确认执行删除
                </Button>
              </Popconfirm>
            </Space>
          )}
        </Card>

        <Card title="演员名单候选" className="soft-card">
          <Space.Compact>
            <Input placeholder="Candidate ID" value={candidateId} onChange={(event) => setCandidateId(event.target.value)} />
            <Button onClick={loadCandidate} loading={loading}>加载</Button>
          </Space.Compact>
          {candidate && (
            <Space direction="vertical" size="middle" className="emby-media-actions-section">
              <Descriptions size="small" column={1}>
                <Descriptions.Item label="目标名单">{candidate.target_list}</Descriptions.Item>
                <Descriptions.Item label="状态">{candidate.status}</Descriptions.Item>
                <Descriptions.Item label="Item ID">{candidate.emby_item_id}</Descriptions.Item>
              </Descriptions>
              <Form layout="vertical" onFinish={applyCandidate}>
                <Form.Item name="actors" label="演员，每行一个" rules={[{ required: true, message: '请输入至少一个演员' }]}>
                  <Input.TextArea rows={5} />
                </Form.Item>
                <Form.Item name="note" label="备注">
                  <Input />
                </Form.Item>
                <Button type="primary" htmlType="submit" disabled={candidate.status === 'applied'} loading={loading}>
                  写入名单
                </Button>
              </Form>
              <Text type="secondary">完整 NFO 快照已保存在后端，后续页面可以继续展示演员明细。</Text>
            </Space>
          )}
        </Card>
      </div>
    </PageScaffold>
  )
}
```

- [ ] **Step 3: Add route and nav**

Modify `frontend/src/App.tsx`:

```ts
import EmbyMediaActionsPage from './pages/EmbyMediaActionsPage'
```

Add route near `/review-intake`:

```tsx
<Route path="/emby-media-actions" element={<EmbyMediaActionsPage />} />
```

Modify `frontend/src/layout/navigation.tsx`:

```ts
import { PlaySquareOutlined } from '@ant-design/icons'
```

Add Workflow item:

```tsx
{ key: '/emby-media-actions', label: 'Emby 动作', icon: <PlaySquareOutlined /> },
```

- [ ] **Step 4: Add CSS**

Append to `frontend/src/index.css`:

```css
.emby-media-actions-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.7fr);
  gap: 16px;
}

.emby-media-actions-section {
  width: 100%;
  margin-top: 16px;
}

@media (max-width: 980px) {
  .emby-media-actions-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/embyMediaActions.ts frontend/src/pages/EmbyMediaActionsPage.tsx frontend/src/App.tsx frontend/src/layout/navigation.tsx frontend/src/index.css
git commit -m "feat: add emby media action review page"
```

---

### Task 10: Full Verification And Deployment Notes

**Files:**
- Modify: `docs/superpowers/specs/2026-07-02-emby-media-actions-design.md`
- Create: `docs/superpowers/plans/2026-07-02-emby-media-actions-verification.md`

**Interfaces:**
- Consumes all prior tasks.
- Produces a short verification note with commands, results, and production env values to set.

- [ ] **Step 1: Run backend test subset**

Run:

```bash
pytest tests/emby_media_actions tests/api/test_emby_media_actions_routes.py -v
```

Expected: PASS.

- [ ] **Step 2: Run related existing tests**

Run:

```bash
pytest tests/services/test_review_intake_service.py tests/api/test_review_intake_routes.py tests/dedupe/test_delete_plan_service.py -v
```

Expected: PASS. These tests check nearby keyword intake and delete plan behavior.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 4: Write verification note**

Create `docs/superpowers/plans/2026-07-02-emby-media-actions-verification.md`:

```markdown
# Emby Media Actions Verification

## Commands

- `pytest tests/emby_media_actions tests/api/test_emby_media_actions_routes.py -v`
- `pytest tests/services/test_review_intake_service.py tests/api/test_review_intake_routes.py tests/dedupe/test_delete_plan_service.py -v`
- `cd frontend && npm run build`

## Production Environment

- `EMBY_BASE_URL=http://192.168.70.138:8096`
- `EMBY_API_KEY` is set outside git.
- `EMBY_MEDIA_ACTIONS_ENABLED=true`
- `EMBY_MEDIA_ACTIONS_STRM_ROOTS=/mnt/cache/docker1/alist-strm/video`
- `EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS=/mnt/cache/docker1/alist-strm/video/mp302_mv,/mnt/cache/docker1/alist-strm/video/mp302_tv,/mnt/cache/docker1/alist-strm/video/porn_tv1`
- `EMBY_MEDIA_ACTIONS_SOURCE_ROOTS=/mnt/cache/docker1/alist-strm/video/alist_mv1,/mnt/cache/docker1/alist-strm/video/alist_tv1,/mnt/cache/docker1/alist-strm/video/115strm,/mnt/cache/docker1/alist-strm/video/kuake2,/mnt/cache/docker1/alist-strm/video/302porn_tv1`
- `EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT=true`

## Manual Smoke Test

1. Install `scripts/iina_emby_media_actions.lua` in IINA.
2. Bind `emby-delete-plan`, `emby-blacklist-candidate`, and `emby-whitelist-candidate`.
3. Play one known STRM-backed Emby item.
4. Trigger `emby-delete-plan`.
5. Open `/emby-media-actions` and load the returned plan id.
6. Verify the plan shows `emby_library`, `source_strm`, and `remote_115` groups.
7. Do not confirm real deletion until the plan items match the expected item exactly.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-07-02-emby-media-actions-verification.md docs/superpowers/specs/2026-07-02-emby-media-actions-design.md
git commit -m "docs: add emby media actions verification"
```

If the design spec has no changes, omit it from `git add`.
