from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./skeleton_growth.db"
    master_project_folder: str = r"I:\YouTube Projects"
    youtube_client_secret_path: str | None = None
    youtube_token_path: str | None = None
    youtube_redirect_uri: str = "http://127.0.0.1:8000/youtube/oauth/callback"
    expected_youtube_channel_id: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
