from functools import lru_cache
import ntpath
import os
from pathlib import Path

from fastapi import HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict


V1_MASTER_PROJECT_FOLDER = r"I:\YouTube Projects"


class Settings(BaseSettings):
    database_url: str = "sqlite:///./skeleton_growth.db"
    master_project_folder: str = V1_MASTER_PROJECT_FOLDER
    youtube_client_secret_path: str | None = None
    youtube_token_path: str | None = None
    youtube_redirect_uri: str = "http://127.0.0.1:8000/youtube/oauth/callback"
    expected_youtube_channel_id: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_master_project_folder() -> Path:
    """Return the one approved V1 root, or fail before any filesystem mutation."""
    configured = get_settings().master_project_folder
    if _canonical_windows_path(configured) != _canonical_windows_path(V1_MASTER_PROJECT_FOLDER):
        raise HTTPException(
            status_code=503,
            detail=f"MASTER_PROJECT_FOLDER must be {V1_MASTER_PROJECT_FOLDER} for Version 1.",
        )
    root = Path(V1_MASTER_PROJECT_FOLDER)
    try:
        if not root.is_dir() or _is_reparse_point(root):
            raise OSError
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Create the master watched folder {V1_MASTER_PROJECT_FOLDER} before starting the API.",
        ) from exc
    if _canonical_windows_path(str(resolved)) != _canonical_windows_path(V1_MASTER_PROJECT_FOLDER):
        raise HTTPException(
            status_code=503,
            detail=f"MASTER_PROJECT_FOLDER must resolve directly to {V1_MASTER_PROJECT_FOLDER}; aliases and reparse points are not allowed.",
        )
    return resolved


def require_expected_youtube_channel_id() -> str:
    channel_id = get_settings().expected_youtube_channel_id
    if not channel_id:
        raise HTTPException(
            status_code=503,
            detail="EXPECTED_YOUTUBE_CHANNEL_ID must identify the single Version 1 channel.",
        )
    return channel_id


def _canonical_windows_path(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(ntpath.abspath(value)))


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or getattr(os.path, "isjunction", lambda _path: False)(path):
        return True
    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)
