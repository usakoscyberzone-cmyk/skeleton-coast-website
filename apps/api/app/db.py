from collections.abc import Iterator
import time

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def upgrade_media_files_schema(bind) -> None:
    inspector = inspect(bind)
    if "media_files" not in inspector.get_table_names():
        return
    column_names = {
        column["name"] for column in inspector.get_columns("media_files")
    }
    with bind.begin() as connection:
        if "probe_error" not in column_names:
            connection.exec_driver_sql("ALTER TABLE media_files ADD COLUMN probe_error TEXT")
        connection.exec_driver_sql(
            "DELETE FROM media_files WHERE id NOT IN ("
            "SELECT MIN(id) FROM media_files GROUP BY project_id, path)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_files_project_path "
            "ON media_files (project_id, path)"
        )


def begin_immediate_transaction(
    session: Session, *, max_attempts: int = 20, retry_delay_seconds: float = 0.05
) -> None:
    for attempt in range(max_attempts):
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            return
        except OperationalError as error:
            session.rollback()
            if not _is_sqlite_lock_error(error) or attempt == max_attempts - 1:
                raise
            time.sleep(retry_delay_seconds)


def _is_sqlite_lock_error(error: OperationalError) -> bool:
    return "database is locked" in str(error.orig).lower()
