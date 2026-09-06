from dataclasses import dataclass
from functools import lru_cache
from os import getenv
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    master_project_folder: Path
    api_base_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        master_project_folder=Path(getenv("MASTER_PROJECT_FOLDER", r"I:\YouTube Projects")),
        api_base_url=getenv("API_BASE_URL", "http://127.0.0.1:8000"),
    )
