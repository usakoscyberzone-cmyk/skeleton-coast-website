from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import MediaFile, Project
from ..schemas import MediaFileRead, ProjectDetailRead, ProjectRead
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


def _persist_media_files(
    session: Session, project: Project, media_results: list[MediaProbeResult]
) -> None:
    existing_media = list(
        session.scalars(select(MediaFile).where(MediaFile.project_id == project.id))
    )
    by_path = {media_file.path: media_file for media_file in existing_media}
    seen_paths = set()
    for result in media_results:
        absolute_path = str(result.path.resolve())
        seen_paths.add(absolute_path)
        media_file = by_path.get(absolute_path)
        if media_file is None:
            media_file = MediaFile(project_id=project.id, path=absolute_path, kind=result.kind)
            session.add(media_file)
        media_file.kind = result.kind
        media_file.duration_seconds = result.duration_seconds
        media_file.width = result.width
        media_file.height = result.height
        media_file.frame_rate = result.frame_rate
        media_file.codec = result.codec
        media_file.probe_error = result.probe_error
    for media_file in existing_media:
        if media_file.path not in seen_paths:
            session.delete(media_file)
