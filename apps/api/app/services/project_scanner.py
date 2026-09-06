from dataclasses import dataclass
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

    folders = [path for path in master_folder.iterdir() if path.is_dir()]
    return [
        ProjectScan(name=path.name, path=path)
        for path in sorted(folders, key=lambda path: path.name.lower())
    ]
