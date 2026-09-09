from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import engine, get_session
from app.main import create_app


def test_settings_use_dashboard_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MASTER_PROJECT_FOLDER", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "sqlite:///./skeleton_growth.db"
    assert settings.master_project_folder == r"I:\YouTube Projects"

    get_settings.cache_clear()


def test_get_session_yields_a_database_session():
    session_generator = get_session()

    session = next(session_generator)

    assert isinstance(session, Session)
    assert session.bind is engine

    session_generator.close()


def test_startup_creates_all_persistence_tables():
    with TestClient(create_app()):
        table_names = set(inspect(engine).get_table_names())

    assert {
        "projects",
        "media_files",
        "video_metric_snapshots",
        "recommendations",
        "short_plans",
        "learning_patterns",
    }.issubset(table_names)
