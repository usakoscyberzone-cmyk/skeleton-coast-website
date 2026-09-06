from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str


class ProjectCreate(BaseModel):
    name: str
    path: str


class ProjectRead(ProjectCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
