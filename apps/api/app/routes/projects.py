from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import Project
from ..schemas import ProjectRead
from ..services.project_scanner import ensure_project_structure, scan_master_folder


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
        persisted_projects.append(persisted_project)

    session.commit()
    for project in persisted_projects:
        session.refresh(project)
    return persisted_projects


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return list(session.scalars(select(Project).order_by(func.lower(Project.name))))
