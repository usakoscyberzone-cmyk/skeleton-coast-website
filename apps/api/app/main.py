from fastapi import FastAPI

from . import models
from .db import Base, engine
from .routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Skeleton Coast Growth Dashboard")
    app.include_router(health_router)

    @app.on_event("startup")
    def create_database_tables() -> None:
        Base.metadata.create_all(bind=engine)

    return app


app = create_app()
