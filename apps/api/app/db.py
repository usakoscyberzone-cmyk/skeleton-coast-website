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


def upgrade_video_metrics_schema(bind) -> None:
    """Rebuild legacy metric tables so unavailable API values are truly nullable."""
    if bind.dialect.name != "sqlite":
        return
    additions = {
        "analytics_start_date": "DATE", "analytics_end_date": "DATE", "title": "TEXT",
        "published_at": "DATETIME", "duration_seconds": "INTEGER", "length_seconds": "INTEGER", "video_type": "VARCHAR(32)", "format": "VARCHAR(32)",
        "topic": "VARCHAR(64)", "average_percentage_viewed": "FLOAT",
        "subscriber_conversion_rate": "FLOAT", "returning_viewers": "INTEGER",
        "retention_json": "TEXT", "views_1h": "INTEGER", "views_24h": "INTEGER", "views_7d": "INTEGER",
    }
    connection = bind.connect()
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        inspector = inspect(connection)
        if "video_metric_snapshots" in inspector.get_table_names():
            current = {column["name"]: column for column in inspector.get_columns("video_metric_snapshots")}
            required = {"views", "impressions", "ctr", "watch_minutes", "avg_view_duration_seconds", "subscribers_gained", "browse_share", "suggested_share", "search_share", "external_share", "shorts_feed_share"}
            needs_rebuild = any(name not in current or current[name]["nullable"] is False for name in required)
            if needs_rebuild:
                connection.exec_driver_sql("ALTER TABLE video_metric_snapshots RENAME TO video_metric_snapshots_legacy")
                from .models import VideoMetricSnapshot
                VideoMetricSnapshot.__table__.create(connection)
                legacy = {c["name"] for c in inspect(connection).get_columns("video_metric_snapshots_legacy")}
                target = [c.name for c in VideoMetricSnapshot.__table__.columns]
                common = [c for c in target if c in legacy]
                if common:
                    names = ", ".join(common)
                    connection.exec_driver_sql(f"INSERT OR IGNORE INTO video_metric_snapshots ({names}) SELECT {names} FROM video_metric_snapshots_legacy ORDER BY id")
                connection.exec_driver_sql("DROP TABLE video_metric_snapshots_legacy")
            else:
                for name, ddl in additions.items():
                    if name not in current:
                        connection.exec_driver_sql(f"ALTER TABLE video_metric_snapshots ADD COLUMN {name} {ddl}")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_video_metric_period_index ON video_metric_snapshots (youtube_video_id, analytics_start_date, analytics_end_date) WHERE analytics_start_date IS NOT NULL AND analytics_end_date IS NOT NULL")
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
