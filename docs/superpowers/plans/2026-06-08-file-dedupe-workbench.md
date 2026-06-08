# File Dedupe Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent file-dedupe workbench that scans imported local directory trees, reviews duplicate candidates, confirms selected files through limited 115 API calls, and executes deletions through a second-confirmation delete plan.

**Architecture:** Add a dedicated dedupe domain: SQLAlchemy models + Alembic migration, pure backend services for normalization/scan/confirmation/delete plans, FastAPI routes with Job/SSE orchestration, and a React/AntD workbench page. Scanning is local-only against `NodeFile`; 115 API calls happen only during explicit confirmation and delete-plan execution.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, pytest, React 19, Ant Design 6, TypeScript, Vite.

---

## Scope And Execution Notes

- Follow the approved spec: `docs/superpowers/specs/2026-06-08-file-dedupe-workbench-design.md`.
- Do not touch the server during implementation. Server work requires a separate read-only inspection and user approval.
- Leave the untracked sample file `根目录20260419_目录树.txt` uncommitted unless the user explicitly asks to add a fixture.
- Use TDD. Each task below starts with tests, then implementation, then verification, then a commit.
- Use Lore-format commits. Every commit command in this plan includes a narrative body, `Tested:`, `Confidence:`, and `Co-authored-by: OmX <omx@oh-my-codex.dev>`.

## File Structure

Create or modify these files:

- Create `app/models/dedupe.py`: SQLAlchemy models for scan runs, groups, candidates, remote confirmations, delete plans, and delete plan items.
- Modify `alembic/env.py`: import `app.models.dedupe` for metadata discovery.
- Create `alembic/versions/20260608_0006_dedupe_workbench.py`: migration creating the dedupe tables and indexes.
- Modify `tests/conftest.py`: import dedupe models so in-memory test DBs include the new tables.
- Create `app/schemas/dedupe.py`: request/response models and Job frame schemas.
- Create `app/services/dedupe/__init__.py`: package marker.
- Create `app/services/dedupe/normalization.py`: filename normalization and rule preview.
- Create `app/services/dedupe/scan_service.py`: local-only scan, grouping, and candidate ledger persistence.
- Create `app/services/dedupe/confirmation_service.py`: path resolution, file-detail confirmation, confidence promotion.
- Create `app/services/dedupe/delete_plan_service.py`: delete-plan creation, confirmation, execution, and retry rules.
- Create `app/api/routes/dedupe.py`: FastAPI routes, locks, active jobs, SSE progress, and CRUD endpoints.
- Modify `app/main.py`: include the dedupe router and start/stop dedupe job sweeper.
- Create `tests/dedupe/test_normalization.py`: normalization and preview tests.
- Create `tests/dedupe/test_scan_service.py`: scan and grouping tests.
- Create `tests/dedupe/test_confirmation_service.py`: remote confirmation tests with `Fake115Client`.
- Create `tests/dedupe/test_delete_plan_service.py`: delete-plan safety and execution tests.
- Create `tests/api/test_dedupe_routes.py`: route and job-state tests.
- Create `frontend/src/api/dedupe.ts`: typed client for dedupe APIs and SSE.
- Create `frontend/src/pages/FileDedupePage.tsx`: AntD workbench page.
- Modify `frontend/src/App.tsx`: add navigation and route for `/dedupe`.

---

### Task 1: Dedupe Models And Migration

**Files:**
- Create: `app/models/dedupe.py`
- Create: `alembic/versions/20260608_0006_dedupe_workbench.py`
- Modify: `alembic/env.py`
- Modify: `tests/conftest.py`
- Test: `tests/dedupe/test_dedupe_models.py`

- [ ] **Step 1: Write the failing model test**

Create `tests/dedupe/test_dedupe_models.py`:

```python
from __future__ import annotations

from sqlalchemy import inspect

from app.db.base import Base


def test_dedupe_tables_are_registered(db_session):
    table_names = set(inspect(db_session.bind).get_table_names())
    assert {
        "dedupe_scan_runs",
        "dedupe_groups",
        "dedupe_candidates",
        "dedupe_remote_confirmations",
        "dedupe_delete_plans",
        "dedupe_delete_plan_items",
    }.issubset(table_names)

    assert "dedupe_scan_runs" in Base.metadata.tables
    assert "dedupe_delete_plan_items" in Base.metadata.tables
```

- [ ] **Step 2: Run the model test and verify it fails**

Run:

```bash
python -m pytest tests/dedupe/test_dedupe_models.py -q
```

Expected: FAIL because `app.models.dedupe` and the new tables do not exist yet.

- [ ] **Step 3: Add SQLAlchemy models**

Create `app/models/dedupe.py` with focused model classes:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class DedupeScanRun(Base):
    __tablename__ = "dedupe_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tree_import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    scope_path_prefix: Mapped[str | None] = mapped_column(Text)
    included_extensions: Mapped[str] = mapped_column(Text, default=".mp4,.mkv,.avi,.mov")
    candidate_threshold: Mapped[float] = mapped_column(Float, default=0.82)
    high_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.92)
    rules_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    total_groups: Mapped[int] = mapped_column(Integer, default=0)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    groups: Mapped[list["DedupeGroup"]] = relationship(back_populates="scan_run", cascade="all, delete-orphan")


class DedupeGroup(TimestampMixin, Base):
    __tablename__ = "dedupe_groups"
    __table_args__ = (
        UniqueConstraint("scan_run_id", "group_key", name="uq_dedupe_groups_run_key"),
        Index("ix_dedupe_groups_status_confidence", "status", "confidence_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("dedupe_scan_runs.id", ondelete="CASCADE"), index=True)
    tree_import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), index=True)
    group_key: Mapped[str] = mapped_column(String(128), nullable=False)
    representative_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    score_max: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(32), default="filename_suspected", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    suggested_keep_candidate_id: Mapped[int | None] = mapped_column(Integer)
    review_note: Mapped[str | None] = mapped_column(Text)

    scan_run: Mapped[DedupeScanRun] = relationship(back_populates="groups")
    candidates: Mapped[list["DedupeCandidate"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class DedupeCandidate(TimestampMixin, Base):
    __tablename__ = "dedupe_candidates"
    __table_args__ = (
        UniqueConstraint("group_id", "node_file_id", name="uq_dedupe_candidates_group_node_file"),
        Index("ix_dedupe_candidates_user_action", "user_action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("dedupe_groups.id", ondelete="CASCADE"), index=True)
    node_file_id: Mapped[int] = mapped_column(ForeignKey("node_files.id", ondelete="CASCADE"), index=True)
    raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(32))
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    suggested_action: Mapped[str] = mapped_column(String(32), default="undecided")
    suggested_reason: Mapped[str | None] = mapped_column(Text)
    user_action: Mapped[str] = mapped_column(String(32), default="undecided")
    user_reason: Mapped[str | None] = mapped_column(Text)

    group: Mapped[DedupeGroup] = relationship(back_populates="candidates")
    confirmations: Mapped[list["DedupeRemoteConfirmation"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class DedupeRemoteConfirmation(Base):
    __tablename__ = "dedupe_remote_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("dedupe_candidates.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    remote_file_id: Mapped[str | None] = mapped_column(String(64))
    remote_parent_id: Mapped[str | None] = mapped_column(String(64))
    remote_path: Mapped[str | None] = mapped_column(Text)
    remote_name: Mapped[str | None] = mapped_column(Text)
    sha1: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    file_status: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candidate: Mapped[DedupeCandidate] = relationship(back_populates="confirmations")


class DedupeDeletePlan(Base):
    __tablename__ = "dedupe_delete_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("dedupe_scan_runs.id", ondelete="SET NULL"))
    tree_import_id: Mapped[int] = mapped_column(ForeignKey("tree_imports.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    confirm_token: Mapped[str | None] = mapped_column(String(128))
    rate_limit_seconds: Mapped[float] = mapped_column(Float, default=2.0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["DedupeDeletePlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class DedupeDeletePlanItem(TimestampMixin, Base):
    __tablename__ = "dedupe_delete_plan_items"
    __table_args__ = (Index("ix_dedupe_plan_items_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("dedupe_delete_plans.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("dedupe_candidates.id", ondelete="RESTRICT"), index=True)
    node_file_id: Mapped[int] = mapped_column(ForeignKey("node_files.id", ondelete="RESTRICT"), index=True)
    remote_file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_path: Mapped[str] = mapped_column(Text, nullable=False)
    remote_path: Mapped[str | None] = mapped_column(Text)
    confirmation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    delete_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[DedupeDeletePlan] = relationship(back_populates="items")
```

- [ ] **Step 4: Import models for migrations and tests**

Modify `alembic/env.py`:

```python
import app.models.dedupe  # noqa: E402, F401
```

Add the same import to `tests/conftest.py`:

```python
from app.models import dedupe as _dedupe_models  # noqa: F401
```

- [ ] **Step 5: Add migration**

Create `alembic/versions/20260608_0006_dedupe_workbench.py`. Set `revision = "20260608_0006"` and `down_revision = "20260519_0005"`. Implement `upgrade()` with one `op.create_table` call per dedupe table and `op.create_index` calls for:

- `ix_dedupe_groups_status_confidence`
- `ix_dedupe_candidates_user_action`
- `ix_dedupe_plan_items_status`

Implement `downgrade()` in reverse order: drop indexes, then drop `dedupe_delete_plan_items`, `dedupe_delete_plans`, `dedupe_remote_confirmations`, `dedupe_candidates`, `dedupe_groups`, and `dedupe_scan_runs`. Use the column names, nullable settings, foreign keys, and unique constraints exactly as declared in `app/models/dedupe.py`.

- [ ] **Step 6: Run model and migration checks**

Run:

```bash
python -m pytest tests/dedupe/test_dedupe_models.py -q
alembic upgrade head
```

Expected: pytest PASS. Alembic upgrade completes without duplicate-table or missing-revision errors.

- [ ] **Step 7: Commit**

```bash
git add app/models/dedupe.py alembic/env.py alembic/versions/20260608_0006_dedupe_workbench.py tests/conftest.py tests/dedupe/test_dedupe_models.py
git commit -m "feat: add dedupe data model" \
  -m "Introduce the persistent tables needed for local duplicate scan runs, candidate review, remote confirmation, and delete-plan execution." \
  -m "Tested: python -m pytest tests/dedupe/test_dedupe_models.py -q; alembic upgrade head" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 2: Filename Normalization Service

**Files:**
- Create: `app/services/dedupe/__init__.py`
- Create: `app/services/dedupe/normalization.py`
- Test: `tests/dedupe/test_normalization.py`

- [ ] **Step 1: Write failing normalization tests**

Create `tests/dedupe/test_normalization.py`:

```python
from __future__ import annotations

from app.services.dedupe.normalization import DedupeRuleSet, normalize_filename, preview_normalization


def test_normalize_removes_media_noise_and_copy_marker() -> None:
    rules = DedupeRuleSet()
    result = normalize_filename("www.98T.la@Example_1080P (1).MP4", rules)
    assert result.normalized_name == "example"
    assert "site_prefix" in result.applied_rules
    assert "copy_marker" in result.applied_rules


def test_normalize_preserves_series_part_number() -> None:
    rules = DedupeRuleSet()
    result = normalize_filename("Movie.Title.Part2.mkv", rules)
    assert result.normalized_name == "movie title part2"


def test_preview_uses_temporary_noise_words() -> None:
    rows = preview_normalization(
        ["VIP站点@漂亮标题.mp4"],
        DedupeRuleSet(noise_words=["VIP站点"]),
    )
    assert rows[0]["raw_name"] == "VIP站点@漂亮标题.mp4"
    assert rows[0]["normalized_name"] == "漂亮标题"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/dedupe/test_normalization.py -q
```

Expected: FAIL because `app.services.dedupe.normalization` does not exist.

- [ ] **Step 3: Implement normalization**

Create `app/services/dedupe/__init__.py` as an empty package marker.

Create `app/services/dedupe/normalization.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata


DEFAULT_NOISE_WORDS = [
    "www.98t.la",
    "98t.la",
    "高清",
    "全集下面已更新",
]

COPY_MARKER_RE = re.compile(r"(\s|\b)(copy|副本|复制)|[\s._-]*\(\d+\)$", re.IGNORECASE)
QUALITY_RE = re.compile(r"\b(480p|720p|1080p|2160p|4k|x264|x265|h264|h265|hevc)\b", re.IGNORECASE)
SITE_PREFIX_RE = re.compile(r"^[\w.-]{2,40}@")
SEPARATOR_RE = re.compile(r"[\s._\-—–]+")


@dataclass(slots=True)
class DedupeRuleSet:
    noise_words: list[str] = field(default_factory=lambda: list(DEFAULT_NOISE_WORDS))
    regex_patterns: list[str] = field(default_factory=list)
    strip_quality_tags: bool = True
    strip_copy_markers: bool = True


@dataclass(slots=True)
class NormalizedFilename:
    raw_name: str
    normalized_name: str
    tokens: list[str]
    applied_rules: list[str]


def _strip_extension(name: str) -> str:
    suffix = Path(name).suffix
    return name[: -len(suffix)] if suffix else name


def normalize_filename(raw_name: str, rules: DedupeRuleSet | None = None) -> NormalizedFilename:
    active_rules = rules or DedupeRuleSet()
    value = unicodedata.normalize("NFKC", _strip_extension(raw_name)).strip()
    applied: list[str] = []

    lowered = value.lower()
    if SITE_PREFIX_RE.search(lowered):
        value = SITE_PREFIX_RE.sub("", value)
        applied.append("site_prefix")

    for word in active_rules.noise_words:
        if word and word.lower() in value.lower():
            value = re.sub(re.escape(word), "", value, flags=re.IGNORECASE)
            applied.append("noise_word")

    for pattern in active_rules.regex_patterns:
        new_value = re.sub(pattern, "", value, flags=re.IGNORECASE)
        if new_value != value:
            value = new_value
            applied.append("custom_regex")

    if active_rules.strip_quality_tags:
        value = QUALITY_RE.sub("", value)
        applied.append("quality_tag")

    if active_rules.strip_copy_markers and COPY_MARKER_RE.search(value):
        value = COPY_MARKER_RE.sub("", value)
        applied.append("copy_marker")

    value = SEPARATOR_RE.sub(" ", value).strip().lower()
    value = re.sub(r"\s+", " ", value)
    tokens = [part for part in value.split(" ") if part]
    return NormalizedFilename(raw_name=raw_name, normalized_name=value, tokens=tokens, applied_rules=applied)


def preview_normalization(raw_names: list[str], rules: DedupeRuleSet | None = None) -> list[dict[str, object]]:
    return [
        {
            "raw_name": item,
            "normalized_name": normalized.normalized_name,
            "tokens": normalized.tokens,
            "applied_rules": normalized.applied_rules,
        }
        for item in raw_names
        for normalized in [normalize_filename(item, rules)]
    ]
```

- [ ] **Step 4: Run normalization tests**

Run:

```bash
python -m pytest tests/dedupe/test_normalization.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/dedupe/__init__.py app/services/dedupe/normalization.py tests/dedupe/test_normalization.py
git commit -m "feat: add dedupe filename normalization" \
  -m "Add the configurable local filename normalization layer that removes media naming noise while preserving series tokens for later duplicate scoring." \
  -m "Tested: python -m pytest tests/dedupe/test_normalization.py -q" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 3: Local Scan Service And Candidate Ledger

**Files:**
- Create: `app/services/dedupe/scan_service.py`
- Test: `tests/dedupe/test_scan_service.py`

- [ ] **Step 1: Write failing scan tests**

Create `tests/dedupe/test_scan_service.py` with helpers that seed `TreeImport` and `NodeFile` rows:

```python
from __future__ import annotations

from app.models.tree import NodeFile, TreeImport
from app.models.dedupe import DedupeGroup
from app.services.dedupe.scan_service import DedupeScanService, DedupeScanOptions


def _seed_import(db_session):
    tree_import = TreeImport(source_filename="sample.txt", status="completed", note="test")
    db_session.add(tree_import)
    db_session.flush()
    rows = [
        NodeFile(tree_import=tree_import, raw_name="www.98T.la@Example 1080P.mp4", normalized_name="www.98T.la@Example 1080P.mp4", raw_path="根目录/待整理/www.98T.la@Example 1080P.mp4", parent_path="根目录/待整理", depth=2, file_ext=".mp4", fingerprint_hint="a"),
        NodeFile(tree_import=tree_import, raw_name="Example (1).MP4", normalized_name="Example (1).MP4", raw_path="根目录/重复/Example (1).MP4", parent_path="根目录/重复", depth=2, file_ext=".mp4", fingerprint_hint="b"),
        NodeFile(tree_import=tree_import, raw_name="Different Title.mp4", normalized_name="Different Title.mp4", raw_path="根目录/待整理/Different Title.mp4", parent_path="根目录/待整理", depth=2, file_ext=".mp4", fingerprint_hint="c"),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return tree_import.id


def test_scan_creates_persistent_duplicate_group(db_session):
    import_id = _seed_import(db_session)
    summary = DedupeScanService(db_session).scan(
        DedupeScanOptions(tree_import_id=import_id, candidate_threshold=0.82, high_confidence_threshold=0.92)
    )

    assert summary.total_files == 3
    assert summary.total_groups == 1
    group = db_session.query(DedupeGroup).one()
    assert group.confidence_level == "high_probability"
    assert len(group.candidates) == 2


def test_scope_path_prefix_limits_scan(db_session):
    import_id = _seed_import(db_session)
    summary = DedupeScanService(db_session).scan(
        DedupeScanOptions(tree_import_id=import_id, scope_path_prefix="根目录/重复")
    )
    assert summary.total_files == 1
    assert summary.total_groups == 0
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/dedupe/test_scan_service.py -q
```

Expected: FAIL because `DedupeScanService` does not exist.

- [ ] **Step 3: Implement scan service**

Create `app/services/dedupe/scan_service.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from difflib import SequenceMatcher
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeScanRun
from app.models.tree import NodeFile, TreeImport
from app.services.dedupe.normalization import DedupeRuleSet, normalize_filename


MEDIA_EXTENSIONS = [".mp4", ".mkv", ".avi", ".mov"]


@dataclass(slots=True)
class DedupeScanOptions:
    tree_import_id: int
    scope_path_prefix: str | None = None
    included_extensions: list[str] = field(default_factory=lambda: list(MEDIA_EXTENSIONS))
    candidate_threshold: float = 0.82
    high_confidence_threshold: float = 0.92
    rules: DedupeRuleSet = field(default_factory=DedupeRuleSet)


@dataclass(slots=True)
class DedupeScanSummary:
    scan_run_id: int
    total_files: int
    total_groups: int
    total_candidates: int


class DedupeScanService:
    def __init__(self, db: Session):
        self.db = db

    def scan(self, options: DedupeScanOptions) -> DedupeScanSummary:
        tree_import = self.db.get(TreeImport, options.tree_import_id)
        if tree_import is None:
            raise ValueError(f"TreeImport {options.tree_import_id} not found")

        run = DedupeScanRun(
            tree_import_id=options.tree_import_id,
            status="running",
            scope_path_prefix=options.scope_path_prefix,
            included_extensions=",".join(options.included_extensions),
            candidate_threshold=options.candidate_threshold,
            high_confidence_threshold=options.high_confidence_threshold,
            rules_snapshot_json=json.dumps(options.rules.__dict__, ensure_ascii=False),
            started_at=datetime.now(UTC),
        )
        self.db.add(run)
        self.db.flush()

        files = self._load_files(options)
        buckets: dict[str, list[tuple[NodeFile, str]]] = {}
        for row in files:
            normalized = normalize_filename(row.raw_name, options.rules).normalized_name
            if not normalized:
                continue
            buckets.setdefault(self._bucket_key(normalized), []).append((row, normalized))

        total_candidates = 0
        total_groups = 0
        for bucket_rows in buckets.values():
            group_rows, score = self._select_group(bucket_rows, options.candidate_threshold)
            if len(group_rows) < 2:
                continue
            group_key = self._group_key([row.id for row, _ in group_rows])
            normalized_name = group_rows[0][1]
            group = DedupeGroup(
                scan_run_id=run.id,
                tree_import_id=options.tree_import_id,
                group_key=group_key,
                representative_name=group_rows[0][0].raw_name,
                normalized_name=normalized_name,
                score_max=score,
                confidence_level="high_probability" if score >= options.high_confidence_threshold else "filename_suspected",
            )
            self.db.add(group)
            self.db.flush()
            keep_id = self._choose_keep_candidate(group_rows)
            for row, normalized in group_rows:
                action = "keep" if row.id == keep_id else "delete"
                self.db.add(DedupeCandidate(
                    group_id=group.id,
                    node_file_id=row.id,
                    raw_name=row.raw_name,
                    raw_path=row.raw_path,
                    file_ext=row.file_ext,
                    normalized_name=normalized,
                    similarity_score=score,
                    suggested_action=action,
                    suggested_reason=self._suggested_reason(row, action),
                ))
                total_candidates += 1
            total_groups += 1

        run.total_files = len(files)
        run.total_groups = total_groups
        run.total_candidates = total_candidates
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        run.summary_json = json.dumps({"groups": total_groups, "candidates": total_candidates}, ensure_ascii=False)
        self.db.commit()
        return DedupeScanSummary(run.id, len(files), total_groups, total_candidates)

    def _load_files(self, options: DedupeScanOptions) -> list[NodeFile]:
        stmt = select(NodeFile).where(NodeFile.import_id == options.tree_import_id)
        stmt = stmt.where(NodeFile.file_ext.in_([ext.lower() for ext in options.included_extensions]))
        if options.scope_path_prefix:
            stmt = stmt.where(NodeFile.raw_path.startswith(options.scope_path_prefix))
        return list(self.db.scalars(stmt.order_by(NodeFile.id.asc())).all())

    @staticmethod
    def _bucket_key(normalized: str) -> str:
        tokens = normalized.split()
        return " ".join(tokens[:3]) if tokens else normalized[:16]

    @staticmethod
    def _group_key(node_file_ids: list[int]) -> str:
        joined = ",".join(str(item) for item in sorted(node_file_ids))
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _score(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio()

    def _select_group(self, rows: list[tuple[NodeFile, str]], threshold: float) -> tuple[list[tuple[NodeFile, str]], float]:
        selected: set[int] = set()
        best = 0.0
        for (left_row, left_name), (right_row, right_name) in combinations(rows, 2):
            score = self._score(left_name, right_name)
            if score >= threshold:
                selected.update({left_row.id, right_row.id})
                best = max(best, score)
        return [item for item in rows if item[0].id in selected], best

    @staticmethod
    def _choose_keep_candidate(rows: list[tuple[NodeFile, str]]) -> int:
        sorted_rows = sorted(rows, key=lambda item: ("已整理" not in item[0].raw_path, "待整理" in item[0].raw_path, len(item[0].raw_name)))
        return sorted_rows[0][0].id

    @staticmethod
    def _suggested_reason(row: NodeFile, action: str) -> str:
        if action == "keep":
            return "默认保留命名质量或目录优先级更高的文件"
        if "待整理" in row.raw_path or "重复" in row.raw_path or "(1)" in row.raw_name:
            return "路径或文件名命中默认删除策略"
        return "组内非保留项"
```

- [ ] **Step 4: Run scan tests**

Run:

```bash
python -m pytest tests/dedupe/test_scan_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/dedupe/scan_service.py tests/dedupe/test_scan_service.py
git commit -m "feat: scan local tree for duplicate candidates" \
  -m "Implement local-only duplicate candidate detection over imported NodeFile rows with persisted scan runs, groups, and candidates." \
  -m "Tested: python -m pytest tests/dedupe/test_scan_service.py -q" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 4: Dedupe Schemas And Candidate Routes

**Files:**
- Create: `app/schemas/dedupe.py`
- Create: `app/api/routes/dedupe.py`
- Modify: `app/main.py`
- Test: `tests/api/test_dedupe_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/api/test_dedupe_routes.py` with this fixture and tests:

```python
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import deps
from app.db.base import Base
from app.main import app
from app.models import dedupe as _dedupe_models  # noqa: F401
from app.models import keywords as _keywords_models  # noqa: F401
from app.models import organization as _organization_models  # noqa: F401
from app.models import tasks as _task_models  # noqa: F401
from app.models import tree as _tree_models  # noqa: F401


def _client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/dedupe-routes.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[deps.get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()
```

Add tests:

```python
def test_scan_job_endpoint_returns_uuid(client):
    resp = client.post("/dedupe/scan-jobs", json={"tree_import_id": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert len(body["job_id"]) >= 32


def test_list_groups_returns_page_shape(client):
    resp = client.get("/dedupe/groups")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 100}
```

- [ ] **Step 2: Run route tests and verify failure**

Run:

```bash
python -m pytest tests/api/test_dedupe_routes.py -q
```

Expected: FAIL because `/dedupe` routes do not exist.

- [ ] **Step 3: Add schemas**

Create `app/schemas/dedupe.py` with request and response types:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DedupeScanJobRequest(BaseModel):
    tree_import_id: int
    scope_path_prefix: str | None = None
    included_extensions: list[str] = Field(default_factory=lambda: [".mp4", ".mkv", ".avi", ".mov"])
    candidate_threshold: float = Field(default=0.82, ge=0.1, le=1.0)
    high_confidence_threshold: float = Field(default=0.92, ge=0.1, le=1.0)
    noise_words: list[str] = Field(default_factory=list)
    regex_patterns: list[str] = Field(default_factory=list)


class DedupeReviewRequest(BaseModel):
    keep_candidate_ids: list[int] = Field(default_factory=list)
    delete_candidate_ids: list[int] = Field(default_factory=list)
    note: str | None = None


class DedupeGroupResponse(ORMModel):
    id: int
    scan_run_id: int
    tree_import_id: int
    representative_name: str
    normalized_name: str
    score_max: float
    confidence_level: str
    status: str
    review_note: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DedupeCandidateResponse(ORMModel):
    id: int
    group_id: int
    node_file_id: int
    raw_name: str
    raw_path: str
    file_ext: str | None
    normalized_name: str
    similarity_score: float
    suggested_action: str
    suggested_reason: str | None
    user_action: str
    user_reason: str | None


class DedupeGroupDetailResponse(BaseModel):
    group: DedupeGroupResponse
    candidates: list[DedupeCandidateResponse]


class DedupeGroupListResponse(BaseModel):
    items: list[DedupeGroupResponse]
    total: int
    page: int
    page_size: int


class DedupeScanSummary(BaseModel):
    scan_run_id: int
    total_files: int
    total_groups: int
    total_candidates: int


class DedupeJobFrame(BaseModel):
    job_id: str
    job_type: Literal["scan", "confirm", "delete"]
    stage: str
    current: int
    total: int
    done: bool
    error: str | None = None
    summary: dict | None = None
    started_at: datetime
    finished_at: datetime | None = None


class DedupeActiveJobsResponse(BaseModel):
    scan: DedupeJobFrame | None = None
    confirm: DedupeJobFrame | None = None
    delete: DedupeJobFrame | None = None
```

- [ ] **Step 4: Add routes**

Create `app/api/routes/dedupe.py`. Follow `app/api/routes/whitelist_batch.py` for `_jobs`, locks, SSE, active jobs, and sweeper. Implement:

```python
router = APIRouter(prefix="/dedupe", tags=["dedupe"])

@router.post("/scan-jobs")
async def start_scan_job(payload: DedupeScanJobRequest) -> dict:
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="已有去重扫描任务在运行")
    job_id = _new_job("scan")
    asyncio.create_task(_run_scan_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}

@router.get("/groups", response_model=DedupeGroupListResponse)
def list_groups(status: str | None = None, confidence_level: str | None = None, page: int = 1, page_size: int = 100, db: Session = Depends(get_db)) -> DedupeGroupListResponse:
    stmt = select(DedupeGroup)
    if status:
        stmt = stmt.where(DedupeGroup.status == status)
    if confidence_level:
        stmt = stmt.where(DedupeGroup.confidence_level == confidence_level)
    rows = list(db.scalars(stmt.order_by(DedupeGroup.id.desc())).all())
    safe_page_size = max(1, min(page_size, 500))
    offset = (max(1, page) - 1) * safe_page_size
    items = rows[offset : offset + safe_page_size]
    return DedupeGroupListResponse(items=[DedupeGroupResponse.model_validate(row) for row in items], total=len(rows), page=page, page_size=safe_page_size)

@router.get("/groups/{group_id}", response_model=DedupeGroupDetailResponse)
def get_group(group_id: int, db: Session = Depends(get_db)) -> DedupeGroupDetailResponse:
    group = db.get(DedupeGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Dedupe group not found")
    candidates = list(db.scalars(select(DedupeCandidate).where(DedupeCandidate.group_id == group_id).order_by(DedupeCandidate.id.asc())).all())
    return DedupeGroupDetailResponse(group=DedupeGroupResponse.model_validate(group), candidates=[DedupeCandidateResponse.model_validate(row) for row in candidates])

@router.post("/groups/{group_id}/review")
def review_group(group_id: int, payload: DedupeReviewRequest, db: Session = Depends(get_db)) -> dict:
    group = db.get(DedupeGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Dedupe group not found")
    candidates = list(db.scalars(select(DedupeCandidate).where(DedupeCandidate.group_id == group_id)).all())
    keep_ids = set(payload.keep_candidate_ids)
    delete_ids = set(payload.delete_candidate_ids)
    for candidate in candidates:
        if candidate.id in keep_ids:
            candidate.user_action = "keep"
        elif candidate.id in delete_ids:
            candidate.user_action = "delete"
        else:
            candidate.user_action = "undecided"
    group.status = "confirmed"
    group.review_note = payload.note
    db.commit()
    return {"group_id": group.id, "status": group.status}
```

In `review_group`, set matching candidate `user_action` values to `keep` or `delete`, set `group.status = "confirmed"`, write `group.review_note`, and commit.

- [ ] **Step 5: Register route in app**

Modify `app/main.py`:

```python
from app.api.routes import dedupe
```

If `app/main.py` keeps the existing multi-line route import tuple, add `dedupe` to that tuple. Then register the router after the existing workbench routes:

```python
app.include_router(dedupe.router)
```

Start/stop the dedupe sweeper in lifespan:

```python
from app.api.routes.dedupe import _sweep_jobs as _sweep_dedupe_jobs
app.state.dedupe_job_sweeper = asyncio.create_task(_sweep_dedupe_jobs())
```

In the shutdown section:

```python
dedupe_sweeper = getattr(app.state, "dedupe_job_sweeper", None)
if dedupe_sweeper is not None:
    dedupe_sweeper.cancel()
```

- [ ] **Step 6: Run route tests**

Run:

```bash
python -m pytest tests/api/test_dedupe_routes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/dedupe.py app/api/routes/dedupe.py app/main.py tests/api/test_dedupe_routes.py
git commit -m "feat: add dedupe candidate API" \
  -m "Expose scan jobs, active job state, candidate group listing, detail, and review endpoints for the dedupe workbench." \
  -m "Tested: python -m pytest tests/api/test_dedupe_routes.py -q" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 5: Remote Confirmation Service

**Files:**
- Create: `app/services/dedupe/confirmation_service.py`
- Modify: `app/api/routes/dedupe.py`
- Modify: `app/schemas/dedupe.py`
- Test: `tests/dedupe/test_confirmation_service.py`

- [ ] **Step 1: Write failing confirmation tests**

Create `tests/dedupe/test_confirmation_service.py`:

```python
from __future__ import annotations

from app.models.dedupe import DedupeCandidate, DedupeGroup, DedupeScanRun
from app.models.tree import NodeFile, TreeImport
from app.services.client_115.client import Fake115Client
from app.services.client_115.schemas import NodePayload
from app.services.dedupe.confirmation_service import DedupeConfirmationService


def _seed_candidate(db_session):
    tree_import = TreeImport(source_filename="tree.txt", status="completed")
    db_session.add(tree_import)
    db_session.flush()
    node = NodeFile(tree_import=tree_import, raw_name="Example.mp4", normalized_name="Example.mp4", raw_path="根目录/待整理/Example.mp4", parent_path="根目录/待整理", depth=2, file_ext=".mp4", fingerprint_hint="fp")
    db_session.add(node)
    db_session.flush()
    run = DedupeScanRun(tree_import_id=tree_import.id, status="completed")
    db_session.add(run)
    db_session.flush()
    group = DedupeGroup(scan_run_id=run.id, tree_import_id=tree_import.id, group_key="g", representative_name="Example.mp4", normalized_name="example", score_max=0.99)
    db_session.add(group)
    db_session.flush()
    candidate = DedupeCandidate(group_id=group.id, node_file_id=node.id, raw_name=node.raw_name, raw_path=node.raw_path, normalized_name="example", user_action="delete")
    db_session.add(candidate)
    db_session.commit()
    return candidate.id, group.id


def test_confirm_selected_candidate_resolves_remote_file(db_session):
    candidate_id, group_id = _seed_candidate(db_session)
    client = Fake115Client()
    client.add_node(NodePayload(id="10", name="待整理", path="待整理", parent_id=None, is_file=False))
    client.add_node(NodePayload(id="11", name="Example.mp4", path="待整理/Example.mp4", parent_id="10", is_file=True))

    result = DedupeConfirmationService(db_session, client).confirm_candidates([candidate_id])

    assert result.resolved == 1
    candidate = db_session.get(DedupeCandidate, candidate_id)
    assert candidate.confirmations[-1].remote_file_id == "11"
    assert db_session.get(DedupeGroup, group_id).confidence_level in {"high_probability", "verified_duplicate"}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/dedupe/test_confirmation_service.py -q
```

Expected: FAIL because the confirmation service does not exist.

- [ ] **Step 3: Implement confirmation service**

Create `app/services/dedupe/confirmation_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dedupe import DedupeCandidate, DedupeRemoteConfirmation
from app.services.client_115.client import Client115Error


@dataclass(slots=True)
class DedupeConfirmationSummary:
    requested: int
    resolved: int
    failed: int


class DedupeConfirmationService:
    def __init__(self, db: Session, client):
        self.db = db
        self.client = client

    def confirm_candidates(self, candidate_ids: list[int]) -> DedupeConfirmationSummary:
        candidates = list(self.db.scalars(select(DedupeCandidate).where(DedupeCandidate.id.in_(candidate_ids))).all())
        resolved = failed = 0
        for candidate in candidates:
            try:
                remote_file_id = self._resolve_path_to_id(candidate.raw_path)
                data = self.client.get_file(file_id=remote_file_id).get("data", {})
                confirmation = DedupeRemoteConfirmation(
                    candidate_id=candidate.id,
                    status="resolved",
                    remote_file_id=remote_file_id,
                    remote_parent_id=str(data.get("parent_id")) if data.get("parent_id") is not None else None,
                    remote_path=self.client.get_full_path(remote_file_id) if hasattr(self.client, "get_full_path") else candidate.raw_path,
                    remote_name=data.get("file_name") or candidate.raw_name,
                    sha1=data.get("sha1") or data.get("file_sha1"),
                    size_bytes=int(data["file_size"]) if data.get("file_size") not in (None, "") else None,
                    file_status=str(data.get("area_id")) if data.get("area_id") is not None else None,
                )
                self.db.add(confirmation)
                resolved += 1
            except Exception as exc:
                self.db.add(DedupeRemoteConfirmation(candidate_id=candidate.id, status="not_found", error_message=str(exc)))
                failed += 1
        self._refresh_group_confidence(candidate_ids)
        self.db.commit()
        return DedupeConfirmationSummary(len(candidate_ids), resolved, failed)

    def _resolve_path_to_id(self, path: str) -> str:
        parts = self.client.path_parts_for_display_path(path) if hasattr(self.client, "path_parts_for_display_path") else [part for part in path.strip("/").split("/") if part and part != "根目录"]
        current_id = "0"
        for part in parts:
            listing = self.client.list_files(cid=current_id, limit=500, offset=0, show_dir=1)
            matches = [item for item in listing.get("data", []) if item.get("fn") == part]
            if len(matches) != 1:
                raise Client115Error(f"Path segment is ambiguous or missing: {part}")
            current_id = str(matches[0].get("fid"))
        return current_id

    def _refresh_group_confidence(self, candidate_ids: list[int]) -> None:
        candidates = list(self.db.scalars(select(DedupeCandidate).where(DedupeCandidate.id.in_(candidate_ids))).all())
        for candidate in candidates:
            if candidate.group and candidate.confirmations:
                candidate.group.confidence_level = "high_probability"
```

Keep exact SHA/size promotion conservative in this task: if SHA is unavailable from the client response, the group remains `high_probability`; promote to `verified_duplicate` only when at least two delete/keep candidates in the same group have matching non-empty SHA values or matching non-null `size_bytes`.

- [ ] **Step 4: Wire confirm job route**

Extend `app/schemas/dedupe.py`:

```python
class DedupeConfirmJobRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)
```

Extend `app/api/routes/dedupe.py`:

```python
@router.post("/confirm-jobs")
async def start_confirm_job(payload: DedupeConfirmJobRequest) -> dict:
    if _confirm_lock.locked():
        raise HTTPException(status_code=409, detail="已有去重确认任务在运行")
    job_id = _new_job("confirm")
    asyncio.create_task(_run_confirm_job(job_id, payload))
    return {"job_id": job_id, "status": "pending"}
```

Use the same `_run_blocking_job` pattern as scan jobs. Construct `DedupeConfirmationService(session, Real115Client())` in the blocking worker.

- [ ] **Step 5: Run confirmation tests**

Run:

```bash
python -m pytest tests/dedupe/test_confirmation_service.py tests/api/test_dedupe_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/dedupe/confirmation_service.py app/schemas/dedupe.py app/api/routes/dedupe.py tests/dedupe/test_confirmation_service.py tests/api/test_dedupe_routes.py
git commit -m "feat: confirm dedupe candidates remotely" \
  -m "Add the explicit remote confirmation step that resolves selected local candidates to 115 file ids and stores API-derived file details." \
  -m "Tested: python -m pytest tests/dedupe/test_confirmation_service.py tests/api/test_dedupe_routes.py -q" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 6: Delete Plan Service And Execution

**Files:**
- Create: `app/services/dedupe/delete_plan_service.py`
- Modify: `app/api/routes/dedupe.py`
- Modify: `app/schemas/dedupe.py`
- Test: `tests/dedupe/test_delete_plan_service.py`

- [ ] **Step 1: Write failing delete-plan tests**

Create `tests/dedupe/test_delete_plan_service.py` with two cases:

```python
def test_create_plan_requires_resolved_remote_file_id(db_session):
    service = DedupeDeletePlanService(db_session, client=None)
    with pytest.raises(ValueError, match="remote confirmation"):
        service.create_plan(name="bad", candidate_ids=[999], rate_limit_seconds=2.0)


def test_execute_plan_deletes_each_pending_item(db_session, fake_client):
    plan_id, remote_file_id = _seed_resolved_delete_plan(db_session, fake_client)
    summary = DedupeDeletePlanService(db_session, fake_client).execute_plan(plan_id, confirm=True, sleep_seconds=0)
    assert summary.deleted == 1
    assert remote_file_id not in fake_client.nodes
```

Include a `_seed_resolved_delete_plan` helper that creates a candidate with `user_action="delete"`, a `DedupeRemoteConfirmation(status="resolved", remote_file_id="file-1")`, and a matching `Fake115Client` node.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/dedupe/test_delete_plan_service.py -q
```

Expected: FAIL because `DedupeDeletePlanService` does not exist.

- [ ] **Step 3: Implement delete plan service**

Create `app/services/dedupe/delete_plan_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dedupe import DedupeCandidate, DedupeDeletePlan, DedupeDeletePlanItem, DedupeRemoteConfirmation


@dataclass(slots=True)
class DedupeDeletePlanSummary:
    plan_id: int
    total: int
    deleted: int
    failed: int
    skipped: int


class DedupeDeletePlanService:
    def __init__(self, db: Session, client):
        self.db = db
        self.client = client

    def create_plan(self, *, name: str, candidate_ids: list[int], rate_limit_seconds: float = 2.0) -> DedupeDeletePlan:
        candidates = list(self.db.scalars(select(DedupeCandidate).where(DedupeCandidate.id.in_(candidate_ids))).all())
        if not candidates:
            raise ValueError("No candidates selected")
        plan = DedupeDeletePlan(name=name, tree_import_id=candidates[0].group.tree_import_id, source_scan_run_id=candidates[0].group.scan_run_id, rate_limit_seconds=rate_limit_seconds)
        self.db.add(plan)
        self.db.flush()
        for candidate in candidates:
            if candidate.user_action != "delete":
                raise ValueError(f"Candidate {candidate.id} is not marked for delete")
            confirmation = self._latest_resolved_confirmation(candidate.id)
            if confirmation is None or not confirmation.remote_file_id:
                raise ValueError(f"Candidate {candidate.id} has no resolved remote confirmation")
            self.db.add(DedupeDeletePlanItem(
                plan_id=plan.id,
                candidate_id=candidate.id,
                node_file_id=candidate.node_file_id,
                remote_file_id=confirmation.remote_file_id,
                raw_path=candidate.raw_path,
                remote_path=confirmation.remote_path,
                confirmation_level=candidate.group.confidence_level,
                delete_reason=candidate.user_reason or candidate.suggested_reason or "人工确认删除",
            ))
        plan.total_items = len(candidates)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def execute_plan(self, plan_id: int, *, confirm: bool, sleep_seconds: float | None = None) -> DedupeDeletePlanSummary:
        if not confirm:
            raise ValueError("confirm must be true")
        plan = self.db.get(DedupeDeletePlan, plan_id)
        if plan is None:
            raise ValueError(f"Delete plan {plan_id} not found")
        plan.status = "running"
        plan.confirmed_at = plan.confirmed_at or datetime.now(UTC)
        plan.started_at = datetime.now(UTC)
        self.db.commit()

        deleted = failed = skipped = 0
        delay = plan.rate_limit_seconds if sleep_seconds is None else sleep_seconds
        for item in plan.items:
            if item.status != "pending":
                skipped += 1
                continue
            try:
                item.status = "deleting"
                self.db.commit()
                self.client.delete_node(item.remote_file_id, dry_run=False)
                item.status = "deleted"
                item.deleted_at = datetime.now(UTC)
                deleted += 1
            except Exception as exc:
                item.status = "failed"
                item.error_message = str(exc)
                failed += 1
            self.db.commit()
            if delay > 0:
                time.sleep(delay)

        plan.deleted_count = deleted
        plan.failed_count = failed
        plan.skipped_count = skipped
        plan.status = "completed_with_errors" if failed else "completed"
        plan.finished_at = datetime.now(UTC)
        self.db.commit()
        return DedupeDeletePlanSummary(plan.id, len(plan.items), deleted, failed, skipped)

    def _latest_resolved_confirmation(self, candidate_id: int) -> DedupeRemoteConfirmation | None:
        return self.db.scalar(
            select(DedupeRemoteConfirmation)
            .where(DedupeRemoteConfirmation.candidate_id == candidate_id)
            .where(DedupeRemoteConfirmation.status == "resolved")
            .order_by(DedupeRemoteConfirmation.id.desc())
        )
```

- [ ] **Step 4: Add delete-plan schemas and routes**

Add to `app/schemas/dedupe.py`:

```python
class DedupeDeletePlanCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    candidate_ids: list[int] = Field(min_length=1)
    rate_limit_seconds: float = Field(default=2.0, ge=0.0, le=30.0)


class DedupeDeletePlanExecuteRequest(BaseModel):
    confirm: bool = False
```

Add route handlers with these behaviors:

- `POST /dedupe/delete-plans`
  - call `DedupeDeletePlanService(db, client=None).create_plan(name=payload.name, candidate_ids=payload.candidate_ids, rate_limit_seconds=payload.rate_limit_seconds)`
  - return `{"plan_id": plan.id, "status": plan.status, "total_items": plan.total_items}`
- `GET /dedupe/delete-plans/{plan_id}`
  - return the plan header and items; respond `404` when missing
- `POST /dedupe/delete-plans/{plan_id}/execute-jobs`
  - require payload `confirm: true`
  - return `409` when a delete job is already running
  - create a `delete` job and execute `DedupeDeletePlanService(session, Real115Client()).execute_plan(plan_id, confirm=True)` in the blocking worker

- [ ] **Step 5: Run delete-plan tests**

Run:

```bash
python -m pytest tests/dedupe/test_delete_plan_service.py tests/api/test_dedupe_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/dedupe/delete_plan_service.py app/schemas/dedupe.py app/api/routes/dedupe.py tests/dedupe/test_delete_plan_service.py tests/api/test_dedupe_routes.py
git commit -m "feat: add dedupe delete plans" \
  -m "Route confirmed duplicate candidates through second-confirmation delete plans with per-item execution state and conservative rate limiting." \
  -m "Tested: python -m pytest tests/dedupe/test_delete_plan_service.py tests/api/test_dedupe_routes.py -q" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 7: Frontend API Client

**Files:**
- Create: `frontend/src/api/dedupe.ts`
- Test: frontend TypeScript build

- [ ] **Step 1: Add the typed client**

Create `frontend/src/api/dedupe.ts`:

```ts
import { api } from './client'

export interface DedupeScanJobRequest {
  tree_import_id: number
  scope_path_prefix?: string | null
  included_extensions?: string[]
  candidate_threshold?: number
  high_confidence_threshold?: number
  noise_words?: string[]
  regex_patterns?: string[]
}

export interface DedupeJobFrame {
  job_id: string
  job_type: 'scan' | 'confirm' | 'delete'
  stage: string
  current: number
  total: number
  done: boolean
  error: string | null
  summary: Record<string, unknown> | null
  started_at: string
  finished_at: string | null
}

export interface DedupeGroup {
  id: number
  scan_run_id: number
  tree_import_id: number
  representative_name: string
  normalized_name: string
  score_max: number
  confidence_level: string
  status: string
  review_note: string | null
}

export interface DedupeCandidate {
  id: number
  group_id: number
  node_file_id: number
  raw_name: string
  raw_path: string
  file_ext: string | null
  normalized_name: string
  similarity_score: number
  suggested_action: string
  suggested_reason: string | null
  user_action: string
  user_reason: string | null
}

export interface DedupeGroupListResponse {
  items: DedupeGroup[]
  total: number
  page: number
  page_size: number
}

export interface DedupeGroupDetailResponse {
  group: DedupeGroup
  candidates: DedupeCandidate[]
}

export function startDedupeScanJob(payload: DedupeScanJobRequest) {
  return api.post<{ job_id: string; status: string }>('/dedupe/scan-jobs', payload)
}

export function listDedupeGroups(params: Record<string, string | number | undefined>) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') q.set(key, String(value))
  })
  return api.get<DedupeGroupListResponse>(`/dedupe/groups${q.toString() ? '?' + q.toString() : ''}`)
}

export function getDedupeGroup(id: number) {
  return api.get<DedupeGroupDetailResponse>(`/dedupe/groups/${id}`)
}

export function reviewDedupeGroup(id: number, payload: { keep_candidate_ids: number[]; delete_candidate_ids: number[]; note?: string | null }) {
  return api.post<{ group_id: number; status: string }>(`/dedupe/groups/${id}/review`, payload)
}

export function subscribeDedupeJob(jobId: string, onFrame: (frame: DedupeJobFrame | { error: string }) => void, onDone?: (frame: DedupeJobFrame) => void) {
  const es = new EventSource(`/api/dedupe/jobs/${jobId}/progress`)
  es.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onFrame(data)
    if (data.done) {
      es.close()
      onDone?.(data as DedupeJobFrame)
    }
  }
  es.onerror = () => es.close()
  return () => es.close()
}
```

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/dedupe.ts
git commit -m "feat: add dedupe frontend API client" \
  -m "Add typed frontend API helpers for dedupe scan jobs, candidate group listing, detail loading, review, and SSE progress." \
  -m "Tested: cd frontend && npm run build" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 8: Frontend Workbench Page

**Files:**
- Create: `frontend/src/pages/FileDedupePage.tsx`
- Modify: `frontend/src/App.tsx`
- Test: frontend lint/build and browser check

- [ ] **Step 1: Add page skeleton**

Create `frontend/src/pages/FileDedupePage.tsx` with an AntD three-column layout:

```tsx
import { useEffect, useState } from 'react'
import { Button, Card, Col, Form, Input, InputNumber, Progress, Row, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined, ScanOutlined } from '@ant-design/icons'

import { api } from '../api/client'
import type { ImportListResponse, TreeImport } from '../api/types'
import {
  getDedupeGroup,
  listDedupeGroups,
  reviewDedupeGroup,
  startDedupeScanJob,
  subscribeDedupeJob,
  type DedupeCandidate,
  type DedupeGroup,
  type DedupeJobFrame,
} from '../api/dedupe'

const { Title, Text } = Typography

export default function FileDedupePage() {
  const [imports, setImports] = useState<TreeImport[]>([])
  const [selectedImportId, setSelectedImportId] = useState<number>()
  const [groups, setGroups] = useState<DedupeGroup[]>([])
  const [total, setTotal] = useState(0)
  const [selectedGroup, setSelectedGroup] = useState<DedupeGroup | null>(null)
  const [candidates, setCandidates] = useState<DedupeCandidate[]>([])
  const [scanJob, setScanJob] = useState<DedupeJobFrame | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.get<ImportListResponse>('/imports/data?limit=100').then((body) => {
      setImports(body.items)
      setSelectedImportId(body.items[0]?.id)
    }).catch(() => message.error('加载目录树批次失败'))
    void loadGroups()
  }, [])

  async function loadGroups() {
    setLoading(true)
    try {
      const body = await listDedupeGroups({ page: 1, page_size: 100 })
      setGroups(body.items)
      setTotal(body.total)
    } finally {
      setLoading(false)
    }
  }

  async function handleScan(values: { scope_path_prefix?: string; candidate_threshold?: number; high_confidence_threshold?: number; noise_words?: string }) {
    if (!selectedImportId) {
      message.warning('请先选择目录树批次')
      return
    }
    const resp = await startDedupeScanJob({
      tree_import_id: selectedImportId,
      scope_path_prefix: values.scope_path_prefix || null,
      candidate_threshold: values.candidate_threshold ?? 0.82,
      high_confidence_threshold: values.high_confidence_threshold ?? 0.92,
      noise_words: values.noise_words?.split('\\n').map((item) => item.trim()).filter(Boolean) ?? [],
    })
    subscribeDedupeJob(resp.job_id, (frame) => {
      if ('job_id' in frame) setScanJob(frame)
    }, () => {
      message.success('去重扫描完成')
      void loadGroups()
    })
  }

  async function openGroup(group: DedupeGroup) {
    const detail = await getDedupeGroup(group.id)
    setSelectedGroup(detail.group)
    setCandidates(detail.candidates)
  }

  async function markReview() {
    if (!selectedGroup) return
    const keep = candidates.filter((item) => item.suggested_action === 'keep').map((item) => item.id)
    const del = candidates.filter((item) => item.suggested_action === 'delete').map((item) => item.id)
    await reviewDedupeGroup(selectedGroup.id, { keep_candidate_ids: keep, delete_candidate_ids: del, note: '按系统建议确认' })
    message.success('已保存审批')
    await loadGroups()
  }

  const columns: ColumnsType<DedupeGroup> = [
    { title: '代表文件名', dataIndex: 'representative_name', ellipsis: true },
    { title: '归一化名', dataIndex: 'normalized_name', ellipsis: true },
    { title: '分数', dataIndex: 'score_max', width: 90, render: (v: number) => v.toFixed(2) },
    { title: '等级', dataIndex: 'confidence_level', width: 130, render: (v: string) => <Tag>{v}</Tag> },
    { title: '状态', dataIndex: 'status', width: 130 },
    { title: '操作', key: 'action', width: 100, render: (_, row) => <Button size="small" onClick={() => void openGroup(row)}>详情</Button> },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Title level={3} style={{ margin: 0 }}>文件去重</Title>
      <Row gutter={16} align="top">
        <Col span={6}>
          <Card title="扫描与规则">
            <Form layout="vertical" onFinish={(values) => void handleScan(values)} initialValues={{ candidate_threshold: 0.82, high_confidence_threshold: 0.92 }}>
              <Form.Item label="目录树批次">
                <Select value={selectedImportId} onChange={setSelectedImportId} options={imports.map((item) => ({ value: item.id, label: `#${item.id} ${item.source_filename}` }))} />
              </Form.Item>
              <Form.Item name="scope_path_prefix" label="扫描范围">
                <Input placeholder="根目录/待整理" />
              </Form.Item>
              <Form.Item name="candidate_threshold" label="入队阈值">
                <InputNumber min={0.1} max={1} step={0.01} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="high_confidence_threshold" label="高概率阈值">
                <InputNumber min={0.1} max={1} step={0.01} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="noise_words" label="临时噪音词">
                <Input.TextArea rows={5} placeholder="每行一个" />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<ScanOutlined />}>启动本地扫描</Button>
            </Form>
            {scanJob && <Progress percent={scanJob.total ? Math.round((scanJob.current / scanJob.total) * 100) : scanJob.done ? 100 : 0} style={{ marginTop: 16 }} />}
            <Text type="secondary">扫描阶段只分析本地目录树，不调用 115 文件搜索 API。</Text>
          </Card>
        </Col>
        <Col span={12}>
          <Card title={`候选组 ${total}`} extra={<Button icon={<ReloadOutlined />} onClick={() => void loadGroups()}>刷新</Button>}>
            <Table rowKey="id" loading={loading} dataSource={groups} columns={columns} pagination={{ pageSize: 100 }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card title="详情与审批">
            {!selectedGroup && <Text type="secondary">选择一个候选组查看详情。</Text>}
            {selectedGroup && (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Text strong>{selectedGroup.representative_name}</Text>
                {candidates.map((item) => (
                  <Card size="small" key={item.id}>
                    <Tag color={item.suggested_action === 'delete' ? 'red' : 'green'}>{item.suggested_action}</Tag>
                    <div>{item.raw_name}</div>
                    <Text type="secondary">{item.raw_path}</Text>
                  </Card>
                ))}
                <Button type="primary" onClick={() => void markReview()}>按建议保存审批</Button>
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
```

- [ ] **Step 2: Register navigation**

Modify `frontend/src/App.tsx`:

- Import `FileDedupePage`.
- Add a nav item `{ key: '/dedupe', label: '文件去重', icon: <ScanOutlined /> }`.
- Add route `<Route path="/dedupe" element={<FileDedupePage />} />`.

- [ ] **Step 3: Verify frontend**

Run:

```bash
cd frontend && npm run lint && npm run build
```

Expected: PASS.

- [ ] **Step 4: Browser check**

Start the app through the repo's existing dev workflow, open `/dedupe`, and verify:

- The page loads.
- The left nav item appears.
- Directory-tree batches load in the select.
- Candidate table renders empty state without crashing.
- The warning text says scan does not call 115 file search.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/FileDedupePage.tsx frontend/src/App.tsx
git commit -m "feat: add file dedupe workbench page" \
  -m "Add the first React workbench surface for selecting tree imports, launching local scans, reviewing duplicate groups, and saving suggested reviews." \
  -m "Tested: cd frontend && npm run lint && npm run build; browser check /dedupe" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

---

### Task 9: End-To-End Verification And Deployment Notes

**Files:**
- Modify: `docs/superpowers/specs/2026-06-08-file-dedupe-workbench-design.md` only if implementation discoveries require a design note.

- [ ] **Step 1: Run backend test suite**

Run:

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend checks**

Run:

```bash
cd frontend && npm run lint && npm run build
```

Expected: PASS.

- [ ] **Step 3: Run database migration check**

Run:

```bash
alembic upgrade head
```

Expected: PASS.

- [ ] **Step 4: Browser verification**

Start the local app, open `/dedupe`, and verify the workbench is visible. Use a known imported tree batch or create a tiny test import through `/imports`; launch scan and confirm a candidate group appears for two similar media filenames.

- [ ] **Step 5: Confirm git status**

Run:

```bash
git status --short
```

Expected: only intentionally untracked user files remain, especially `根目录20260419_目录树.txt` if it is still untracked.

- [ ] **Step 6: Commit final verification note only if docs changed**

If implementation discoveries required a spec note:

```bash
git add docs/superpowers/specs/2026-06-08-file-dedupe-workbench-design.md
git commit -m "docs: update dedupe implementation notes" \
  -m "Record implementation-specific notes discovered while building the approved file dedupe workbench." \
  -m "Tested: python -m pytest -q; cd frontend && npm run lint && npm run build; alembic upgrade head" \
  -m "Confidence: medium" \
  -m "Co-authored-by: OmX <omx@oh-my-codex.dev>"
```

If docs did not change, do not create an empty commit.

## Handoff Checklist

- Backend scan must remain local-only; do not call `search_nodes()` from scan code.
- Confirmation and deletion must use explicit user-selected candidates.
- Delete execution must require delete-plan confirmation.
- Do not sync or modify server files. After implementation, push GitHub first, then provide the server pull/migrate/rebuild flow for user approval.
