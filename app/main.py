from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.api.routes import router
from app.core.config import get_settings
from app.core.log_context import bind_log_context, clear_log_context, ensure_request_id
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title=settings.app_name)
app.include_router(router, prefix=settings.api_prefix)


@app.middleware("http")
async def attach_request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    clear_log_context()
    request_id = ensure_request_id(request.headers.get("X-Request-ID"))
    try:
        with bind_log_context(request_id=request_id):
            response = await call_next(request)
    finally:
        clear_log_context()

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "DevAccel-AI is running"}
