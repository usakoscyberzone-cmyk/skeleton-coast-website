from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import sqlite3
import subprocess
from threading import Barrier, Lock, Timer
import time

import app.db as database
import app.main as main_module
import app.routes.projects as projects_route
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import get_settings, require_master_project_folder
from app.models import MediaFile, Project
from app.main import create_app
from app.services import project_scanner
from app.services.media_probe import MediaProbeResult
from app.services.project_scanner import (
    ensure_project_structure,
    scan_master_folder,
    scan_media_files,
)


def _hold_sqlite_immediate_lock(database_path: str, ready, release) -> None:
    connection = sqlite3.connect(database_path, timeout=0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ready.set()
        release.wait(5)
        connection.commit()
    finally:
        connection.close()


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

    app = create_app()
    app.dependency_overrides[require_master_project_folder] = lambda: master_folder
    with TestClient(app) as client:
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

    app = create_app()
    app.dependency_overrides[require_master_project_folder] = lambda: master_folder
    with TestClient(app) as client:
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


def test_scan_media_files_rejects_a_junction_project_root_named_like_output(
    tmp_path: Path, monkeypatch
):
    """Breaks if a swapped project root can redirect a source scan outside master."""
    project = tmp_path / "Thumbnails"
    project.mkdir()
    source = project / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        project_scanner.os.path,
        "isjunction",
        lambda path: Path(path) == project,
        raising=False,
    )

    result = scan_media_files(project)

    assert result == []


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
            projects_route.scan_projects(session, master_folder=tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: invoke_scan(), range(2)))

    assert max_active_scans == 1


def test_upgrade_media_files_schema_deduplicates_legacy_rows_and_adds_unique_index(
    tmp_path: Path,
):
    """Breaks if a database created before Task 4 cannot use media ON CONFLICT."""
    from app.db import upgrade_media_files_schema

    database_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{database_path}")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE media_files ("
            "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, path TEXT NOT NULL, "
            "kind TEXT NOT NULL, duration_seconds FLOAT, width INTEGER, height INTEGER, "
            "frame_rate FLOAT, codec TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO media_files (id, project_id, path, kind) "
            "VALUES (1, 7, 'C:/media/reel.mp4', 'video'), "
            "(2, 7, 'C:/media/reel.mp4', 'video')"
        )

    upgrade_media_files_schema(legacy_engine)

    with legacy_engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id FROM media_files WHERE project_id = 7 AND path = 'C:/media/reel.mp4'"
        ).all()
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(media_files)")
        }
    unique_indexes = inspect(legacy_engine).get_indexes("media_files")

    assert rows == [(1,)]
    assert "probe_error" in columns
    assert any(
        index["unique"] and index["column_names"] == ["project_id", "path"]
        for index in unique_indexes
    )


def test_upgrade_media_files_schema_is_a_no_op_for_non_sqlite_bind():
    """Breaks if the SQLite legacy upgrade connects to another database dialect."""
    from app.db import upgrade_media_files_schema

    class RejectingNonSqliteBind:
        class dialect:
            name = "postgresql"

        def connect(self):
            pytest.fail("non-SQLite legacy upgrade attempted to connect")

    upgrade_media_files_schema(RejectingNonSqliteBind())


def test_upgrade_media_files_schema_locks_each_connection_before_introspection(
    tmp_path: Path, monkeypatch
):
    """Breaks if concurrent startup inspects either connection before its write lock."""
    from app.db import upgrade_media_files_schema

    database_path = tmp_path / "ordered-concurrent-legacy.db"
    upgrade_engine = create_engine(
        f"sqlite:///{database_path}", connect_args={"check_same_thread": False}
    )
    with upgrade_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE media_files ("
            "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, path TEXT NOT NULL, "
            "kind TEXT NOT NULL)"
        )

    original_inspect = database.inspect
    pre_lock_inspection_barrier = Barrier(2)
    event_lock = Lock()
    events_by_connection: dict[int, list[str]] = {}

    def record_begin_immediate(
        connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        if statement.strip().upper() != "BEGIN IMMEDIATE":
            return
        with event_lock:
            events_by_connection.setdefault(id(connection), []).append(
                "begin_immediate"
            )

    def instrument_inspection(bind):
        if bind is not upgrade_engine and getattr(bind, "engine", None) is upgrade_engine:
            with event_lock:
                connection_events = events_by_connection.setdefault(id(bind), [])
                inspected_before_lock = "begin_immediate" not in connection_events
                connection_events.append("inspect")
            if inspected_before_lock:
                pre_lock_inspection_barrier.wait(timeout=5)
        return original_inspect(bind)

    event.listen(upgrade_engine, "before_cursor_execute", record_begin_immediate)
    monkeypatch.setattr(database, "inspect", instrument_inspection)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(upgrade_media_files_schema, upgrade_engine) for _ in range(2)]
        for future in futures:
            future.result(timeout=5)

    assert len(events_by_connection) == 2
    assert all(
        connection_events[:2] == ["begin_immediate", "inspect"]
        for connection_events in events_by_connection.values()
    )

    with upgrade_engine.connect() as connection:
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(media_files)")
        }
    assert "probe_error" in columns


def test_upgrade_media_files_schema_does_not_duplicate_fresh_unique_indexes(tmp_path: Path):
    """Breaks if startup adds another project/path unique index to a fresh schema."""
    from app.db import upgrade_media_files_schema

    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    database.Base.metadata.create_all(bind=fresh_engine)

    upgrade_media_files_schema(fresh_engine)

    with fresh_engine.connect() as connection:
        unique_project_path_indexes = []
        for _, name, unique, *_ in connection.exec_driver_sql("PRAGMA index_list(media_files)"):
            columns = [
                row[2]
                for row in connection.exec_driver_sql(f"PRAGMA index_info('{name}')")
            ]
            if unique and columns == ["project_id", "path"]:
                unique_project_path_indexes.append(name)

    assert len(unique_project_path_indexes) == 1


def test_begin_immediate_transaction_waits_for_a_separate_process_lock(tmp_path: Path):
    """Breaks if two API workers can write scans at the same time."""
    from app.db import begin_immediate_transaction

    database_path = tmp_path / "process-lock.db"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_sqlite_immediate_lock,
        args=(str(database_path), ready, release),
    )
    holder.start()
    try:
        assert ready.wait(5)
        release_timer = Timer(0.1, release.set)
        release_timer.start()
        lock_engine = create_engine(
            f"sqlite:///{database_path}", connect_args={"timeout": 0}
        )
        with sessionmaker(bind=lock_engine)() as session:
            begin_immediate_transaction(session, max_attempts=20, retry_delay_seconds=0.02)
            session.rollback()
        release_timer.join()
    finally:
        release.set()
        holder.join(5)
        if holder.is_alive():
            holder.terminate()
            holder.join()

    assert holder.exitcode == 0


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

    app = create_app()
    app.dependency_overrides[require_master_project_folder] = lambda: master_folder
    with TestClient(app) as client:
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
