from dataclasses import dataclass
import os
from pathlib import Path


OUTPUT_DIRS = ("Thumbnails", "Shorts", "Captions", "Metadata", "Analytics", "Exports")


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
