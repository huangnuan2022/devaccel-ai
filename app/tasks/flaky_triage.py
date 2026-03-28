from app.core.log_context import bind_log_context, clear_log_context
from app.db.session import SessionLocal
from app.services.flaky_triage import FlakyTestService
from app.workers.celery_app import celery_app


@celery_app.task(name="flaky.triage", bind=True)
def triage_flaky_test_task(self, flaky_test_id: int) -> None:
    db = SessionLocal()
    try:
        headers = getattr(self.request, "headers", {}) or {}
        clear_log_context()
        with bind_log_context(
            request_id=headers.get("request_id"),
            task_id=self.request.id,
            flaky_test_id=flaky_test_id,
        ):
            service = FlakyTestService(db)
            service.process_triage(flaky_test_id)
    finally:
        clear_log_context()
        db.close()
