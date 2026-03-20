from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import engine
from app.models import FlakyTestRun, PullRequestAnalysis, PullRequestRecord

settings = get_settings()
configure_logging(settings.log_level)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Keep local onboarding easy, but avoid treating ad hoc table creation as a
    # production behavior. Real deployed environments should rely on migrations.
    if settings.app_env == "local":
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "DevAccel-AI is running"}
