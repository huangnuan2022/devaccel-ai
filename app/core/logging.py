import logging

from app.core.log_context import get_log_record_context


class LogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_log_record_context().items():
            setattr(record, key, value)
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)s [%(name)s] "
            "request_id=%(request_id)s delivery_id=%(delivery_id)s task_id=%(task_id)s "
            "pull_request_id=%(pull_request_id)s flaky_test_id=%(flaky_test_id)s "
            "installation_id=%(installation_id)s correlation_id=%(correlation_id)s "
            "github_check_run_id=%(github_check_run_id)s "
            "cloudwatch_log_stream=%(cloudwatch_log_stream)s %(message)s"
        ),
    )
    context_filter = LogContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(context_filter)
