from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str


class ProjectCreate(BaseModel):
    name: str
    path: str


class ProjectRead(ProjectCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class MediaFileRead(BaseModel):
    id: int
    path: str
    kind: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    frame_rate: float | None
    codec: str | None
    probe_error: str | None

    model_config = ConfigDict(from_attributes=True)


class ProjectDetailRead(ProjectRead):
    media_files: list[MediaFileRead]
