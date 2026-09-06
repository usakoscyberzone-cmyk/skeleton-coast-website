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
    if bind.dialect.name != "sqlite":
        return

    connection = bind.connect()
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        inspector = inspect(connection)
        if "media_files" not in inspector.get_table_names():
            connection.commit()
            return
        column_names = {
            column["name"] for column in inspector.get_columns("media_files")
        }
        if "probe_error" not in column_names:
            connection.exec_driver_sql("ALTER TABLE media_files ADD COLUMN probe_error TEXT")
        connection.exec_driver_sql(
            "DELETE FROM media_files WHERE id NOT IN ("
            "SELECT MIN(id) FROM media_files GROUP BY project_id, path)"
        )
        if not _has_unique_project_path_index(connection):
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_media_files_project_path "
                "ON media_files (project_id, path)"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


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


def _has_unique_project_path_index(connection) -> bool:
    for _, name, unique, *_ in connection.exec_driver_sql("PRAGMA index_list(media_files)"):
        if not unique:
            continue
        column_names = [
            row[2]
            for row in connection.exec_driver_sql(f"PRAGMA index_info('{name}')")
        ]
        if column_names == ["project_id", "path"]:
            return True
    return False
