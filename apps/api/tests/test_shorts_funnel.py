import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db import Base, get_session, upgrade_short_plans_schema
import app.main as main_module
from app.main import create_app
from app.models import Project
from app.schemas import ShortPlanCreate
from app.services.shorts_funnel import ShortBaseline, ShortMetrics, classify_short


@pytest.mark.parametrize(("metrics", "baseline", "expected"), [
    (ShortMetrics(.78, .92, .015, .001), ShortBaseline(.60, .80, .010, .004), "discovery"),
    (ShortMetrics(.78, .95, .020, .008), ShortBaseline(.60, .80, .010, .004), "winner"),
    (ShortMetrics(.40, .70, .005, .008), ShortBaseline(.60, .80, .010, .004), "conversion"),
    (ShortMetrics(.60, .80, .010, .004), ShortBaseline(.60, .80, .010, .004), "discovery"),
    (ShortMetrics(.20, .20, .001, .001), ShortBaseline(.60, .80, .010, .004), "discovery"),
])
def test_classification_uses_relative_channel_baselines(metrics, baseline, expected):
    assert classify_short(metrics, baseline) == expected


@pytest.mark.parametrize("metrics, baseline", [
    (ShortMetrics(.9, .9, .03, .02), ShortBaseline(0, .8, .01, .004)),
    (ShortMetrics(math.inf, .9, .03, .02), ShortBaseline(.6, .8, .01, .004)),
    (ShortMetrics(.9, 1.1, .03, .02), ShortBaseline(.6, .8, .01, .004)),
])
def test_invalid_or_insufficient_baselines_stay_non_comparative(metrics, baseline):
    assert classify_short(metrics, baseline) == "discovery"


def _client_with_project(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shorts.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    project = Project(name="Pilchards", path="I:\\YouTube Projects\\Pilchards")
    session.add(project)
    session.commit()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), project, session


def test_short_plans_preserve_exact_advisory_cut_values_and_list_by_id(tmp_path):
    client, project, session = _client_with_project(tmp_path)
    payload = {
        "hook_type": "shocking fact", "source_start_seconds": 12.125,
        "source_end_seconds": 41.875, "target_duration_seconds": 29.75,
        "on_screen_text": "Pilchards are dying", "cta": "Watch the full story",
        "status": "planned", "strategic_role": "discovery",
    }
    first = client.post(f"/projects/{project.id}/shorts", json=payload)
    second = client.post(f"/projects/{project.id}/shorts", json=payload)
    listed = client.get(f"/projects/{project.id}/shorts")

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert [(item["id"], item["source_start_seconds"], item["source_end_seconds"], item["target_duration_seconds"]) for item in listed.json()] == [
        (first.json()["id"], 12.125, 41.875, 29.75),
        (second.json()["id"], 12.125, 41.875, 29.75),
    ]
    session.close()


@pytest.mark.parametrize("payload", [
    {"hook_type": "hook", "source_start_seconds": -1, "source_end_seconds": 2, "target_duration_seconds": 1, "on_screen_text": "text", "cta": "cta", "status": "planned", "strategic_role": "discovery"},
    {"hook_type": "hook", "source_start_seconds": 2, "source_end_seconds": 2, "target_duration_seconds": 1, "on_screen_text": "text", "cta": "cta", "status": "planned", "strategic_role": "discovery"},
    {"hook_type": "hook", "source_start_seconds": 1, "source_end_seconds": 2, "target_duration_seconds": 1.1, "on_screen_text": "text", "cta": "cta", "status": "planned", "strategic_role": "discovery"},
    {"hook_type": "hook", "source_start_seconds": 1, "source_end_seconds": 2, "target_duration_seconds": 1, "on_screen_text": "text", "cta": "cta", "status": "published", "strategic_role": "unknown"},
])
def test_short_plan_rejects_invalid_cut_or_enum_values(tmp_path, payload):
    client, project, session = _client_with_project(tmp_path)
    assert client.post(f"/projects/{project.id}/shorts", json=payload).status_code == 422
    session.close()


def test_short_plan_routes_return_not_found_for_unknown_project(tmp_path):
    client, _project, session = _client_with_project(tmp_path)
    assert client.get("/projects/999/shorts").status_code == 404
    assert client.post("/projects/999/shorts", json={"hook_type": "hook", "source_start_seconds": 0, "source_end_seconds": 1, "target_duration_seconds": 1, "on_screen_text": "text", "cta": "cta", "status": "planned", "strategic_role": "discovery"}).status_code == 404
    session.close()


@pytest.mark.parametrize("field", ["source_start_seconds", "source_end_seconds", "target_duration_seconds"])
@pytest.mark.parametrize("timestamp", [math.inf, -math.inf, math.nan])
def test_short_plan_schema_rejects_non_finite_timestamps(field, timestamp):
    payload = dict(
        hook_type="hook", source_start_seconds=0, source_end_seconds=2,
        target_duration_seconds=1, on_screen_text="text", cta="cta",
        status="planned", strategic_role="discovery",
    )
    payload[field] = timestamp
    with pytest.raises(ValueError):
        ShortPlanCreate(**payload)


def test_legacy_null_roles_are_backfilled_idempotently_and_roundtrip_through_get(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-shorts.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, path TEXT, created_at DATETIME)"))
        connection.execute(text("CREATE TABLE short_plans (id INTEGER PRIMARY KEY, project_id INTEGER, hook_type TEXT, source_start_seconds FLOAT, source_end_seconds FLOAT, target_duration_seconds FLOAT, on_screen_text TEXT, cta TEXT, status TEXT, strategic_role TEXT)"))
        connection.execute(text("INSERT INTO projects VALUES (1, 'Legacy', 'I:/YouTube Projects/Legacy', CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO short_plans VALUES (7, 1, 'reveal', 1.25, 11.25, 10, 'Text', 'CTA', 'planned', NULL)"))

    monkeypatch.setattr(main_module, "engine", engine)
    app = create_app()
    with TestClient(app):
        pass
    upgrade_short_plans_schema(engine)
    assert inspect(engine).get_columns("short_plans")[-1]["nullable"] is False
    with Session(engine) as session:
        app.dependency_overrides[get_session] = lambda: session
        response = TestClient(app).get("/projects/1/shorts")
    assert response.status_code == 200
    assert response.json() == [{"id": 7, "project_id": 1, "hook_type": "reveal", "source_start_seconds": 1.25, "source_end_seconds": 11.25, "target_duration_seconds": 10, "on_screen_text": "Text", "cta": "CTA", "status": "planned", "strategic_role": "discovery"}]
