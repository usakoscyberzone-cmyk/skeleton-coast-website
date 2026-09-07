from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import begin_immediate_transaction, get_session
from ..models import MediaFile, Project, ShortPlan
from ..schemas import MediaFileRead, ProjectDetailRead, ProjectRead, ShortPlanCreate, ShortPlanRead
from ..services.project_scanner import (
    ensure_project_structure,
    scan_master_folder,
    scan_media_files,
)
from ..services.media_probe import MediaProbeResult


router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/scan", response_model=list[ProjectRead])
def scan_projects(session: Session = Depends(get_session)) -> list[Project]:
    master_folder = Path(get_settings().master_project_folder)
    begin_immediate_transaction(session)
    projects = scan_master_folder(master_folder)
    persisted_projects = []

    for project in projects:
        ensure_project_structure(project.path)
        absolute_path = str(project.path.resolve())
        persisted_project = session.scalar(
            select(Project).where(Project.path == absolute_path)
        )
        if persisted_project is None:
            persisted_project = Project(name=project.name, path=absolute_path)
            session.add(persisted_project)
        else:
            persisted_project.name = project.name
        session.flush()
        _persist_media_files(session, persisted_project, scan_media_files(project.path))
        persisted_projects.append(persisted_project)

    session.commit()
    for project in persisted_projects:
        session.refresh(project)
    return persisted_projects


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return list(
        session.scalars(
            select(Project).order_by(func.lower(Project.name), Project.name, Project.id)
        )
    )


@router.get("/{project_id}", response_model=ProjectDetailRead)
def get_project(project_id: int, session: Session = Depends(get_session)) -> ProjectDetailRead:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    media_files = list(
        session.scalars(
            select(MediaFile)
            .where(MediaFile.project_id == project.id)
            .order_by(func.lower(MediaFile.path), MediaFile.path, MediaFile.id)
        )
    )
    return ProjectDetailRead(
        id=project.id,
        name=project.name,
        path=project.path,
        media_files=[MediaFileRead.model_validate(media_file) for media_file in media_files],
    )


def _project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/shorts", response_model=ShortPlanRead, status_code=201)
def create_short_plan(project_id: int, payload: ShortPlanCreate, session: Session = Depends(get_session)) -> ShortPlan:
    _project_or_404(session, project_id)
    plan = ShortPlan(project_id=project_id, **payload.model_dump())
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.get("/{project_id}/shorts", response_model=list[ShortPlanRead])
def list_short_plans(project_id: int, session: Session = Depends(get_session)) -> list[ShortPlan]:
    _project_or_404(session, project_id)
    return list(session.scalars(select(ShortPlan).where(ShortPlan.project_id == project_id).order_by(ShortPlan.id)))


def _persist_media_files(
    session: Session, project: Project, media_results: list[MediaProbeResult]
) -> None:
    seen_paths = set()
    for result in media_results:
        absolute_path = str(result.path.resolve())
        seen_paths.add(absolute_path)
        values = {
            "project_id": project.id,
            "path": absolute_path,
            "kind": result.kind,
            "duration_seconds": result.duration_seconds,
            "width": result.width,
            "height": result.height,
            "frame_rate": result.frame_rate,
            "codec": result.codec,
            "probe_error": result.probe_error,
        }
        insert_statement = sqlite_insert(MediaFile).values(**values)
        session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=[MediaFile.project_id, MediaFile.path],
                set_={
                    key: getattr(insert_statement.excluded, key)
                    for key in values
                    if key not in {"project_id", "path"}
                },
            )
        )
    stale_media = delete(MediaFile).where(MediaFile.project_id == project.id)
    if seen_paths:
        stale_media = stale_media.where(MediaFile.path.not_in(seen_paths))
    session.execute(stale_media)
