from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from threading import Lock
import time

import app.db as database
import app.main as main_module
import app.routes.projects as projects_route
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import MediaFile, Project
from app.main import create_app
from app.services import project_scanner
from app.services.media_probe import MediaProbeResult
from app.services.project_scanner import (
    ensure_project_structure,
    scan_master_folder,
    scan_media_files,
)


def test_ensure_project_structure_creates_expected_directories(tmp_path: Path):
    project = tmp_path / "Pilchard Mortality"
    project.mkdir()

    created = ensure_project_structure(project)

    expected = {"Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports"}
    assert {path.name for path in created} == expected
    assert all((project / name).is_dir() for name in expected)
    assert ensure_project_structure(project) == created


def test_scan_master_folder_returns_sorted_direct_project_folders(tmp_path: Path):
    (tmp_path / "Pilchard Mortality").mkdir()
    (tmp_path / "Baia dos Tigres").mkdir()
    (tmp_path / "Pilchard Mortality" / "Nested Project").mkdir()
    (tmp_path / "notes.txt").write_text("not a project folder", encoding="utf-8")

    result = scan_master_folder(tmp_path)

    assert [project.name for project in result] == ["Baia dos Tigres", "Pilchard Mortality"]
    assert [project.path for project in result] == [
        tmp_path / "Baia dos Tigres",
        tmp_path / "Pilchard Mortality",
    ]


def test_scan_master_folder_returns_no_projects_when_root_is_missing(tmp_path: Path):
    assert scan_master_folder(tmp_path / "missing") == []


def test_scan_master_folder_breaks_unicode_casefold_ties_by_name_then_path(tmp_path: Path):
    theta_symbol = tmp_path / "\u03d1 Project"
    theta_capital = tmp_path / "\u03f4 Project"
    theta_capital.mkdir()
    theta_symbol.mkdir()

    result = scan_master_folder(tmp_path)

    assert [
        (project.name.casefold(), project.name, str(project.path)) for project in result
    ] == [
        ("\u03b8 project", "\u03d1 Project", str(theta_symbol.resolve())),
        ("\u03b8 project", "\u03f4 Project", str(theta_capital.resolve())),
    ]


def test_scan_endpoint_persists_projects_and_get_returns_name_order(tmp_path: Path, monkeypatch):
    master_folder = tmp_path / "YouTube Projects"
    (master_folder / "Pilchard Mortality").mkdir(parents=True)
    (master_folder / "Baia dos Tigres").mkdir()
    (master_folder / "readme.txt").write_text("ignored", encoding="utf-8")
    monkeypatch.setenv("MASTER_PROJECT_FOLDER", str(master_folder))
    get_settings.cache_clear()
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'projects.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=test_engine))
    monkeypatch.setattr(main_module, "engine", test_engine)

    database.Base.metadata.create_all(bind=test_engine)

    with TestClient(create_app()) as client:
        first_scan = client.post("/projects/scan")
        second_scan = client.post("/projects/scan")
        listed_projects = client.get("/projects")

    assert first_scan.status_code == 200
    assert listed_projects.status_code == 200
    assert first_scan.json() == second_scan.json()
    assert [project["name"] for project in listed_projects.json()] == [
        "Baia dos Tigres",
        "Pilchard Mortality",
    ]
    assert len(first_scan.json()) == 2
    assert all(Path(project["path"]).is_absolute() for project in first_scan.json())
    assert all(
        (master_folder / project["name"] / output_dir).is_dir()
        for project in first_scan.json()
        for output_dir in ("Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports")
    )

    get_settings.cache_clear()


def test_scan_endpoint_ignores_linked_project_outside_master(tmp_path: Path, monkeypatch):
    master_folder = tmp_path / "YouTube Projects"
    master_folder.mkdir()
    outside_folder = tmp_path / "outside-master"
    outside_folder.mkdir()
    linked_project = master_folder / "Linked Project"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(linked_project), str(outside_folder)],
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.setenv("MASTER_PROJECT_FOLDER", str(master_folder))
    get_settings.cache_clear()
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'linked-project.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=test_engine))
    monkeypatch.setattr(main_module, "engine", test_engine)
    database.Base.metadata.create_all(bind=test_engine)

    with TestClient(create_app()) as client:
        response = client.post("/projects/scan")

    assert response.status_code == 200
    assert response.json() == []
    assert not any(
        (outside_folder / name).exists()
        for name in ("Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports")
    )

    get_settings.cache_clear()


def test_list_projects_breaks_casefold_ties_by_name_then_id(tmp_path: Path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'ordering.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=test_engine))
    monkeypatch.setattr(main_module, "engine", test_engine)
    database.Base.metadata.create_all(bind=test_engine)
    with database.SessionLocal() as session:
        session.add_all(
            [
                Project(name="alpha", path=str(tmp_path / "first")),
                Project(name="Alpha", path=str(tmp_path / "second")),
            ]
        )
        session.commit()

    with TestClient(create_app()) as client:
        response = client.get("/projects")

    assert response.status_code == 200
    assert [project["name"] for project in response.json()] == ["Alpha", "alpha"]


def test_scan_media_files_returns_supported_source_files_in_deterministic_order(
    tmp_path: Path, monkeypatch
):
    """Breaks if generated folders or unsupported files are accidentally probed."""
    project = tmp_path / "Pilchard Mortality"
    project.mkdir()
    (project / "Zulu.MP4").write_bytes(b"video")
    (project / "alpha.MP3").write_bytes(b"audio")
    (project / "notes.txt").write_text("ignore me", encoding="utf-8")
    (project / "Thumbnails").mkdir()
    (project / "Thumbnails" / "generated.jpg").write_bytes(b"asset")
    (project / "Captions").mkdir()
    (project / "Captions" / "generated.vtt").write_text("WEBVTT", encoding="utf-8")

    probed_paths: list[Path] = []

    def fake_probe(path: Path) -> MediaProbeResult:
        probed_paths.append(path)
        return MediaProbeResult(path=path, kind="video")

    monkeypatch.setattr(project_scanner, "probe_media", fake_probe)

    result = scan_media_files(project)

    assert [item.path.name for item in result] == ["alpha.MP3", "Zulu.MP4"]
    assert probed_paths == [project / "alpha.MP3", project / "Zulu.MP4"]


def test_scan_media_files_continues_when_one_probe_returns_an_error(
    tmp_path: Path, monkeypatch
):
    """Breaks if one corrupt source file prevents later media from being listed."""
    project = tmp_path / "Project"
    project.mkdir()
    (project / "broken.mp4").write_bytes(b"bad")
    (project / "usable.mp4").write_bytes(b"good")

    def fake_probe(path: Path) -> MediaProbeResult:
        if path.name == "broken.mp4":
            return MediaProbeResult(path=path, kind="video", probe_error="ffprobe_failed")
        return MediaProbeResult(path=path, kind="video", codec="h264")

    monkeypatch.setattr(project_scanner, "probe_media", fake_probe)

    result = scan_media_files(project)

    assert [(item.path.name, item.probe_error) for item in result] == [
        ("broken.mp4", "ffprobe_failed"),
        ("usable.mp4", None),
    ]


def test_scan_media_files_rejects_junction_targets_and_case_variant_output_roots(
    tmp_path: Path, monkeypatch
):
    """Breaks if a reparse point leaves the project or generated files re-enter scans."""
    project = tmp_path / "Project"
    project.mkdir()
    local_file = project / "source.mp4"
    local_file.write_bytes(b"source")
    generated_dir = project / "thumbnails"
    generated_dir.mkdir()
    (generated_dir / "generated.jpg").write_bytes(b"generated")
    external_target = tmp_path / "outside-project"
    external_target.mkdir()
    external_file = external_target / "outside.mp4"
    external_file.write_bytes(b"outside")
    external_junction = project / "External"

    def fake_walk(_: Path, *, topdown: bool):
        assert topdown is True
        return iter(
            [
                (
                    str(project),
                    ["thumbnails", "External"],
                    ["source.mp4", "escaped.mp4"],
                ),
                (str(generated_dir), [], ["generated.jpg"]),
                (str(external_junction), [], ["outside.mp4"]),
            ]
        )

    monkeypatch.setattr(project_scanner.os, "walk", fake_walk)
    monkeypatch.setattr(
        project_scanner.os.path,
        "isjunction",
        lambda path: Path(path) == external_junction,
        raising=False,
    )
    monkeypatch.setattr(
        project_scanner.Path,
        "resolve",
        lambda path: external_target / "outside.mp4"
        if path in {external_junction / "outside.mp4", project / "escaped.mp4"}
        else Path(path),
    )

    result = scan_media_files(project)

    assert [item.path for item in result] == [local_file]


def test_scan_media_files_does_not_treat_the_project_root_as_generated_output(
    tmp_path: Path, monkeypatch
):
    """Breaks if an otherwise valid project name happens to match an output folder."""
    project = tmp_path / "Thumbnails"
    project.mkdir()
    source = project / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        project_scanner,
        "probe_media",
        lambda path: MediaProbeResult(path=path, kind="video"),
    )

    result = scan_media_files(project)

    assert [item.path for item in result] == [source]


def test_media_files_have_a_database_unique_constraint_for_project_path(tmp_path: Path):
    """Breaks if a concurrent scan can create duplicate rows for one source path."""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'constraint.db'}", connect_args={"check_same_thread": False}
    )
    database.Base.metadata.create_all(bind=test_engine)

    constraints = inspect(test_engine).get_unique_constraints("media_files")

    assert any(
        constraint["column_names"] == ["project_id", "path"] for constraint in constraints
    )
    with database.SessionLocal(bind=test_engine) as session:
        project = Project(name="Project", path=str(tmp_path / "Project"))
        session.add(project)
        session.flush()
        session.add_all(
            [
                MediaFile(project_id=project.id, path="C:/media/reel.mp4", kind="video"),
                MediaFile(project_id=project.id, path="C:/media/reel.mp4", kind="video"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_scan_projects_serializes_in_process_scans(tmp_path: Path, monkeypatch):
    """Breaks if overlapping API scans can interleave stale-row reconciliation."""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'serialized.db'}", connect_args={"check_same_thread": False}
    )
    database.Base.metadata.create_all(bind=test_engine)
    active_scans = 0
    max_active_scans = 0
    active_lock = Lock()

    def slow_discovery(_: Path):
        nonlocal active_scans, max_active_scans
        with active_lock:
            active_scans += 1
            max_active_scans = max(max_active_scans, active_scans)
        time.sleep(0.05)
        with active_lock:
            active_scans -= 1
        return []

    monkeypatch.setattr(projects_route, "scan_master_folder", slow_discovery)
    test_sessions = sessionmaker(bind=test_engine)

    def invoke_scan() -> None:
        with test_sessions() as session:
            projects_route.scan_projects(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: invoke_scan(), range(2)))

    assert max_active_scans == 1


def test_project_scan_upserts_media_removes_stale_rows_and_exposes_probe_errors(
    tmp_path: Path, monkeypatch
):
    """Breaks if scanning duplicates media, keeps deleted files, or hides probe failures."""
    master_folder = tmp_path / "YouTube Projects"
    project_folder = master_folder / "Pilchard Mortality"
    project_folder.mkdir(parents=True)
    source_file = project_folder / "reel.mp4"
    source_file.write_bytes(b"first")
    broken_file = project_folder / "broken.mp4"
    broken_file.write_bytes(b"bad")
    monkeypatch.setenv("MASTER_PROJECT_FOLDER", str(master_folder))
    get_settings.cache_clear()
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'media.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=test_engine))
    monkeypatch.setattr(main_module, "engine", test_engine)
    database.Base.metadata.create_all(bind=test_engine)

    def fake_probe(path: Path) -> MediaProbeResult:
        if path.name == "broken.mp4":
            return MediaProbeResult(path=path, kind="video", probe_error="ffprobe_failed")
        return MediaProbeResult(
            path=path,
            kind="video",
            duration_seconds=28.95,
            width=1080,
            height=1920,
            frame_rate=59.94,
            codec="h264",
        )

    monkeypatch.setattr(project_scanner, "probe_media", fake_probe)

    with TestClient(create_app()) as client:
        first_scan = client.post("/projects/scan")
        project_id = first_scan.json()[0]["id"]
        first_detail = client.get(f"/projects/{project_id}")
        second_scan = client.post("/projects/scan")
        broken_file.unlink()
        source_file.unlink()
        replacement = project_folder / "replacement.MP4"
        replacement.write_bytes(b"replacement")
        third_scan = client.post("/projects/scan")
        final_detail = client.get(f"/projects/{project_id}")

    assert first_scan.status_code == 200
    assert second_scan.status_code == 200
    assert third_scan.status_code == 200
    assert first_detail.status_code == 200
    assert first_detail.json()["media_files"] == [
        {
            "id": 1,
            "path": str(broken_file.resolve()),
            "kind": "video",
            "duration_seconds": None,
            "width": None,
            "height": None,
            "frame_rate": None,
            "codec": None,
            "probe_error": "ffprobe_failed",
        },
        {
            "id": 2,
            "path": str(source_file.resolve()),
            "kind": "video",
            "duration_seconds": 28.95,
            "width": 1080,
            "height": 1920,
            "frame_rate": 59.94,
            "codec": "h264",
            "probe_error": None,
        },
    ]
    assert final_detail.status_code == 200
    assert [media["path"] for media in final_detail.json()["media_files"]] == [
        str(replacement.resolve())
    ]
    with database.SessionLocal() as session:
        rows = list(session.query(MediaFile).order_by(MediaFile.path))
    assert [(row.path, row.probe_error) for row in rows] == [
        (str(replacement.resolve()), None)
    ]

    get_settings.cache_clear()
