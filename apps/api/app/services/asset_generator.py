from __future__ import annotations

import csv
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from typing import Iterable, Iterator, Literal, Mapping, Any


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
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_THUMBNAIL_LABELS = frozenset({"A", "B", "C"})
_THUMBNAIL_ASPECTS = {"16:9": "16x9", "9:16": "9x16"}
_PROJECT_LOCKS: dict[str, threading.RLock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


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


def _validate_project_root(project_path: Path) -> Path:
    if not project_path.is_absolute() or not project_path.is_dir() or _is_reparse_point(project_path):
        raise UnsafeAssetPathError("Unsafe project directory")
    try:
        return project_path.resolve(strict=True)
    except OSError as exc:
        raise UnsafeAssetPathError("Unsafe project directory") from exc


def _validate_targets(project_path: Path, targets: Iterable[Path]) -> None:
    resolved_project = _validate_project_root(project_path)
    for target in targets:
        output_dir = target.parent
        if output_dir.name not in {"Metadata", "Shorts", "Analytics", "Captions", "Thumbnails"}:
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


@contextmanager
def _hold_directory_stable(path: Path) -> Iterator[None]:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        read_write_delete = 0x80000000 | 0x40000000 | 0x00010000
        share_read_write = 0x00000001 | 0x00000002
        create_new = 1
        hidden_delete_on_close = 0x00000002 | 0x04000000
        handle = ctypes.c_void_p(-1).value
        for _ in range(10):
            guard = path / f".asset-generation-{secrets.token_hex(16)}.guard"
            handle = create_file(
                str(guard),
                read_write_delete,
                share_read_write,
                None,
                create_new,
                hidden_delete_on_close,
                None,
            )
            if handle != ctypes.c_void_p(-1).value:
                break
            if ctypes.get_last_error() not in {80, 183}:
                raise ctypes.WinError(ctypes.get_last_error())
        if handle == ctypes.c_void_p(-1).value:
            raise OSError("Could not reserve a directory guard")
        try:
            yield
        finally:
            close_handle(handle)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        yield
    finally:
        os.close(descriptor)


@contextmanager
def _hold_asset_directories(
    project_path: Path, targets: Iterable[Path]
) -> Iterator[None]:
    targets = tuple(targets)
    _validate_targets(project_path, targets)
    output_directories = sorted({target.parent for target in targets}, key=str)
    with ExitStack() as stack:
        stack.enter_context(_hold_directory_stable(project_path))
        for output_dir in output_directories:
            stack.enter_context(_hold_directory_stable(output_dir))
        _validate_targets(project_path, targets)
        yield


def _stage_file(target: Path, content: str | bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        mode = "wb" if isinstance(content, bytes) else "w"
        kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8", "newline": "\n"}
        with os.fdopen(descriptor, mode, **kwargs) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _project_lock(project_path: Path) -> threading.RLock:
    key = os.path.normcase(str(project_path.resolve(strict=False)))
    with _PROJECT_LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _interprocess_project_lock(project_path: Path) -> Iterator[None]:
    if os.name != "nt":
        yield
        return

    import ctypes
    from ctypes import wintypes

    canonical_path = os.path.normcase(str(project_path.resolve(strict=False)))
    identity = hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()
    mutex_name = f"Local\\SkeletonCoastAssets-{identity}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single_object.restype = wintypes.DWORD
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (wintypes.HANDLE,)
    release_mutex.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, mutex_name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        wait_result = wait_for_single_object(handle, 0xFFFFFFFF)
        if wait_result not in {0x00000000, 0x00000080}:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = True
        yield
    finally:
        if acquired:
            release_mutex(handle)
        close_handle(handle)


def _commit_files(files: dict[Path, str | bytes], *, overwrite: bool) -> list[Path]:
    if any(path.exists() for path in files) and not overwrite:
        raise AssetConflictError("One or more generated assets already exist")
    originals = {path: path.read_bytes() if path.exists() else None for path in files}
    staged: list[tuple[Path, Path]] = []
    replaced: list[Path] = []
    rollback_artifacts: list[Path] = []
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
                    rollback_artifacts.append(rollback)
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
        for rollback in rollback_artifacts:
            rollback.unlink(missing_ok=True)


def _write_files_locked(files: dict[Path, str | bytes], *, overwrite: bool) -> list[Path]:
    project_path = next(iter(files)).parents[1]
    with _hold_asset_directories(project_path, files):
        return _commit_files(files, overwrite=overwrite)


def _write_files(files: dict[Path, str | bytes], *, overwrite: bool = False) -> list[Path]:
    project_path = next(iter(files)).parents[1]
    with _project_lock(project_path):
        with _interprocess_project_lock(project_path):
            return _write_files_locked(files, overwrite=overwrite)


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


def _validate_source_png(source_png: Path) -> bytes:
    if not source_png.is_absolute() or source_png.suffix.lower() != ".png":
        raise ValueError("source_png must be an absolute PNG path")
    if not source_png.is_file() or _is_reparse_point(source_png):
        raise ValueError("source_png must be a regular PNG file")
    current = source_png.parent
    while current != current.parent:
        if _is_reparse_point(current):
            raise UnsafeAssetPathError("source_png may not traverse a reparse point")
        current = current.parent
    before = source_png.stat()
    with source_png.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        content = handle.read()
    after = source_png.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_opened = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_opened or identity_opened != identity_after:
        raise UnsafeAssetPathError("source_png changed while it was read")
    if not content.startswith(_PNG_SIGNATURE):
        raise ValueError("source_png is not a PNG file")
    return content


def save_thumbnail_variant(
    project_path: Path,
    source_png: Path,
    aspect: Literal["16:9", "9:16"],
    label: str,
) -> Path:
    """Copy one approved PNG byte-for-byte into a fixed project-local target."""
    if aspect not in _THUMBNAIL_ASPECTS:
        raise ValueError("aspect must be 16:9 or 9:16")
    if label not in _THUMBNAIL_LABELS:
        raise ValueError("label must be A, B, or C")
    content = _validate_source_png(source_png)
    target = project_path / "Thumbnails" / f"thumbnail-{label}-{_THUMBNAIL_ASPECTS[aspect]}.png"
    return _write_files({target: content})[0]


def _validate_packaging_document(document: Mapping[str, Any]) -> None:
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("packaging candidates must be a list")
    labels: set[str] = set()
    score_names = {
        "curiosity", "clarity", "search_relevance", "audience_fit", "uniqueness",
        "title_thumbnail_complementarity",
    }
    required_text = {
        "title", "hook", "seo_description", "pinned_comment", "chapters", "playlist",
        "next_video_cta", "rationale",
    }
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("invalid packaging candidate")
        label = candidate.get("label")
        if label not in _THUMBNAIL_LABELS or label in labels:
            raise ValueError("candidate labels must be unique A, B, or C")
        labels.add(label)
        if any(not isinstance(candidate.get(field), str) or not candidate[field].strip() for field in required_text):
            raise ValueError("packaging candidate text fields must not be blank")
        tags = candidate.get("tags")
        if not isinstance(tags, list) or not tags or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError("packaging candidate tags must not be blank")
        thumbnail = candidate.get("thumbnail")
        if not isinstance(thumbnail, Mapping) or thumbnail.get("aspect") not in _THUMBNAIL_ASPECTS:
            raise ValueError("invalid packaging thumbnail")
        expected_file = f"Thumbnails/thumbnail-{label}-{_THUMBNAIL_ASPECTS[thumbnail['aspect']]}.png"
        if thumbnail.get("file") != expected_file:
            raise UnsafeAssetPathError("packaging thumbnail must use its fixed project path")
        scores = candidate.get("scores")
        if not isinstance(scores, Mapping) or set(scores) != score_names:
            raise ValueError("all six advisory scores are required")
        if any(type(score) is not int or not 0 <= score <= 100 for score in scores.values()):
            raise ValueError("advisory scores must be integers from 0 to 100")


def write_packaging_candidates(
    project_path: Path, document: Mapping[str, Any], *, overwrite: bool = False
) -> Path:
    _validate_packaging_document(document)
    rendered = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target = project_path / "Metadata" / "packaging-candidates.json"
    return _write_files({target: rendered}, overwrite=overwrite)[0]


def read_packaging_candidates(project_path: Path) -> dict[str, Any]:
    _validate_project_root(project_path)
    target = project_path / "Metadata" / "packaging-candidates.json"
    if not target.exists():
        return {"candidates": []}
    with _project_lock(project_path):
        with _interprocess_project_lock(project_path):
            with _hold_asset_directories(project_path, (target,)):
                document = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("invalid packaging candidate file")
                _validate_packaging_document(document)
                return document
