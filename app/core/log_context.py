from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import uuid


LOG_CONTEXT_FIELDS = (
    "request_id",
    "delivery_id",
    "task_id",
    "pull_request_id",
    "flaky_test_id",
    "installation_id",
)

_log_context: ContextVar[dict[str, str]] = ContextVar("log_context", default={})


def ensure_request_id(request_id: str | None = None) -> str:
    if request_id and request_id.strip():
        return request_id.strip()
    return uuid.uuid4().hex


def clear_log_context() -> None:
    _log_context.set({})


def get_log_record_context() -> dict[str, str]:
    current = _log_context.get()
    return {field: current.get(field, "-") for field in LOG_CONTEXT_FIELDS}


def get_serialized_log_context() -> dict[str, str]:
    return {key: value for key, value in _log_context.get().items() if value}


@contextmanager
def bind_log_context(**context: object) -> Iterator[None]:
    current = dict(_log_context.get())
    updates = {
        key: str(value)
        for key, value in context.items()
        if value is not None and str(value).strip()
    }
    token = _log_context.set({**current, **updates})
    try:
        yield
    finally:
        _log_context.reset(token)
