from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


ShortStatus = Literal["planned", "ready", "published"]
ShortRole = Literal["discovery", "conversion", "winner"]


class ShortPlanCreate(BaseModel):
    hook_type: str = Field(min_length=1, max_length=64)
    source_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    source_end_seconds: float = Field(gt=0, allow_inf_nan=False)
    target_duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    on_screen_text: str = Field(min_length=1)
    cta: str = Field(min_length=1)
    status: ShortStatus = "planned"
    strategic_role: ShortRole

    @model_validator(mode="after")
    def target_fits_source_range(self):
        source_length = self.source_end_seconds - self.source_start_seconds
        if source_length <= 0:
            raise ValueError("source_end_seconds must be greater than source_start_seconds")
        if self.target_duration_seconds > source_length:
            raise ValueError("target_duration_seconds must fit within the source range")
        return self


class ShortPlanRead(ShortPlanCreate):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)
