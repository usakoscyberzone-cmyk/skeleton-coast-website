from fastapi import FastAPI

from . import models
from .db import Base, engine, upgrade_media_files_schema, upgrade_recommendations_schema, upgrade_short_plans_schema, upgrade_video_metrics_schema
from .routes.health import router as health_router
from .routes.projects import router as projects_router
from .routes.youtube import analytics_router, router as youtube_router
from .routes.recommendations import router as recommendations_router
from .routes.assets import router as assets_router
from .routes.learning import router as learning_router


def create_app() -> FastAPI:
    app = FastAPI(title="Skeleton Coast Growth Dashboard")
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(youtube_router)
    app.include_router(analytics_router)
    app.include_router(recommendations_router)
    app.include_router(assets_router)
    app.include_router(learning_router)

    @app.on_event("startup")
    def create_database_tables() -> None:
        Base.metadata.create_all(bind=engine)
        upgrade_media_files_schema(engine)
        upgrade_video_metrics_schema(engine)
        upgrade_recommendations_schema(engine)
        upgrade_short_plans_schema(engine)

    return app


app = create_app()
