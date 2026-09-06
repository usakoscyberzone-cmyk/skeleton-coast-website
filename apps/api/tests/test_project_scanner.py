from pathlib import Path

import app.db as database
import app.main as main_module
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.main import create_app
from app.services.project_scanner import ensure_project_structure, scan_master_folder


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
