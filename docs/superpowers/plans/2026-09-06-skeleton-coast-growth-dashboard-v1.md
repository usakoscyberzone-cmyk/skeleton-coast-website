# Skeleton Coast Growth Dashboard V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private hybrid YouTube growth system for Skeleton Coast Fishing Adventures & Tours that watches `I:\YouTube Projects`, connects read-only to YouTube Analytics, creates supporting assets, and gives evidence-based recommendations without modifying YouTube or DaVinci automatically.

**Architecture:** A Python Windows helper watches and analyzes local project folders, while a local/private web application exposes a browser dashboard and stores normalized project/analytics data in SQLite. The backend uses FastAPI and background jobs; the frontend uses React + TypeScript. YouTube integration is OAuth-based and read-only. Asset generation and recommendation logic are isolated services so they can be tested independently.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite, Pydantic v2, watchdog, ffprobe/FFmpeg, google-api-python-client, google-auth-oauthlib, pytest, React 18, TypeScript, Vite, Vitest, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-06-skeleton-coast-growth-dashboard-design.md`

## Global Constraints

- Version 1 supports exactly one YouTube channel: Skeleton Coast Fishing Adventures & Tours.
- Master project folder is `I:\YouTube Projects`.
- The Windows helper may read/analyze local files and create new assets only.
- The Windows helper must never modify DaVinci Resolve projects or timelines.
- YouTube access is read-only in Version 1.
- The system must never fabricate views, automate engagement, or manipulate watch-time metrics.
- Recommendations may be generated automatically, but no YouTube change may be applied automatically.
- Generated assets must be saved inside the relevant project folder.
- Every recommendation must expose Action, Reason, Confidence, and Data Used.
- Recommendations must avoid acting on very small samples.
- Prefer channel-specific historical baselines over generic benchmarks when enough channel data exists.
- Home screen must prioritize the question: **What should I do next?**

---

## Scope Decomposition

The approved specification contains four substantial subsystems. They are implemented in this order so every phase leaves working, testable software:

1. **Foundation + Windows helper** — project discovery, folder creation, local media metadata.
2. **YouTube analytics + dashboard** — read-only channel connection, storage, core screens.
3. **Recommendation engine + learning library** — Green/Amber/Red decisions and historical baselines.
4. **Asset generation + Shorts funnel** — metadata packs, captions, cut lists, thumbnails, performance reports.

This plan keeps those phases in one ordered document because later phases consume interfaces defined by earlier phases, but each task is independently testable and reviewable.

---

## File Structure

```text
skeleton-coast-growth-dashboard/
  apps/
    api/
      app/
        main.py                    # FastAPI application factory and routes mount
        config.py                  # Environment/config loading
        db.py                      # SQLAlchemy engine/session lifecycle
        models.py                  # Core persistence models
        schemas.py                 # Shared API request/response models
        routes/
          health.py                # Health endpoint
          projects.py              # Project discovery/read APIs
          youtube.py               # OAuth + analytics read APIs
          recommendations.py       # Recommendation read APIs
          assets.py                # Asset generation API
        services/
          project_scanner.py       # Project folder discovery and normalization
          media_probe.py           # ffprobe wrapper
          youtube_client.py        # Read-only YouTube/Analytics client
          analytics_ingest.py      # Normalize YouTube metrics into DB
          recommendation_engine.py # Green/Amber/Red and action logic
          baselines.py             # Channel-specific comparison baselines
          asset_generator.py       # Metadata/caption/report asset generation
          shorts_funnel.py         # Short plan persistence/classification
      tests/
        test_health.py
        test_project_scanner.py
        test_media_probe.py
        test_youtube_client.py
        test_analytics_ingest.py
        test_recommendation_engine.py
        test_baselines.py
        test_asset_generator.py
        test_shorts_funnel.py
      pyproject.toml
    web/
      src/
        main.tsx
        api/client.ts
        types.ts
        pages/
          HomePage.tsx
          ProjectsPage.tsx
          ProjectDetailPage.tsx
          AnalyticsPage.tsx
          RecommendationsPage.tsx
          LearningPage.tsx
        components/
          StatusBadge.tsx
          NextActions.tsx
          MetricCard.tsx
          ProjectCard.tsx
          PackagingPanel.tsx
          ShortsFunnelPanel.tsx
      tests/
        HomePage.test.tsx
        ProjectsPage.test.tsx
        RecommendationsPage.test.tsx
      package.json
      vite.config.ts
  helper/
    skeleton_helper/
      __main__.py                  # Windows helper CLI entry point
      watcher.py                   # watchdog integration
      sync_client.py               # push project scan results to API
      settings.py                  # master-folder/API settings
    tests/
      test_watcher.py
      test_sync_client.py
    pyproject.toml
  docs/
    setup-windows.md               # Install/run helper + FFmpeg + env settings
    youtube-oauth.md               # Read-only YouTube OAuth setup
  .env.example
  README.md
```

---

### Task 1: Bootstrap the API and persistence foundation

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/app/main.py`
- Create: `apps/api/app/config.py`
- Create: `apps/api/app/db.py`
- Create: `apps/api/app/models.py`
- Create: `apps/api/app/schemas.py`
- Create: `apps/api/app/routes/health.py`
- Create: `apps/api/tests/test_health.py`
- Create: `.env.example`

**Interfaces:**
- Produces: `create_app() -> FastAPI`
- Produces: `get_settings() -> Settings`
- Produces: `get_session() -> Iterator[Session]`
- Produces persistence entities `Project`, `MediaFile`, `VideoMetricSnapshot`, `Recommendation`, `ShortPlan`, `LearningPattern`.

- [ ] **Step 1: Write the failing health/API boot test**

```python
from fastapi.testclient import TestClient
from app.main import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd apps/api && pytest tests/test_health.py -v`

Expected: FAIL because `app.main` does not exist.

- [ ] **Step 3: Create minimal FastAPI app, config, and SQLite session setup**

```python
# apps/api/app/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./skeleton_growth.db"
    master_project_folder: str = r"I:\YouTube Projects"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# apps/api/app/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

```python
# apps/api/app/routes/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

```python
# apps/api/app/main.py
from fastapi import FastAPI
from .routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Skeleton Coast Growth Dashboard")
    app.include_router(health_router)
    return app


app = create_app()
```

- [ ] **Step 4: Add persistence models and create tables at app startup**

Define these minimum fields:

```python
# apps/api/app/models.py
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MediaFile(Base):
    __tablename__ = "media_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)


class VideoMetricSnapshot(Base):
    __tablename__ = "video_metric_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    watch_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0)
    browse_share: Mapped[float] = mapped_column(Float, default=0.0)
    suggested_share: Mapped[float] = mapped_column(Float, default=0.0)
    search_share: Mapped[float] = mapped_column(Float, default=0.0)
    external_share: Mapped[float] = mapped_column(Float, default=0.0)
    shorts_feed_share: Mapped[float] = mapped_column(Float, default=0.0)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    data_used_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShortPlan(Base):
    __tablename__ = "short_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    hook_type: Mapped[str] = mapped_column(String(64))
    source_start_seconds: Mapped[float] = mapped_column(Float)
    source_end_seconds: Mapped[float] = mapped_column(Float)
    target_duration_seconds: Mapped[float] = mapped_column(Float)
    on_screen_text: Mapped[str] = mapped_column(Text)
    cta: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planned")
    strategic_role: Mapped[str | None] = mapped_column(String(32), nullable=True)


class LearningPattern(Base):
    __tablename__ = "learning_patterns"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(64), index=True)
    pattern_type: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 5: Run tests**

Run: `cd apps/api && pytest -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api .env.example
git commit -m "feat: bootstrap API and persistence models"
```

---

### Task 2: Implement local project discovery and standard folder creation

**Files:**
- Create: `apps/api/app/services/project_scanner.py`
- Create: `apps/api/app/routes/projects.py`
- Create: `apps/api/tests/test_project_scanner.py`
- Modify: `apps/api/app/main.py`

**Interfaces:**
- Produces: `ensure_project_structure(project_path: Path) -> list[Path]`
- Produces: `scan_master_folder(master_folder: Path) -> list[ProjectScan]`
- Produces API `POST /projects/scan` and `GET /projects`.

- [ ] **Step 1: Write failing tests for folder creation and project discovery**

```python
from pathlib import Path
from app.services.project_scanner import ensure_project_structure, scan_master_folder


def test_ensure_project_structure_creates_expected_directories(tmp_path: Path):
    project = tmp_path / "Pilchard Mortality"
    project.mkdir()
    created = ensure_project_structure(project)
    expected = {"Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports"}
    assert {p.name for p in created} == expected
    assert all((project / name).is_dir() for name in expected)


def test_scan_master_folder_returns_only_direct_project_folders(tmp_path: Path):
    (tmp_path / "Pilchard Mortality").mkdir()
    (tmp_path / "Baia dos Tigres").mkdir()
    result = scan_master_folder(tmp_path)
    assert [p.name for p in result] == ["Baia dos Tigres", "Pilchard Mortality"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd apps/api && pytest tests/test_project_scanner.py -v`

Expected: FAIL because scanner functions do not exist.

- [ ] **Step 3: Implement deterministic scanner**

```python
# apps/api/app/services/project_scanner.py
from dataclasses import dataclass
from pathlib import Path

OUTPUT_DIRS = ("Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports")


@dataclass(frozen=True)
class ProjectScan:
    name: str
    path: Path


def ensure_project_structure(project_path: Path) -> list[Path]:
    created = []
    for name in OUTPUT_DIRS:
        path = project_path / name
        path.mkdir(exist_ok=True)
        created.append(path)
    return created


def scan_master_folder(master_folder: Path) -> list[ProjectScan]:
    if not master_folder.exists():
        return []
    folders = [p for p in master_folder.iterdir() if p.is_dir()]
    return [ProjectScan(name=p.name, path=p) for p in sorted(folders, key=lambda p: p.name.lower())]
```

- [ ] **Step 4: Add API persistence path**

`POST /projects/scan` must:
1. read `Settings.master_project_folder`,
2. discover child project folders,
3. call `ensure_project_structure`,
4. upsert `Project` rows by absolute path,
5. return project id/name/path.

`GET /projects` returns persisted projects sorted by name.

- [ ] **Step 5: Add API route test and run suite**

Run: `cd apps/api && pytest tests/test_project_scanner.py tests/test_health.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/services/project_scanner.py apps/api/app/routes/projects.py apps/api/app/main.py apps/api/tests/test_project_scanner.py
git commit -m "feat: discover YouTube project folders"
```

---

### Task 3: Add the Windows helper watcher and API synchronization

**Files:**
- Create: `helper/pyproject.toml`
- Create: `helper/skeleton_helper/__main__.py`
- Create: `helper/skeleton_helper/settings.py`
- Create: `helper/skeleton_helper/watcher.py`
- Create: `helper/skeleton_helper/sync_client.py`
- Create: `helper/tests/test_watcher.py`
- Create: `helper/tests/test_sync_client.py`

**Interfaces:**
- Consumes: `POST /projects/scan`
- Produces: `ProjectFolderWatcher.start()`, `ProjectFolderWatcher.stop()`
- Produces: `sync_projects(api_base_url: str) -> dict`

- [ ] **Step 1: Write failing watcher debounce test**

```python
from pathlib import Path
from skeleton_helper.watcher import should_trigger_scan


def test_should_trigger_scan_for_new_top_level_project(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    created = master / "New Project"
    assert should_trigger_scan(master, created) is True


def test_should_not_trigger_for_generated_subfolder(tmp_path: Path):
    master = tmp_path / "YouTube Projects"
    project = master / "Pilchard" / "Thumbnails"
    assert should_trigger_scan(master, project) is False
```

- [ ] **Step 2: Run and verify failure**

Run: `cd helper && pytest tests/test_watcher.py -v`

- [ ] **Step 3: Implement top-level folder event filter and watchdog observer**

`should_trigger_scan(master, changed)` returns true only when `changed.parent == master`.

The watcher must debounce scan requests for 2 seconds to avoid duplicate events during folder creation.

- [ ] **Step 4: Write failing sync-client test using an HTTP mock**

```python
def test_sync_projects_posts_scan(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8000/projects/scan",
        json={"projects": []},
    )
    from skeleton_helper.sync_client import sync_projects
    result = sync_projects("http://127.0.0.1:8000")
    assert result == {"projects": []}
```

- [ ] **Step 5: Implement sync client and CLI**

CLI behavior:

```text
python -m skeleton_helper
Master folder: I:\YouTube Projects
API: http://127.0.0.1:8000
Watching for new projects...
```

On startup, perform one immediate sync; afterward sync only for new top-level project folders.

- [ ] **Step 6: Run helper tests**

Run: `cd helper && pytest -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add helper
git commit -m "feat: add Windows project folder watcher"
```

---

### Task 4: Probe local media metadata with ffprobe

**Files:**
- Create: `apps/api/app/services/media_probe.py`
- Create: `apps/api/tests/test_media_probe.py`
- Modify: `apps/api/app/services/project_scanner.py`
- Modify: `apps/api/app/routes/projects.py`

**Interfaces:**
- Produces: `probe_media(path: Path) -> MediaProbeResult`
- Produces: `scan_media_files(project_path: Path) -> list[MediaProbeResult]`

- [ ] **Step 1: Write failing parser test using a captured ffprobe JSON payload**

```python
from pathlib import Path
from app.services.media_probe import parse_ffprobe_payload


def test_parse_ffprobe_payload_extracts_primary_video_stream():
    payload = {
        "format": {"duration": "28.950000"},
        "streams": [{
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1080,
            "height": 1920,
            "avg_frame_rate": "60000/1001",
        }],
    }
    result = parse_ffprobe_payload(Path("reel.mp4"), payload)
    assert result.duration_seconds == 28.95
    assert result.width == 1080
    assert result.height == 1920
    assert round(result.frame_rate, 2) == 59.94
    assert result.codec == "h264"
```

- [ ] **Step 2: Run and verify failure**

Run: `cd apps/api && pytest tests/test_media_probe.py -v`

- [ ] **Step 3: Implement ffprobe wrapper**

Use:

```bash
ffprobe -v error -show_streams -show_format -of json <file>
```

Supported input extensions for V1:

```python
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
```

Return a structured error for unreadable files; do not stop the whole project scan.

- [ ] **Step 4: Persist scan results as `MediaFile` rows**

The project detail API should expose each media file with technical metadata and a `probe_error` field when probing failed.

- [ ] **Step 5: Run tests**

Run: `cd apps/api && pytest tests/test_media_probe.py tests/test_project_scanner.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/services/media_probe.py apps/api/app/services/project_scanner.py apps/api/app/routes/projects.py apps/api/tests/test_media_probe.py
git commit -m "feat: scan local media metadata"
```

---

### Task 5: Implement read-only YouTube OAuth and analytics ingestion

**Files:**
- Create: `apps/api/app/services/youtube_client.py`
- Create: `apps/api/app/services/analytics_ingest.py`
- Create: `apps/api/app/routes/youtube.py`
- Create: `apps/api/tests/test_youtube_client.py`
- Create: `apps/api/tests/test_analytics_ingest.py`
- Create: `docs/youtube-oauth.md`
- Modify: `apps/api/app/main.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `YouTubeClient.get_authenticated_channel() -> ChannelIdentity`
- Produces: `YouTubeClient.fetch_video_metrics(video_id, start_date, end_date) -> RawVideoMetrics`
- Produces: `normalize_metrics(raw: RawVideoMetrics) -> MetricSnapshotInput`
- API routes: `GET /youtube/status`, `GET /youtube/oauth/start`, `GET /youtube/oauth/callback`, `POST /youtube/sync`.

- [ ] **Step 1: Write failing scope test**

```python
from app.services.youtube_client import YOUTUBE_SCOPES


def test_youtube_scopes_are_read_only():
    assert YOUTUBE_SCOPES == [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]
```

- [ ] **Step 2: Run and verify failure**

Run: `cd apps/api && pytest tests/test_youtube_client.py -v`

- [ ] **Step 3: Implement OAuth client with exact read-only scopes**

Never request upload, force-ssl write, or channel-management scopes in V1.

Persist OAuth token data locally in a file path configured by `YOUTUBE_TOKEN_PATH`; do not store the client secret in SQLite.

- [ ] **Step 4: Write failing analytics normalization test**

```python
from app.services.analytics_ingest import normalize_metrics


def test_normalize_metrics_calculates_subscriber_conversion():
    raw = {
        "video_id": "abc123",
        "views": 422,
        "impressions": 5000,
        "ctr": 0.071,
        "watch_minutes": 480.0,
        "avg_view_duration_seconds": 68.0,
        "subscribers_gained": 5,
        "traffic": {"BROWSE": 0.576, "SUGGESTED": 0.04, "SEARCH": 0.08, "EXTERNAL": 0.27, "SHORTS": 0.0},
    }
    result = normalize_metrics(raw)
    assert result.subscriber_conversion_rate == 5 / 422
    assert result.browse_share == 0.576
```

- [ ] **Step 5: Implement YouTube Data API + Analytics API fetches**

Fetch at minimum:
- channel identity and channel id,
- uploads playlist/video ids,
- title, publish time, duration, video type inference,
- views,
- watch time,
- average view duration,
- subscribers gained,
- impressions,
- CTR where available,
- traffic-source shares where available,
- returning viewers where available.

If a metric is unavailable for a date range or API dimension, store `null` rather than inventing zero.

- [ ] **Step 6: Enforce the single-channel constraint**

After OAuth, compare the authenticated channel id to `EXPECTED_YOUTUBE_CHANNEL_ID` when configured. If it does not match, reject sync with HTTP 409 and explain that V1 supports one channel only.

- [ ] **Step 7: Run tests**

Run: `cd apps/api && pytest tests/test_youtube_client.py tests/test_analytics_ingest.py -v`

Expected: PASS with mocked Google API responses; no live API required for unit tests.

- [ ] **Step 8: Document OAuth setup**

`docs/youtube-oauth.md` must contain exact Google Cloud steps:
1. create/select project,
2. enable YouTube Data API v3 and YouTube Analytics API,
3. configure OAuth consent screen,
4. create Desktop/Web OAuth credentials for local callback,
5. copy client id/secret to `.env`,
6. start dashboard and authorize the Skeleton Coast channel,
7. verify `/youtube/status` reports the expected channel.

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/services/youtube_client.py apps/api/app/services/analytics_ingest.py apps/api/app/routes/youtube.py apps/api/tests/test_youtube_client.py apps/api/tests/test_analytics_ingest.py docs/youtube-oauth.md .env.example
git commit -m "feat: connect read-only YouTube analytics"
```

---

### Task 6: Build the browser dashboard shell and project views

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/types.ts`
- Create: `apps/web/src/components/StatusBadge.tsx`
- Create: `apps/web/src/components/NextActions.tsx`
- Create: `apps/web/src/components/MetricCard.tsx`
- Create: `apps/web/src/components/ProjectCard.tsx`
- Create: `apps/web/src/pages/HomePage.tsx`
- Create: `apps/web/src/pages/ProjectsPage.tsx`
- Create: `apps/web/src/pages/ProjectDetailPage.tsx`
- Create: `apps/web/tests/HomePage.test.tsx`
- Create: `apps/web/tests/ProjectsPage.test.tsx`

**Interfaces:**
- Consumes: `/projects`, `/youtube/status`, `/recommendations/active`, `/analytics/summary`.
- Produces browser routes `/`, `/projects`, `/projects/:id`.

- [ ] **Step 1: Write failing Home page test**

```tsx
import { render, screen } from '@testing-library/react';
import { HomePage } from '../src/pages/HomePage';

it('prioritizes the next actions panel', async () => {
  render(<HomePage />);
  expect(await screen.findByRole('heading', { name: /what should i do next/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd apps/web && npm test -- --run`

- [ ] **Step 3: Implement minimal router and API client**

`api/client.ts` must expose typed functions:

```ts
export async function getProjects(): Promise<ProjectSummary[]>;
export async function getDashboardSummary(): Promise<DashboardSummary>;
export async function getActiveRecommendations(): Promise<Recommendation[]>;
```

- [ ] **Step 4: Implement Home and Projects pages**

Home must render:
- views,
- watch hours,
- subscribers gained,
- realtime views when available,
- top long-form,
- top Short,
- traffic-source split,
- Green/Amber/Red badges,
- prioritized Next Actions panel.

Projects must render one card per `I:\YouTube Projects\<Project Name>` discovered project.

- [ ] **Step 5: Run frontend tests**

Run: `cd apps/web && npm test -- --run`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web
git commit -m "feat: add growth dashboard project views"
```

---

### Task 7: Implement recommendation engine with guardrails

**Files:**
- Create: `apps/api/app/services/recommendation_engine.py`
- Create: `apps/api/app/services/baselines.py`
- Create: `apps/api/app/routes/recommendations.py`
- Create: `apps/api/tests/test_recommendation_engine.py`
- Create: `apps/api/tests/test_baselines.py`
- Modify: `apps/api/app/main.py`

**Interfaces:**
- Produces: `evaluate_video(context: VideoDecisionContext) -> RecommendationDecision`
- Produces: `build_channel_baseline(topic: str, format: str, length_bucket: str) -> Baseline`
- API: `GET /recommendations/active`, `POST /recommendations/rebuild`.

- [ ] **Step 1: Write failing guardrail tests**

```python
from app.services.recommendation_engine import evaluate_video, VideoDecisionContext


def test_small_sample_returns_amber_wait_not_red():
    ctx = VideoDecisionContext(
        age_hours=2,
        impressions=120,
        ctr=0.025,
        browse_share=0.50,
        browse_trend=0.10,
        realtime_trend=0.05,
        external_share=0.10,
        avg_percentage_viewed=0.35,
        subscriber_conversion=0.01,
        comparable_sample_size=8,
    )
    result = evaluate_video(ctx)
    assert result.state == "amber"
    assert "wait" in result.action.lower()


def test_rising_browse_with_healthy_realtime_returns_green():
    ctx = VideoDecisionContext(
        age_hours=18,
        impressions=5000,
        ctr=0.071,
        browse_share=0.58,
        browse_trend=0.20,
        realtime_trend=0.15,
        external_share=0.15,
        avg_percentage_viewed=0.34,
        subscriber_conversion=0.012,
        comparable_sample_size=12,
    )
    result = evaluate_video(ctx)
    assert result.state == "green"
    assert "leave" in result.action.lower() or "do not change" in result.action.lower()
```

- [ ] **Step 2: Run and verify failure**

Run: `cd apps/api && pytest tests/test_recommendation_engine.py -v`

- [ ] **Step 3: Implement explicit V1 thresholds as conservative defaults**

Use defaults that can later be tuned from channel history:
- `MIN_IMPRESSIONS_FOR_PACKAGING_CHANGE = 1000`
- `MIN_AGE_HOURS_FOR_PACKAGING_CHANGE = 12`
- Green when browse or suggested distribution is rising materially and realtime is non-declining.
- Amber when evidence is mixed, sample is too small, or an external spike dominates.
- Red only when sample and age thresholds are met, distribution has stalled/declined, and CTR or retention underperforms the comparable channel baseline.

Do not use a single metric to force Red.

- [ ] **Step 4: Implement Action / Reason / Confidence / Data Used output**

```python
@dataclass(frozen=True)
class RecommendationDecision:
    state: Literal["green", "amber", "red"]
    action: str
    reason: str
    confidence: Literal["low", "medium", "high"]
    data_used: dict[str, float | int | str | None]
```

- [ ] **Step 5: Write and implement baseline tests**

Baselines group historical videos by:
- topic,
- format (`long`, `short`, `live`),
- length bucket (`<1m`, `1-5m`, `5-15m`, `15m+`).

Require at least 5 comparable videos before using a channel-specific median. Otherwise mark baseline confidence low and use only non-comparative guardrails.

- [ ] **Step 6: Add endpoint and persistence**

`POST /recommendations/rebuild` evaluates latest snapshots and stores one active recommendation per video.

- [ ] **Step 7: Run tests**

Run: `cd apps/api && pytest tests/test_recommendation_engine.py tests/test_baselines.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/services/recommendation_engine.py apps/api/app/services/baselines.py apps/api/app/routes/recommendations.py apps/api/tests/test_recommendation_engine.py apps/api/tests/test_baselines.py
git commit -m "feat: add guarded YouTube recommendations"
```

---

### Task 8: Add analytics, recommendations, and learning screens

**Files:**
- Create: `apps/web/src/pages/AnalyticsPage.tsx`
- Create: `apps/web/src/pages/RecommendationsPage.tsx`
- Create: `apps/web/src/pages/LearningPage.tsx`
- Create: `apps/web/tests/RecommendationsPage.test.tsx`
- Modify: `apps/web/src/main.tsx`
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/types.ts`

**Interfaces:**
- Consumes recommendation decisions and analytics summaries from Tasks 5 and 7.

- [ ] **Step 1: Write failing recommendation rendering test**

```tsx
it('shows action reason confidence and data used', async () => {
  render(<RecommendationsPage />);
  expect(await screen.findByText(/action/i)).toBeInTheDocument();
  expect(screen.getByText(/reason/i)).toBeInTheDocument();
  expect(screen.getByText(/confidence/i)).toBeInTheDocument();
  expect(screen.getByText(/data used/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Implement pages**

Analytics page must show:
- impressions,
- CTR,
- views,
- AVD,
- average percentage viewed,
- watch time,
- subscribers,
- subscriber conversion,
- Browse/Suggested/Search/External/Shorts Feed shares,
- returning viewers,
- 1h/24h/7d comparisons.

Recommendations page sorts by priority and shows Green/Amber/Red state.

Learning page initially shows persisted patterns only; no speculative pattern may be shown without evidence counts.

- [ ] **Step 3: Run tests**

Run: `cd apps/web && npm test -- --run`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src apps/web/tests
git commit -m "feat: add analytics and recommendation screens"
```

---

### Task 9: Implement Shorts funnel planning and classification

**Files:**
- Create: `apps/api/app/services/shorts_funnel.py`
- Create: `apps/api/tests/test_shorts_funnel.py`
- Create: `apps/web/src/components/ShortsFunnelPanel.tsx`
- Modify: `apps/api/app/routes/projects.py`
- Modify: `apps/web/src/pages/ProjectDetailPage.tsx`

**Interfaces:**
- Produces: `classify_short(metrics: ShortMetrics, baseline: ShortBaseline) -> Literal["discovery", "conversion", "winner"]`
- API: `POST /projects/{project_id}/shorts`, `GET /projects/{project_id}/shorts`.

- [ ] **Step 1: Write failing classification tests**

```python
from app.services.shorts_funnel import classify_short, ShortMetrics, ShortBaseline


def test_high_reach_low_conversion_is_discovery():
    result = classify_short(
        ShortMetrics(view_rate=0.78, avg_percentage_viewed=0.92, shares_per_view=0.015, subscriber_conversion=0.001),
        ShortBaseline(view_rate=0.60, avg_percentage_viewed=0.80, shares_per_view=0.010, subscriber_conversion=0.004),
    )
    assert result == "discovery"


def test_high_reach_and_conversion_is_winner():
    result = classify_short(
        ShortMetrics(view_rate=0.78, avg_percentage_viewed=0.95, shares_per_view=0.020, subscriber_conversion=0.008),
        ShortBaseline(view_rate=0.60, avg_percentage_viewed=0.80, shares_per_view=0.010, subscriber_conversion=0.004),
    )
    assert result == "winner"
```

- [ ] **Step 2: Implement classification using relative channel baselines**

Do not classify from raw view count alone.

- [ ] **Step 3: Implement Short plan CRUD**

Each plan stores exact source start/end seconds, target length, hook type, on-screen text, CTA, status, and strategic role.

- [ ] **Step 4: Render funnel panel on project page**

Show long video at top and each planned Short beneath it with role/status/metrics.

- [ ] **Step 5: Run backend + frontend tests**

Run: `cd apps/api && pytest tests/test_shorts_funnel.py -v`

Run: `cd apps/web && npm test -- --run`

- [ ] **Step 6: Commit**

```bash
git add apps/api apps/web/src/components/ShortsFunnelPanel.tsx apps/web/src/pages/ProjectDetailPage.tsx
git commit -m "feat: add Shorts-to-long-form funnel tracking"
```

---

### Task 10: Generate project metadata, captions, cut lists, and reports

**Files:**
- Create: `apps/api/app/services/asset_generator.py`
- Create: `apps/api/app/routes/assets.py`
- Create: `apps/api/tests/test_asset_generator.py`
- Modify: `apps/api/app/main.py`

**Interfaces:**
- Produces: `write_metadata_pack(project_path: Path, pack: MetadataPack) -> list[Path]`
- Produces: `write_short_cut_list(project_path: Path, plans: list[ShortPlanInput]) -> Path`
- Produces: `write_performance_report(project_path: Path, report: PerformanceReport) -> Path`
- API: `POST /projects/{project_id}/assets/generate`.

- [ ] **Step 1: Write failing metadata-pack file test**

```python
from pathlib import Path
from app.services.asset_generator import MetadataPack, write_metadata_pack


def test_write_metadata_pack_creates_platform_files(tmp_path: Path):
    project = tmp_path / "Pilchard Mortality"
    (project / "Metadata").mkdir(parents=True)
    paths = write_metadata_pack(project, MetadataPack(
        youtube_title="Thousands of Pilchards Are Dying Along Namibia's Coast",
        youtube_description="Description",
        youtube_tags=["Namibia", "pilchards"],
        pinned_comment="Pinned comment",
        facebook_caption="Facebook caption",
        instagram_caption="Instagram caption",
        chapters="00:00 Opening",
    ))
    assert {p.name for p in paths} == {
        "youtube.txt", "tags.txt", "pinned-comment.txt", "facebook.txt", "instagram.txt", "chapters.txt"
    }
```

- [ ] **Step 2: Run and verify failure**

Run: `cd apps/api && pytest tests/test_asset_generator.py -v`

- [ ] **Step 3: Implement deterministic text asset generation**

File layout:

```text
Metadata/youtube.txt
Metadata/tags.txt
Metadata/pinned-comment.txt
Metadata/facebook.txt
Metadata/instagram.txt
Metadata/chapters.txt
Shorts/cut-list.csv
Analytics/performance-report.md
```

`cut-list.csv` columns:

```text
hook_type,source_start,source_end,target_duration,on_screen_text,cta,status,strategic_role
```

- [ ] **Step 4: Add caption export support**

Support SRT and WebVTT generation from provided timed caption segments. Do not auto-transcribe in V1 unless a transcription provider is explicitly added later.

- [ ] **Step 5: Add asset-generation API**

The endpoint takes explicit content payload and writes files only under the project's allowed output folders. Reject path traversal and any path outside the registered project root.

- [ ] **Step 6: Run tests**

Run: `cd apps/api && pytest tests/test_asset_generator.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/services/asset_generator.py apps/api/app/routes/assets.py apps/api/tests/test_asset_generator.py
git commit -m "feat: generate project metadata and cut-list assets"
```

---

### Task 11: Add thumbnail file workflow without generative branding drift

**Files:**
- Modify: `apps/api/app/services/asset_generator.py`
- Modify: `apps/api/app/routes/assets.py`
- Modify: `apps/api/tests/test_asset_generator.py`
- Create: `apps/web/src/components/PackagingPanel.tsx`
- Modify: `apps/web/src/pages/ProjectDetailPage.tsx`

**Interfaces:**
- Produces: `save_thumbnail_variant(project_path: Path, source_png: Path, aspect: Literal["16:9", "9:16"], label: str) -> Path`
- UI supports registering Thumbnail A/B/C and title A/B/C as paired packaging candidates.

- [ ] **Step 1: Write failing safe-thumbnail-copy test**

```python
def test_save_thumbnail_variant_stays_inside_thumbnail_folder(tmp_path):
    project = tmp_path / "Project"
    source = tmp_path / "candidate.png"
    source.write_bytes(b"png-bytes")
    path = save_thumbnail_variant(project, source, "16:9", "A")
    assert path.parent == project / "Thumbnails"
    assert path.name == "thumbnail-A-16x9.png"
```

- [ ] **Step 2: Implement deterministic thumbnail registration/export**

V1 must preserve the user's exact official branding assets when supplied. Do not regenerate or reinterpret logos. The service copies approved PNG assets and stores packaging metadata; it does not use a generative model to redraw the Skeleton Coast logo.

- [ ] **Step 3: Implement packaging pair UI**

Each candidate shows title + thumbnail together and fields for:
- curiosity,
- clarity,
- search relevance,
- audience fit,
- uniqueness,
- title/thumbnail complementarity,
- plain-language rationale.

The score is labeled "advisory" and never presented as objective truth.

- [ ] **Step 4: Run tests**

Run API and frontend suites.

- [ ] **Step 5: Commit**

```bash
git add apps/api apps/web/src/components/PackagingPanel.tsx apps/web/src/pages/ProjectDetailPage.tsx
git commit -m "feat: add safe thumbnail packaging workflow"
```

---

### Task 12: Implement learning-pattern extraction from channel history

**Files:**
- Modify: `apps/api/app/services/baselines.py`
- Create: `apps/api/app/services/learning_library.py`
- Create: `apps/api/tests/test_learning_library.py`
- Create: `apps/api/app/routes/learning.py`
- Modify: `apps/api/app/main.py`

**Interfaces:**
- Produces: `extract_learning_patterns(dataset: ChannelDataset) -> list[LearningPatternInput]`
- API: `POST /learning/rebuild`, `GET /learning/patterns`.

- [ ] **Step 1: Write failing evidence-threshold test**

```python
def test_pattern_requires_minimum_evidence():
    dataset = make_dataset(video_count=3)
    assert extract_learning_patterns(dataset) == []
```

- [ ] **Step 2: Implement minimum evidence rules**

A pattern requires at least 5 comparable items and must report:
- sample count,
- median/relative difference,
- topic/format scope,
- confidence.

Do not output claims such as "mystery thumbnails outperform by 24%" unless the actual stored data supports that value.

- [ ] **Step 3: Implement learning types**

V1 pattern types:
- `thumbnail_wording`
- `hook_type`
- `topic_performance`
- `short_duration`
- `subscriber_conversion`
- `browse_suggested_response`
- `geography`
- `follow_up_performance`

- [ ] **Step 4: Add rebuild/read routes and tests**

Run: `cd apps/api && pytest tests/test_learning_library.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/learning_library.py apps/api/app/services/baselines.py apps/api/app/routes/learning.py apps/api/tests/test_learning_library.py
git commit -m "feat: learn channel-specific performance patterns"
```

---

### Task 13: Add Windows setup, run scripts, and end-to-end smoke test

**Files:**
- Create: `docs/setup-windows.md`
- Create: `README.md`
- Create: `scripts/start-api.ps1`
- Create: `scripts/start-helper.ps1`
- Create: `scripts/start-web.ps1`
- Create: `scripts/smoke-test.ps1`
- Modify: `.env.example`

**Interfaces:**
- Produces a repeatable local start procedure for the user's Windows PC.

- [ ] **Step 1: Write smoke test script expectations**

The script must verify:
1. Python 3.12+ exists.
2. Node 20+ exists.
3. `ffprobe` exists.
4. `I:\YouTube Projects` exists or print a clear creation instruction.
5. API `/health` responds 200.
6. Web app loads.
7. Helper can perform one manual project sync.
8. YouTube status is either `connected` or a clear `authorization_required` state.

- [ ] **Step 2: Write `docs/setup-windows.md`**

Include exact PowerShell commands for:
- cloning/opening the project,
- creating Python virtual environments,
- installing API/helper dependencies,
- installing frontend dependencies,
- setting `.env`,
- verifying FFmpeg/ffprobe,
- starting API,
- starting web app,
- starting helper,
- authorizing YouTube.

- [ ] **Step 3: Add start scripts**

Example API script:

```powershell
Set-Location "$PSScriptRoot\..\apps\api"
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- [ ] **Step 4: Run all automated tests**

Run:

```bash
cd apps/api && pytest -v
cd ../../helper && pytest -v
cd ../apps/web && npm test -- --run
```

Expected: all PASS.

- [ ] **Step 5: Run smoke test on Windows**

Run: `powershell -ExecutionPolicy Bypass -File scripts\smoke-test.ps1`

Expected: every prerequisite and local service check reports PASS, with YouTube either connected or explicitly awaiting OAuth.

- [ ] **Step 6: Commit**

```bash
git add README.md docs scripts .env.example
git commit -m "docs: add Windows setup and smoke-test workflow"
```

---

## Final Verification Checklist

- [ ] API tests pass.
- [ ] Windows helper tests pass.
- [ ] Frontend tests pass.
- [ ] Project folder watcher detects a new top-level folder under `I:\YouTube Projects`.
- [ ] Standard folders are created without touching any DaVinci project files.
- [ ] Media probing handles valid and invalid files without crashing the project scan.
- [ ] YouTube OAuth requests only read-only scopes.
- [ ] Connected channel id matches the configured Skeleton Coast channel id.
- [ ] No API route can upload, publish, edit metadata, or change thumbnails on YouTube.
- [ ] Recommendations always expose Action, Reason, Confidence, and Data Used.
- [ ] Small samples cannot produce a Red packaging-change recommendation.
- [ ] Dashboard Home prominently shows "What should I do next?".
- [ ] Shorts are evaluated by retention/conversion signals, not raw views alone.
- [ ] Learning patterns require minimum evidence before being shown.
- [ ] Generated files remain inside the registered project folder.
- [ ] Official Skeleton Coast branding assets are copied/preserved, never generatively redrawn.

## Self-Review

- **Spec coverage:** All approved V1 areas are mapped to Tasks 1–13: helper, project scanning, media metadata, YouTube read-only analytics, dashboard, recommendations, retention/baselines, Shorts funnel, assets, packaging, learning library, and Windows setup.
- **Out-of-scope enforcement:** No task adds YouTube writes, automated publishing, automated engagement, DaVinci modification, multi-channel support, billing, or public accounts.
- **Placeholder scan:** No TBD/TODO placeholders remain. All implementation steps define concrete files, interfaces, tests, or behavior.
- **Type consistency:** Project, media, metric snapshot, recommendation, Short plan, and learning-pattern interfaces are defined before later tasks consume them.

