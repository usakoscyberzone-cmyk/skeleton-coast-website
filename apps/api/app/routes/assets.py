"""Generate local advisory assets without mutating any publishing platform."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..models import Project
from ..services.asset_generator import (
    AssetConflictError,
    CaptionSegment,
    CaptionTrack,
    MetadataPack,
    PerformanceReport,
    ShortPlanInput,
    UnsafeAssetPathError,
    _is_reparse_point,
    generate_asset_pack,
    read_packaging_snapshot,
    save_thumbnail_variant,
    update_packaging_candidates,
)


router = APIRouter(prefix="/projects", tags=["assets"])


class MetadataPayload(BaseModel):
    youtube_title: str = Field(min_length=1)
    youtube_description: str = Field(min_length=1)
    youtube_tags: list[str] = Field(min_length=1)
    pinned_comment: str = Field(min_length=1)
    facebook_caption: str = Field(min_length=1)
    instagram_caption: str = Field(min_length=1)
    chapters: str = Field(min_length=1)

    @field_validator(
        "youtube_title", "youtube_description", "pinned_comment",
        "facebook_caption", "instagram_caption", "chapters",
    )
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("youtube_tags")
    @classmethod
    def tags_are_not_blank(cls, value: list[str]) -> list[str]:
        if any(not tag.strip() for tag in value):
            raise ValueError("tags must not be blank")
        return value


class ShortPayload(BaseModel):
    hook_type: str = Field(min_length=1)
    source_start: float = Field(ge=0, allow_inf_nan=False)
    source_end: float = Field(gt=0, allow_inf_nan=False)
    target_duration: float = Field(gt=0, allow_inf_nan=False)
    on_screen_text: str = Field(min_length=1)
    cta: str = Field(min_length=1)
    status: Literal["planned", "ready", "published"]
    strategic_role: Literal["discovery", "conversion", "winner"]

    @field_validator("hook_type", "on_screen_text", "cta")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @model_validator(mode="after")
    def valid_range(self):
        if self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if self.target_duration > self.source_end - self.source_start:
            raise ValueError("target_duration must fit the source range")
        return self


class PerformanceReportPayload(BaseModel):
    markdown: str = Field(min_length=1)

    @field_validator("markdown")
    @classmethod
    def report_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("markdown must not be blank")
        return value


class CaptionSegmentPayload(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def caption_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("caption text must not be blank")
        return value

    @model_validator(mode="after")
    def end_follows_start(self):
        if self.end <= self.start:
            raise ValueError("caption end must be greater than start")
        return self


class CaptionTrackPayload(BaseModel):
    track_name: str = Field(min_length=1, max_length=64)
    segments: list[CaptionSegmentPayload] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_without_overlap(self):
        previous_end = -math.inf
        for segment in self.segments:
            if segment.start < previous_end:
                raise ValueError("caption segments must be ordered and non-overlapping")
            previous_end = segment.end
        return self


class AssetGenerationPayload(BaseModel):
    metadata: MetadataPayload
    shorts: list[ShortPayload] = Field(min_length=1)
    performance_report: PerformanceReportPayload
    captions: list[CaptionTrackPayload] = Field(min_length=1)
    overwrite: bool = False


class ThumbnailPayload(BaseModel):
    source_png: str = Field(min_length=1)
    aspect: Literal["16:9", "9:16"]
    label: Literal["A", "B", "C"]


class ThumbnailReferencePayload(BaseModel):
    aspect: Literal["16:9", "9:16"]
    file: str = Field(min_length=1)


class PackagingScoresPayload(BaseModel):
    curiosity: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    search_relevance: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)
    uniqueness: int = Field(ge=0, le=100)
    title_thumbnail_complementarity: int = Field(ge=0, le=100)


class PackagingCandidatePayload(BaseModel):
    label: Literal["A", "B", "C"]
    title: str = Field(min_length=1)
    thumbnail: ThumbnailReferencePayload
    hook: str = Field(min_length=1)
    seo_description: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    pinned_comment: str = Field(min_length=1)
    chapters: str = Field(min_length=1)
    playlist: str = Field(min_length=1)
    next_video_cta: str = Field(min_length=1)
    scores: PackagingScoresPayload
    rationale: str = Field(min_length=1)

    @field_validator(
        "title", "hook", "seo_description", "pinned_comment", "chapters", "playlist",
        "next_video_cta", "rationale",
    )
    @classmethod
    def candidate_text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("candidate text must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def candidate_tags_are_not_blank(cls, value: list[str]) -> list[str]:
        if any(not tag.strip() for tag in value):
            raise ValueError("candidate tags must not be blank")
        return value

    @model_validator(mode="after")
    def thumbnail_matches_candidate(self):
        suffix = "16x9" if self.thumbnail.aspect == "16:9" else "9x16"
        if self.thumbnail.file != f"Thumbnails/thumbnail-{self.label}-{suffix}.png":
            raise ValueError("thumbnail file must match its label and aspect")
        return self


class PackagingPayload(BaseModel):
    candidates: list[PackagingCandidatePayload] = Field(max_length=3)

    @model_validator(mode="after")
    def unique_labels(self):
        labels = [candidate.label for candidate in self.candidates]
        if len(labels) != len(set(labels)):
            raise ValueError("candidate labels must be unique")
        return self


class PackagingSavePayload(PackagingPayload):
    expected_revision: str = Field(default="missing", pattern=r"^(missing|[0-9a-f]{64})$")
    thumbnail_registration: ThumbnailPayload | None = None


class PackagingReadPayload(PackagingPayload):
    revision: str


def _registered_project_path(project: Project) -> Path:
    master = Path(get_settings().master_project_folder)
    registered = Path(project.path)
    if (
        not master.is_absolute()
        or not registered.is_absolute()
        or not master.is_dir()
        or not registered.is_dir()
        or _is_reparse_point(master)
        or _is_reparse_point(registered)
        or str(registered.parent) != str(master)
        or registered.name != project.name
    ):
        raise UnsafeAssetPathError("Unsafe registered project")
    try:
        resolved_master = master.resolve(strict=True)
        resolved_project = registered.resolve(strict=True)
    except OSError as exc:
        raise UnsafeAssetPathError("Unsafe registered project") from exc
    if (
        os.path.normcase(str(registered.parent.resolve(strict=True)))
        != os.path.normcase(str(resolved_master))
        or resolved_project.parent != resolved_master
        or resolved_project.name != project.name
    ):
        raise UnsafeAssetPathError("Registered project is not a direct master child")
    return resolved_project


@router.post("/{project_id}/assets/generate", status_code=201)
def generate_assets(
    project_id: int,
    payload: AssetGenerationPayload,
    session: Session = Depends(get_session),
) -> dict[str, list[str]]:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        project_path = _registered_project_path(project)
        paths = generate_asset_pack(
            project_path,
            MetadataPack(**payload.metadata.model_dump()),
            [ShortPlanInput(**short.model_dump()) for short in payload.shorts],
            PerformanceReport(**payload.performance_report.model_dump()),
            [
                CaptionTrack(
                    track_name=track.track_name,
                    segments=[CaptionSegment(**segment.model_dump()) for segment in track.segments],
                )
                for track in payload.captions
            ],
            overwrite=payload.overwrite,
        )
    except AssetConflictError as exc:
        raise HTTPException(status_code=409, detail="Generated assets already exist") from exc
    except (UnsafeAssetPathError, ValueError) as exc:
        status = 400 if isinstance(exc, UnsafeAssetPathError) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Asset generation failed") from exc
    return {"files": [path.relative_to(project_path).as_posix() for path in paths]}


def _project_or_404(project_id: int, session: Session) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/assets/thumbnails", status_code=201)
def register_thumbnail(
    project_id: int,
    payload: ThumbnailPayload,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    project = _project_or_404(project_id, session)
    try:
        project_path = _registered_project_path(project)
        path = save_thumbnail_variant(
            project_path, Path(payload.source_png), payload.aspect, payload.label
        )
    except AssetConflictError as exc:
        raise HTTPException(status_code=409, detail="Thumbnail variant already exists") from exc
    except UnsafeAssetPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Thumbnail registration failed") from exc
    return {"file": path.relative_to(project_path).as_posix()}


@router.put("/{project_id}/assets/packaging", status_code=201)
def save_packaging(
    project_id: int,
    payload: PackagingSavePayload,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    project = _project_or_404(project_id, session)
    try:
        project_path = _registered_project_path(project)
        document = PackagingPayload(candidates=payload.candidates).model_dump()
        registration = payload.thumbnail_registration
        path, revision = update_packaging_candidates(
            project_path,
            document,
            payload.expected_revision,
            source_png=Path(registration.source_png) if registration else None,
            aspect=registration.aspect if registration else None,
            label=registration.label if registration else None,
        )
    except AssetConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UnsafeAssetPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Packaging save failed") from exc
    return {"file": path.relative_to(project_path).as_posix(), "revision": revision}


@router.get("/{project_id}/assets/packaging", response_model=PackagingReadPayload)
def get_packaging(
    project_id: int,
    session: Session = Depends(get_session),
) -> dict:
    project = _project_or_404(project_id, session)
    try:
        project_path = _registered_project_path(project)
        document, revision = read_packaging_snapshot(project_path)
        return PackagingReadPayload(**document, revision=revision).model_dump()
    except UnsafeAssetPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail="Packaging candidates could not be read") from exc
