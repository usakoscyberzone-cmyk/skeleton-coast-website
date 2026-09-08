import math
import os
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, get_session
from app.main import create_app
from app.models import Project
from app.services import asset_generator
from app.services.asset_generator import (
    AssetConflictError,
    CaptionSegment,
    MetadataPack,
    PerformanceReport,
    ShortPlanInput,
    UnsafeAssetPathError,
    write_caption_track,
    write_metadata_pack,
    write_performance_report,
    write_short_cut_list,
)


def test_write_metadata_pack_creates_platform_files(tmp_path: Path):
    project = tmp_path / "Pilchard Mortality"
    (project / "Metadata").mkdir(parents=True)

    paths = write_metadata_pack(
        project,
        MetadataPack(
            youtube_title="Thousands of Pilchards Are Dying Along Namibia's Coast",
            youtube_description="Description",
            youtube_tags=["Namibia", "pilchards"],
            pinned_comment="Pinned comment",
            facebook_caption="Facebook caption",
            instagram_caption="Instagram caption",
            chapters="00:00 Opening",
        ),
    )

    assert {path.name for path in paths} == {
        "youtube.txt",
        "tags.txt",
        "pinned-comment.txt",
        "facebook.txt",
        "instagram.txt",
        "chapters.txt",
    }
    assert (project / "Metadata" / "youtube.txt").read_bytes() == (
        "Thousands of Pilchards Are Dying Along Namibia's Coast\n\nDescription\n"
    ).encode("utf-8")
    assert (project / "Metadata" / "tags.txt").read_bytes() == b"Namibia\npilchards\n"


def test_write_short_cut_list_uses_fixed_columns_and_csv_escaping(tmp_path: Path):
    project = tmp_path / "Project"
    (project / "Shorts").mkdir(parents=True)

    path = write_short_cut_list(
        project,
        [
            ShortPlanInput(
                hook_type="curiosity",
                source_start=12.5,
                source_end=25.0,
                target_duration=10.0,
                on_screen_text='Peixes, "milhares"',
                cta="Watch, then subscribe",
                status="ready",
                strategic_role="discovery",
            )
        ],
    )

    assert path == project / "Shorts" / "cut-list.csv"
    assert path.read_text(encoding="utf-8") == (
        "hook_type,source_start,source_end,target_duration,on_screen_text,cta,status,strategic_role\n"
        'curiosity,12.5,25,10,"Peixes, ""milhares""","Watch, then subscribe",ready,discovery\n'
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_start", -1.0),
        ("source_start", math.inf),
        ("source_end", math.nan),
        ("target_duration", 0.0),
    ],
)
def test_short_plan_rejects_invalid_times(field: str, value: float):
    values = dict(
        hook_type="hook",
        source_start=0.0,
        source_end=10.0,
        target_duration=5.0,
        on_screen_text="Text",
        cta="Subscribe",
        status="planned",
        strategic_role="conversion",
    )
    values[field] = value

    with pytest.raises(ValueError):
        ShortPlanInput(**values)


def test_short_plan_rejects_reversed_range_and_unknown_role_or_status():
    common = dict(
        hook_type="hook",
        source_start=10.0,
        source_end=10.0,
        target_duration=5.0,
        on_screen_text="Text",
        cta="Subscribe",
        status="planned",
        strategic_role="winner",
    )
    with pytest.raises(ValueError):
        ShortPlanInput(**common)
    with pytest.raises(ValueError):
        ShortPlanInput(**{**common, "source_end": 20.0, "status": "uploaded"})
    with pytest.raises(ValueError):
        ShortPlanInput(**{**common, "source_end": 20.0, "strategic_role": "other"})


def test_write_caption_track_formats_srt_and_webvtt_from_explicit_segments(tmp_path: Path):
    project = tmp_path / "Project"
    (project / "Captions").mkdir(parents=True)
    segments = [
        CaptionSegment(start=0.0, end=1.25, text="Namíbia & Angola"),
        CaptionSegment(start=61.002, end=62.5, text="Second line"),
    ]

    paths = write_caption_track(project, "en", segments)

    assert [path.name for path in paths] == ["en.srt", "en.vtt"]
    assert paths[0].read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,250\nNamíbia & Angola\n\n"
        "2\n00:01:01,002 --> 00:01:02,500\nSecond line\n"
    )
    assert paths[1].read_text(encoding="utf-8") == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.250\nNamíbia & Angola\n\n"
        "00:01:01.002 --> 00:01:02.500\nSecond line\n"
    )


@pytest.mark.parametrize(
    "segments",
    [
        [CaptionSegment(start=2, end=3, text="later"), CaptionSegment(start=1, end=1.5, text="earlier")],
        [CaptionSegment(start=0, end=2, text="first"), CaptionSegment(start=1.9, end=3, text="overlap")],
    ],
)
def test_caption_track_rejects_unordered_or_overlapping_segments(
    tmp_path: Path, segments: list[CaptionSegment]
):
    project = tmp_path / "Project"
    (project / "Captions").mkdir(parents=True)
    with pytest.raises(ValueError):
        write_caption_track(project, "en", segments)


def test_caption_segment_rejects_range_that_collapses_at_subtitle_precision():
    with pytest.raises(ValueError, match="subtitle precision"):
        CaptionSegment(start=0.0, end=0.0004, text="Too short")


@pytest.mark.parametrize("track_name", ["../escape", "C:/escape", "en/us", "", "."])
def test_caption_track_rejects_injected_names(tmp_path: Path, track_name: str):
    project = tmp_path / "Project"
    (project / "Captions").mkdir(parents=True)
    with pytest.raises(UnsafeAssetPathError):
        write_caption_track(
            project, track_name, [CaptionSegment(start=0, end=1, text="Caption")]
        )


def test_write_performance_report_is_utf8_with_deterministic_newline(tmp_path: Path):
    project = tmp_path / "Project"
    (project / "Analytics").mkdir(parents=True)
    path = write_performance_report(
        project, PerformanceReport(markdown="# Résumé\r\n\r\nViews: 1,000\r\n")
    )
    assert path.read_bytes() == "# Résumé\n\nViews: 1,000\n".encode("utf-8")


def test_writer_refuses_existing_assets_without_explicit_overwrite(tmp_path: Path):
    project = tmp_path / "Project"
    metadata = project / "Metadata"
    metadata.mkdir(parents=True)
    existing = metadata / "youtube.txt"
    existing.write_text("user copy", encoding="utf-8")
    pack = _metadata_pack()

    with pytest.raises(AssetConflictError):
        write_metadata_pack(project, pack)
    assert existing.read_text(encoding="utf-8") == "user copy"

    write_metadata_pack(project, pack, overwrite=True)
    assert existing.read_text(encoding="utf-8").startswith("Title\n\n")


def test_writer_rolls_back_all_targets_when_atomic_replace_fails(tmp_path: Path, monkeypatch):
    project = tmp_path / "Project"
    (project / "Metadata").mkdir(parents=True)
    real_replace = asset_generator.os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk failure")
        real_replace(source, target)

    monkeypatch.setattr(asset_generator.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="disk failure"):
        write_metadata_pack(project, _metadata_pack())
    assert list((project / "Metadata").iterdir()) == []


def test_writer_rejects_reparse_output_directory(tmp_path: Path, monkeypatch):
    project = tmp_path / "Project"
    metadata = project / "Metadata"
    metadata.mkdir(parents=True)
    monkeypatch.setattr(
        asset_generator,
        "_is_reparse_point",
        lambda path: Path(path) == metadata,
    )
    with pytest.raises(UnsafeAssetPathError):
        write_metadata_pack(project, _metadata_pack())


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_writer_rejects_real_windows_junction_output_before_writing(tmp_path: Path):
    project = tmp_path / "Project"
    project.mkdir()
    outside = tmp_path / "Outside"
    outside.mkdir()
    junction = project / "Metadata"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr.strip()}")

    try:
        assert asset_generator._is_reparse_point(junction)
        with pytest.raises(UnsafeAssetPathError):
            write_metadata_pack(project, _metadata_pack())
        assert list(outside.iterdir()) == []
    finally:
        os.rmdir(junction)


def test_asset_api_writes_complete_advisory_pack_and_is_deterministic(tmp_path: Path, monkeypatch):
    client, session, project, _master = _asset_client(tmp_path, monkeypatch)
    payload = _api_payload()

    first = client.post(f"/projects/{project.id}/assets/generate", json=payload)
    second = client.post(
        f"/projects/{project.id}/assets/generate", json={**payload, "overwrite": True}
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json() == {
        "files": [
            "Metadata/youtube.txt",
            "Metadata/tags.txt",
            "Metadata/pinned-comment.txt",
            "Metadata/facebook.txt",
            "Metadata/instagram.txt",
            "Metadata/chapters.txt",
            "Shorts/cut-list.csv",
            "Analytics/performance-report.md",
            "Captions/en.srt",
            "Captions/en.vtt",
        ]
    }
    assert "Namíbia" in (Path(project.path) / "Captions" / "en.vtt").read_text(encoding="utf-8")
    session.close()


def test_asset_api_conflict_unknown_project_and_invalid_content(tmp_path: Path, monkeypatch):
    client, session, project, _master = _asset_client(tmp_path, monkeypatch)
    payload = _api_payload()
    assert client.post("/projects/999/assets/generate", json=payload).status_code == 404
    assert client.post(f"/projects/{project.id}/assets/generate", json=payload).status_code == 201
    assert client.post(f"/projects/{project.id}/assets/generate", json=payload).status_code == 409
    invalid = _api_payload()
    invalid["shorts"][0]["source_end"] = invalid["shorts"][0]["source_start"]
    assert client.post(f"/projects/{project.id}/assets/generate", json=invalid).status_code == 422
    session.close()


def test_asset_api_rejects_registered_path_outside_master_and_name_case_trick(
    tmp_path: Path, monkeypatch
):
    client, session, project, master = _asset_client(tmp_path, monkeypatch)
    outside = tmp_path / "outside" / "Project"
    outside.mkdir(parents=True)
    project.path = str(outside)
    session.commit()
    assert client.post(f"/projects/{project.id}/assets/generate", json=_api_payload()).status_code == 400

    project.path = str(master / "project")
    session.commit()
    assert client.post(f"/projects/{project.id}/assets/generate", json=_api_payload()).status_code == 400
    session.close()


def test_asset_api_rejects_lexical_parent_traversal_in_registered_path(
    tmp_path: Path, monkeypatch
):
    client, session, project, master = _asset_client(tmp_path, monkeypatch)
    (master / "nested").mkdir()
    project.path = str(master / "nested" / ".." / "Project")
    session.commit()

    response = client.post(f"/projects/{project.id}/assets/generate", json=_api_payload())

    assert response.status_code == 400
    assert not (master / "Project" / "Metadata" / "youtube.txt").exists()
    session.close()


def test_asset_api_returns_controlled_io_failure_without_leaking_path(
    tmp_path: Path, monkeypatch
):
    client, session, project, _master = _asset_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        asset_generator.os,
        "replace",
        lambda *_: (_ for _ in ()).throw(OSError(f"failure at {project.path}")),
    )
    response = client.post(f"/projects/{project.id}/assets/generate", json=_api_payload())
    assert response.status_code == 500
    assert response.json() == {"detail": "Asset generation failed"}
    assert project.path not in response.text
    session.close()


def _metadata_pack() -> MetadataPack:
    return MetadataPack(
        youtube_title="Title",
        youtube_description="Description",
        youtube_tags=["one", "two"],
        pinned_comment="Pinned",
        facebook_caption="Facebook",
        instagram_caption="Instagram",
        chapters="00:00 Opening",
    )


def _api_payload() -> dict:
    return {
        "metadata": {
            "youtube_title": "Title",
            "youtube_description": "Description",
            "youtube_tags": ["Namibia", "pilchards"],
            "pinned_comment": "Pinned",
            "facebook_caption": "Facebook",
            "instagram_caption": "Instagram",
            "chapters": "00:00 Opening",
        },
        "shorts": [
            {
                "hook_type": "curiosity",
                "source_start": 0,
                "source_end": 10,
                "target_duration": 8,
                "on_screen_text": "What happened?",
                "cta": "Watch the full story",
                "status": "ready",
                "strategic_role": "discovery",
            }
        ],
        "performance_report": {"markdown": "# Performance\n\nReview after 24 hours."},
        "captions": [
            {
                "track_name": "en",
                "segments": [{"start": 0, "end": 1.25, "text": "Namíbia"}],
            }
        ],
    }


def _asset_client(tmp_path: Path, monkeypatch):
    master = tmp_path / "YouTube Projects"
    project_path = master / "Project"
    for folder in ("Metadata", "Shorts", "Analytics", "Captions"):
        (project_path / folder).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MASTER_PROJECT_FOLDER", str(master))
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'assets.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    project = Project(name="Project", path=str(project_path.resolve()))
    session.add(project)
    session.commit()
    session.refresh(project)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), session, project, master
