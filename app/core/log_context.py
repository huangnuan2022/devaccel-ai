import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

LOG_CONTEXT_FIELDS = (
    "request_id",
    "delivery_id",
    "task_id",
    "pull_request_id",
    "flaky_test_id",
    "installation_id",
    "correlation_id",
    "github_check_run_id",
    "cloudwatch_log_stream",
)

_log_context: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)


def _current_log_context() -> dict[str, str]:
    return _log_context.get() or {}


def ensure_request_id(request_id: str | None = None) -> str:
    if request_id and request_id.strip():
        return request_id.strip()
    return uuid.uuid4().hex


def clear_log_context() -> None:
    _log_context.set({})


def get_log_record_context() -> dict[str, str]:
    current = _current_log_context()
    return {field: current.get(field, "-") for field in LOG_CONTEXT_FIELDS}


def get_serialized_log_context() -> dict[str, str]:
    return {key: value for key, value in _current_log_context().items() if value}


@contextmanager
def bind_log_context(**context: object) -> Iterator[None]:
    current = dict(_current_log_context())
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
