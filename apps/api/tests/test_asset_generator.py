from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import math
import multiprocessing
import os
from pathlib import Path
import json
import subprocess
import threading

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


def _cross_process_metadata_writer(project_path: str, marker: str, start, results) -> None:
    pack = MetadataPack(
        youtube_title=f"{marker} title",
        youtube_description=marker * 500_000,
        youtube_tags=[f"{marker} tag"],
        pinned_comment=f"{marker} pinned",
        facebook_caption=f"{marker} facebook",
        instagram_caption=f"{marker} instagram",
        chapters=f"{marker} chapters",
    )
    if not start.wait(timeout=10):
        results.put(("error", marker, "start timeout"))
        return
    try:
        write_metadata_pack(Path(project_path), pack)
    except AssetConflictError:
        results.put(("conflict", marker))
    except BaseException as exc:
        results.put(("error", marker, f"{type(exc).__name__}: {exc}"))
    else:
        results.put(("success", marker))


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


def test_writer_cleanup_preserves_rollback_files_it_did_not_create(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "Project"
    metadata = project / "Metadata"
    metadata.mkdir(parents=True)
    foreign_rollback = metadata / ".youtube.txt.foreign.rollback"
    foreign_rollback.write_text("another writer", encoding="utf-8")
    monkeypatch.setattr(
        asset_generator.os,
        "replace",
        lambda *_: (_ for _ in ()).throw(OSError("disk failure")),
    )

    with pytest.raises(OSError, match="disk failure"):
        write_metadata_pack(project, _metadata_pack())

    assert foreign_rollback.read_text(encoding="utf-8") == "another writer"


def test_concurrent_default_writers_serialize_then_second_conflicts(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "Project"
    (project / "Metadata").mkdir(parents=True)
    real_stage_file = asset_generator._stage_file
    first_writer_ident: list[int] = []
    first_writer_in_stage = threading.Event()
    release_first = threading.Event()

    def pause_first_writer(target: Path, content: str) -> Path:
        if threading.get_ident() == first_writer_ident[0] and not first_writer_in_stage.is_set():
            first_writer_in_stage.set()
            assert release_first.wait(timeout=5)
        return real_stage_file(target, content)

    def first_write():
        first_writer_ident.append(threading.get_ident())
        return write_metadata_pack(project, _metadata_pack())

    monkeypatch.setattr(asset_generator, "_stage_file", pause_first_writer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_write)
        assert first_writer_in_stage.wait(timeout=5)
        second = pool.submit(write_metadata_pack, project, _metadata_pack())
        second_finished_while_first_paused = False
        try:
            second.result(timeout=0.5)
            second_finished_while_first_paused = True
        except FutureTimeoutError:
            pass
        finally:
            release_first.set()

        assert not second_finished_while_first_paused
        assert len(first.result(timeout=5)) == 6
        with pytest.raises(AssetConflictError):
            second.result(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows inter-process locking behavior")
def test_cross_process_default_writers_produce_one_coherent_pack_and_one_conflict(
    tmp_path: Path,
):
    project = tmp_path / "Project"
    metadata = project / "Metadata"
    metadata.mkdir(parents=True)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_cross_process_metadata_writer,
            args=(str(project), marker, start, results),
        )
        for marker in ("ROUND_A_", "ROUND_B_")
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    assert [process.exitcode for process in processes] == [0, 0]
    outcomes = [results.get(timeout=5), results.get(timeout=5)]
    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "success"]
    winner = next(outcome[1] for outcome in outcomes if outcome[0] == "success")
    assert (metadata / "youtube.txt").read_text(encoding="utf-8") == (
        f"{winner} title\n\n{winner * 500_000}\n"
    )
    assert (metadata / "tags.txt").read_text(encoding="utf-8") == f"{winner} tag\n"
    assert (metadata / "pinned-comment.txt").read_text(encoding="utf-8") == (
        f"{winner} pinned\n"
    )
    assert (metadata / "facebook.txt").read_text(encoding="utf-8") == f"{winner} facebook\n"
    assert (metadata / "instagram.txt").read_text(encoding="utf-8") == (
        f"{winner} instagram\n"
    )
    assert (metadata / "chapters.txt").read_text(encoding="utf-8") == f"{winner} chapters\n"
    assert {path.name for path in metadata.iterdir()} == {
        "youtube.txt",
        "tags.txt",
        "pinned-comment.txt",
        "facebook.txt",
        "instagram.txt",
        "chapters.txt",
    }


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


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_writer_holds_output_directory_against_junction_swap_during_transaction(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "Project"
    metadata = project / "Metadata"
    metadata.mkdir(parents=True)
    parked = project / "Metadata-parked"
    outside = tmp_path / "Outside"
    outside.mkdir()
    real_stage_file = asset_generator._stage_file
    swap_attempted = False
    swap_blocked = False

    def attempt_swap_then_stage(target: Path, content: str) -> Path:
        nonlocal swap_attempted, swap_blocked
        if target.parent == metadata and not swap_attempted:
            swap_attempted = True
            try:
                metadata.rename(parked)
            except OSError:
                swap_blocked = True
            else:
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(metadata), str(outside)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                assert result.returncode == 0, result.stderr
        return real_stage_file(target, content)

    monkeypatch.setattr(asset_generator, "_stage_file", attempt_swap_then_stage)
    try:
        write_metadata_pack(project, _metadata_pack())
        assert swap_attempted
        assert swap_blocked
        assert list(outside.iterdir()) == []
        assert (metadata / "youtube.txt").is_file()
    finally:
        if asset_generator._is_reparse_point(metadata):
            os.rmdir(metadata)
        if parked.exists():
            parked.rename(metadata)


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
    for folder in ("Metadata", "Shorts", "Analytics", "Captions", "Thumbnails"):
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


PNG_BYTES = b"\x89PNG\r\n\x1a\napproved-branding-bytes"


def _packaging_payload() -> dict:
    return {
        "candidates": [
            {
                "label": "A",
                "title": "What Washed Ashore on Namibia's Skeleton Coast?",
                "thumbnail": {
                    "aspect": "16:9",
                    "file": "Thumbnails/thumbnail-A-16x9.png",
                },
                "hook": "A coastline mystery grounded in what the camera found.",
                "seo_description": "An evidence-led look at a Skeleton Coast event.",
                "tags": ["Skeleton Coast", "Namibia", "fishing"],
                "pinned_comment": "What did you notice first?",
                "chapters": "00:00 What we found\n01:15 The evidence",
                "playlist": "Skeleton Coast field reports",
                "next_video_cta": "Watch our latest Skeleton Coast fishing expedition.",
                "scores": {
                    "curiosity": 84,
                    "clarity": 91,
                    "search_relevance": 75,
                    "audience_fit": 88,
                    "uniqueness": 82,
                    "title_thumbnail_complementarity": 90,
                },
                "rationale": "The title identifies the place while the image supplies the reveal.",
            }
        ]
    }


def test_save_thumbnail_variant_preserves_exact_png_bytes_and_fixed_name(tmp_path: Path):
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "candidate.png"
    source.write_bytes(PNG_BYTES)

    path = asset_generator.save_thumbnail_variant(project, source, "16:9", "A")

    assert path == project / "Thumbnails" / "thumbnail-A-16x9.png"
    assert path.read_bytes() == PNG_BYTES


@pytest.mark.parametrize(
    ("source_name", "source_bytes", "aspect", "label"),
    [
        ("candidate.jpg", PNG_BYTES, "16:9", "A"),
        ("candidate.png", b"not-a-png", "16:9", "A"),
        ("candidate.png", PNG_BYTES, "4:3", "A"),
        ("candidate.png", PNG_BYTES, "16:9", "../A"),
        ("candidate.png", PNG_BYTES, "16:9", "D"),
    ],
)
def test_save_thumbnail_variant_rejects_unapproved_input(
    tmp_path: Path, source_name: str, source_bytes: bytes, aspect: str, label: str
):
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / source_name
    source.write_bytes(source_bytes)

    with pytest.raises((ValueError, UnsafeAssetPathError)):
        asset_generator.save_thumbnail_variant(project, source, aspect, label)


def test_save_thumbnail_variant_rejects_overwrite_by_default(tmp_path: Path):
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "candidate.png"
    source.write_bytes(PNG_BYTES)
    asset_generator.save_thumbnail_variant(project, source, "9:16", "B")

    with pytest.raises(AssetConflictError):
        asset_generator.save_thumbnail_variant(project, source, "9:16", "B")


def test_packaging_candidates_are_written_as_deterministic_project_json(tmp_path: Path):
    project = tmp_path / "Project"
    project.mkdir()
    payload = _packaging_payload()

    path = asset_generator.write_packaging_candidates(project, payload)

    assert path == project / "Metadata" / "packaging-candidates.json"
    expected = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert path.read_text(encoding="utf-8") == expected
    assert asset_generator.read_packaging_candidates(project) == payload


def test_empty_packaging_read_still_rejects_unsafe_project_root(tmp_path: Path, monkeypatch):
    project = tmp_path / "Project"
    project.mkdir()
    monkeypatch.setattr(asset_generator, "_is_reparse_point", lambda path: Path(path) == project)

    with pytest.raises(UnsafeAssetPathError):
        asset_generator.read_packaging_candidates(project)


def test_packaging_api_registers_png_and_saves_complete_advisory_candidate(
    tmp_path: Path, monkeypatch
):
    client, session, project, _master = _asset_client(tmp_path, monkeypatch)
    source = tmp_path / "approved.png"
    source.write_bytes(PNG_BYTES)

    thumbnail = client.post(
        f"/projects/{project.id}/assets/thumbnails",
        json={"source_png": str(source), "aspect": "16:9", "label": "A"},
    )
    packaging = client.put(
        f"/projects/{project.id}/assets/packaging",
        json=_packaging_payload(),
    )
    loaded = client.get(f"/projects/{project.id}/assets/packaging")

    assert thumbnail.status_code == 201
    assert thumbnail.json() == {"file": "Thumbnails/thumbnail-A-16x9.png"}
    assert packaging.status_code == 201
    assert packaging.json() == {"file": "Metadata/packaging-candidates.json"}
    assert loaded.status_code == 200
    assert loaded.json() == _packaging_payload()
    assert "advisory" not in json.dumps(loaded.json()).lower()  # scores are data, UI supplies label
    session.close()


def test_packaging_api_explicitly_updates_json_for_additional_candidate(
    tmp_path: Path, monkeypatch
):
    client, session, project, _master = _asset_client(tmp_path, monkeypatch)
    for label in ("A", "B"):
        source = tmp_path / f"{label}.png"
        source.write_bytes(PNG_BYTES + label.encode())
        assert client.post(
            f"/projects/{project.id}/assets/thumbnails",
            json={"source_png": str(source), "aspect": "16:9", "label": label},
        ).status_code == 201
    first = _packaging_payload()
    assert client.put(f"/projects/{project.id}/assets/packaging", json=first).status_code == 201
    second = json.loads(json.dumps(first["candidates"][0]))
    second["label"] = "B"
    second["title"] = "A second packaging direction"
    second["thumbnail"]["file"] = "Thumbnails/thumbnail-B-16x9.png"

    response = client.put(
        f"/projects/{project.id}/assets/packaging",
        json={"candidates": [first["candidates"][0], second], "overwrite": True},
    )

    assert response.status_code == 201
    assert [candidate["label"] for candidate in client.get(
        f"/projects/{project.id}/assets/packaging"
    ).json()["candidates"]] == ["A", "B"]
    session.close()


def test_packaging_api_rejects_missing_thumbnail_wrong_png_and_overwrite(
    tmp_path: Path, monkeypatch
):
    client, session, project, _master = _asset_client(tmp_path, monkeypatch)
    missing = client.post(
        f"/projects/{project.id}/assets/thumbnails",
        json={"source_png": str(tmp_path / "missing.png"), "aspect": "16:9", "label": "A"},
    )
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not png")
    wrong = client.post(
        f"/projects/{project.id}/assets/thumbnails",
        json={"source_png": str(bad), "aspect": "16:9", "label": "A"},
    )
    approved = tmp_path / "approved.png"
    approved.write_bytes(PNG_BYTES)
    assert client.post(
        f"/projects/{project.id}/assets/thumbnails",
        json={"source_png": str(approved), "aspect": "16:9", "label": "A"},
    ).status_code == 201
    first = client.put(f"/projects/{project.id}/assets/packaging", json=_packaging_payload())
    conflict = client.put(f"/projects/{project.id}/assets/packaging", json=_packaging_payload())

    assert missing.status_code == 422
    assert wrong.status_code == 422
    assert first.status_code == 201
    assert conflict.status_code == 409
    session.close()
