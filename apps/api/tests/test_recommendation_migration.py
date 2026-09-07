from sqlalchemy import create_engine, inspect, text

from app.db import upgrade_recommendations_schema


def test_legacy_recommendations_migration_keeps_only_newest_row_active_per_video_and_preserves_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-recommendations.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE recommendations (id INTEGER PRIMARY KEY, youtube_video_id TEXT NOT NULL, state TEXT, action TEXT, reason TEXT, confidence TEXT, data_used_json TEXT, created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO recommendations VALUES (1, 'video-a', 'amber', 'old', 'old', 'low', '{}', '2026-09-01 10:00:00')")
        connection.exec_driver_sql("INSERT INTO recommendations VALUES (2, 'video-a', 'red', 'new', 'new', 'medium', '{}', '2026-09-02 10:00:00')")
        connection.exec_driver_sql("INSERT INTO recommendations VALUES (3, 'video-b', 'green', 'only', 'only', 'high', '{}', '2026-09-01 12:00:00')")

    upgrade_recommendations_schema(engine)
    upgrade_recommendations_schema(engine)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, youtube_video_id, is_active FROM recommendations ORDER BY id")).all()
        indexes = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='recommendations'")}
    assert rows == [(1, "video-a", 0), (2, "video-a", 1), (3, "video-b", 1)]
    assert "uq_active_recommendation_per_video" in indexes
