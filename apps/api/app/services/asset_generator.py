from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable


class AssetGenerationError(Exception):
    """Base class for controlled asset generation failures."""


class AssetConflictError(AssetGenerationError):
    """Raised when generation would overwrite a user-owned asset."""


class UnsafeAssetPathError(AssetGenerationError):
    """Raised when an output location is not a safe fixed project child."""


def _required_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")


@dataclass(frozen=True)
class MetadataPack:
    youtube_title: str
    youtube_description: str
    youtube_tags: list[str]
    pinned_comment: str
    facebook_caption: str
    instagram_caption: str
    chapters: str

    def __post_init__(self) -> None:
        for field in (
            "youtube_title", "youtube_description", "pinned_comment",
            "facebook_caption", "instagram_caption", "chapters",
        ):
            _required_text(getattr(self, field), field)
        if not self.youtube_tags or any(not tag.strip() for tag in self.youtube_tags):
            raise ValueError("youtube_tags must contain non-empty tags")


@dataclass(frozen=True)
class ShortPlanInput:
    hook_type: str
    source_start: float
    source_end: float
    target_duration: float
    on_screen_text: str
    cta: str
    status: str
    strategic_role: str

    def __post_init__(self) -> None:
        for field in ("hook_type", "on_screen_text", "cta"):
            _required_text(getattr(self, field), field)
        for field in ("source_start", "source_end", "target_duration"):
            value = getattr(self, field)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field} must be finite and nonnegative")
        if self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if self.target_duration <= 0 or self.target_duration > self.source_end - self.source_start:
            raise ValueError("target_duration must be positive and fit the source range")
        if self.status not in {"planned", "ready", "published"}:
            raise ValueError("invalid short status")
        if self.strategic_role not in {"discovery", "conversion", "winner"}:
            raise ValueError("invalid strategic role")


@dataclass(frozen=True)
class PerformanceReport:
    markdown: str

    def __post_init__(self) -> None:
        _required_text(self.markdown, "markdown")


@dataclass(frozen=True)
class CaptionSegment:
    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.start) or self.start < 0:
            raise ValueError("caption start must be finite and nonnegative")
        if not math.isfinite(self.end) or self.end <= self.start:
            raise ValueError("caption end must be finite and greater than start")
        if round(self.end * 1000) <= round(self.start * 1000):
            raise ValueError("caption end must follow start at subtitle precision")
        _required_text(self.text, "caption text")


@dataclass(frozen=True)
class CaptionTrack:
    track_name: str
    segments: list[CaptionSegment]


CUT_COLUMNS = (
    "hook_type", "source_start", "source_end", "target_duration",
    "on_screen_text", "cta", "status", "strategic_role",
)
_TRACK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _with_final_newline(value: str) -> str:
    return _normalize_newlines(value).rstrip("\n") + "\n"


def _render_metadata(project_path: Path, pack: MetadataPack) -> dict[Path, str]:
    metadata = project_path / "Metadata"
    return {
        metadata / "youtube.txt": _with_final_newline(
            f"{pack.youtube_title}\n\n{pack.youtube_description}"
        ),
        metadata / "tags.txt": _with_final_newline("\n".join(pack.youtube_tags)),
        metadata / "pinned-comment.txt": _with_final_newline(pack.pinned_comment),
        metadata / "facebook.txt": _with_final_newline(pack.facebook_caption),
        metadata / "instagram.txt": _with_final_newline(pack.instagram_caption),
        metadata / "chapters.txt": _with_final_newline(pack.chapters),
    }


def _format_number(value: float) -> str:
    return format(value, ".15g")


def _render_cut_list(project_path: Path, plans: list[ShortPlanInput]) -> dict[Path, str]:
    if not plans:
        raise ValueError("at least one short plan is required")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CUT_COLUMNS)
    for plan in plans:
        writer.writerow((
            plan.hook_type, _format_number(plan.source_start),
            _format_number(plan.source_end), _format_number(plan.target_duration),
            plan.on_screen_text, plan.cta, plan.status, plan.strategic_role,
        ))
    return {project_path / "Shorts" / "cut-list.csv": output.getvalue()}


def _validate_caption_track(track_name: str, segments: list[CaptionSegment]) -> None:
    if not _TRACK_NAME.fullmatch(track_name) or track_name in {".", ".."}:
        raise UnsafeAssetPathError("Invalid caption track name")
    if not segments:
        raise ValueError("at least one caption segment is required")
    previous_end = -1.0
    for segment in segments:
        if segment.start < previous_end:
            raise ValueError("caption segments must be ordered and non-overlapping")
        previous_end = segment.end


def _timestamp(seconds: float, separator: str) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def _render_caption_track(
    project_path: Path, track_name: str, segments: list[CaptionSegment]
) -> dict[Path, str]:
    _validate_caption_track(track_name, segments)
    srt_blocks = []
    vtt_blocks = []
    for sequence, segment in enumerate(segments, start=1):
        text = _normalize_newlines(segment.text).strip("\n")
        srt_blocks.append(
            f"{sequence}\n{_timestamp(segment.start, ',')} --> {_timestamp(segment.end, ',')}\n{text}"
        )
        vtt_blocks.append(
            f"{_timestamp(segment.start, '.')} --> {_timestamp(segment.end, '.')}\n{text}"
        )
    captions = project_path / "Captions"
    return {
        captions / f"{track_name}.srt": "\n\n".join(srt_blocks) + "\n",
        captions / f"{track_name}.vtt": "WEBVTT\n\n" + "\n\n".join(vtt_blocks) + "\n",
    }


def _render_report(project_path: Path, report: PerformanceReport) -> dict[Path, str]:
    return {
        project_path / "Analytics" / "performance-report.md": _with_final_newline(report.markdown)
    }


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path):
        return True
    try:
        return bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return False


def _validate_targets(project_path: Path, targets: Iterable[Path]) -> None:
    if not project_path.is_absolute() or not project_path.is_dir() or _is_reparse_point(project_path):
        raise UnsafeAssetPathError("Unsafe project directory")
    try:
        resolved_project = project_path.resolve(strict=True)
    except OSError as exc:
        raise UnsafeAssetPathError("Unsafe project directory") from exc
    for target in targets:
        output_dir = target.parent
        if output_dir.name not in {"Metadata", "Shorts", "Analytics", "Captions"}:
            raise UnsafeAssetPathError("Invalid asset output directory")
        if output_dir.parent != project_path:
            raise UnsafeAssetPathError("Asset target is outside the project")
        if not output_dir.exists():
            output_dir.mkdir(exist_ok=False)
        if not output_dir.is_dir() or _is_reparse_point(output_dir):
            raise UnsafeAssetPathError("Unsafe asset output directory")
        if output_dir.resolve(strict=True).parent != resolved_project:
            raise UnsafeAssetPathError("Asset output escapes the project")
        if target.exists() and _is_reparse_point(target):
            raise UnsafeAssetPathError("Unsafe asset target")


def _stage_file(target: Path, content: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _write_files(files: dict[Path, str], *, overwrite: bool = False) -> list[Path]:
    _validate_targets(next(iter(files)).parents[1], files)
    if any(path.exists() for path in files) and not overwrite:
        raise AssetConflictError("One or more generated assets already exist")
    originals = {path: path.read_bytes() if path.exists() else None for path in files}
    staged: list[tuple[Path, Path]] = []
    replaced: list[Path] = []
    try:
        staged = [(_stage_file(target, content), target) for target, content in files.items()]
        for temporary, target in staged:
            os.replace(temporary, target)
            replaced.append(target)
        return list(files)
    except BaseException:
        for target in reversed(replaced):
            original = originals[target]
            try:
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    descriptor, rollback_name = tempfile.mkstemp(
                        dir=target.parent, prefix=f".{target.name}.", suffix=".rollback"
                    )
                    rollback = Path(rollback_name)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(original)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(rollback, target)
            except OSError:
                pass
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        for target in files:
            for rollback in target.parent.glob(f".{target.name}.*.rollback"):
                rollback.unlink(missing_ok=True)


def write_metadata_pack(
    project_path: Path, pack: MetadataPack, *, overwrite: bool = False
) -> list[Path]:
    return _write_files(_render_metadata(project_path, pack), overwrite=overwrite)


def write_short_cut_list(
    project_path: Path, plans: list[ShortPlanInput], *, overwrite: bool = False
) -> Path:
    return _write_files(_render_cut_list(project_path, plans), overwrite=overwrite)[0]


def write_performance_report(
    project_path: Path, report: PerformanceReport, *, overwrite: bool = False
) -> Path:
    return _write_files(_render_report(project_path, report), overwrite=overwrite)[0]


def write_caption_track(
    project_path: Path, track_name: str, segments: list[CaptionSegment], *, overwrite: bool = False
) -> list[Path]:
    return _write_files(_render_caption_track(project_path, track_name, segments), overwrite=overwrite)


def generate_asset_pack(
    project_path: Path,
    metadata: MetadataPack,
    shorts: list[ShortPlanInput],
    report: PerformanceReport,
    captions: list[CaptionTrack],
    *,
    overwrite: bool = False,
) -> list[Path]:
    files = _render_metadata(project_path, metadata)
    files.update(_render_cut_list(project_path, shorts))
    files.update(_render_report(project_path, report))
    for track in captions:
        rendered = _render_caption_track(project_path, track.track_name, track.segments)
        if files.keys() & rendered.keys():
            raise ValueError("caption track names must be unique")
        files.update(rendered)
    return _write_files(files, overwrite=overwrite)
