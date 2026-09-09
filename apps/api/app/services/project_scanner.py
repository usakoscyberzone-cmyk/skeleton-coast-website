from dataclasses import dataclass
import os
from pathlib import Path

from .media_probe import MediaProbeResult, media_kind, probe_media


OUTPUT_DIRS = ("Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports")
OUTPUT_DIR_NAMES = frozenset(name.casefold() for name in OUTPUT_DIRS)


@dataclass(frozen=True)
class ProjectScan:
    name: str
    path: Path


def ensure_project_structure(project_path: Path) -> list[Path]:
    created = []
    for name in OUTPUT_DIRS:
        path = project_path / name
        path.mkdir(exist_ok=True)
        created.append(path)
    return created


def scan_master_folder(master_folder: Path) -> list[ProjectScan]:
    if not master_folder.exists():
        return []

    resolved_master = master_folder.resolve()
    is_junction = getattr(os.path, "isjunction", lambda path: False)
    folders = []
    for path in master_folder.iterdir():
        if not path.is_dir() or path.is_symlink() or is_junction(path):
            continue

        resolved_path = path.resolve()
        if resolved_path.parent != resolved_master:
            continue
        folders.append(resolved_path)

    return [
        ProjectScan(name=path.name, path=path)
        for path in sorted(
            folders, key=lambda path: (path.name.casefold(), path.name, str(path))
        )
    ]


def scan_media_files(project_path: Path) -> list[MediaProbeResult]:
    if (
        not project_path.is_dir()
        or project_path.is_symlink()
        or _is_junction(project_path)
    ):
        return []

    resolved_project = _resolve_path(project_path)
    if resolved_project is None:
        return []
    source_files: list[Path] = []
    for root, directories, filenames in os.walk(project_path, topdown=True):
        root_path = Path(root)
        if _should_skip_directory(
            root_path,
            resolved_project,
            include_generated_name=root_path != project_path,
        ):
            directories[:] = []
            continue
        directories[:] = [
            directory
            for directory in directories
            if not _should_skip_directory(root_path / directory, resolved_project)
        ]
        for filename in filenames:
            path = root_path / filename
            resolved_path = _resolve_path(path)
            if (
                path.is_symlink()
                or _is_junction(path)
                or resolved_path is None
                or not _is_within(resolved_path, resolved_project)
                or media_kind(path) is None
            ):
                continue
            source_files.append(path)

    ordered_files = sorted(
        source_files,
        key=lambda path: (
            str(path.relative_to(project_path)).casefold(),
            str(path.relative_to(project_path)),
            str(path),
        ),
    )
    results = []
    for path in ordered_files:
        try:
            results.append(probe_media(path))
        except OSError:
            results.append(
                MediaProbeResult(
                    path=path,
                    kind=media_kind(path) or "unknown",
                    probe_error="unreadable_file",
                )
            )
        except Exception:
            results.append(
                MediaProbeResult(
                    path=path,
                    kind=media_kind(path) or "unknown",
                    probe_error="probe_unexpected_error",
                )
            )
    return results


def _should_skip_directory(
    path: Path, resolved_project: Path, *, include_generated_name: bool = True
) -> bool:
    return (
        (include_generated_name and path.name.casefold() in OUTPUT_DIR_NAMES)
        or path.is_symlink()
        or _is_junction(path)
        or (resolved_path := _resolve_path(path)) is None
        or not _is_within(resolved_path, resolved_project)
    )


def _is_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda _: False)
    return is_junction(path)


def _resolve_path(path: Path) -> Path | None:
    try:
        return path.resolve()
    except OSError:
        return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
