from app.core.log_context import bind_log_context, clear_log_context
from app.db.session import SessionLocal
from app.services.pr_analysis import PullRequestService
from app.workers.celery_app import celery_app


@celery_app.task(name="pr.analyze", bind=True)
def analyze_pull_request_task(self, pull_request_id: int) -> None:
    db = SessionLocal()
    try:
        headers = getattr(self.request, "headers", {}) or {}
        clear_log_context()
        with bind_log_context(
            request_id=headers.get("request_id"),
            delivery_id=headers.get("delivery_id"),
            task_id=self.request.id,
            pull_request_id=pull_request_id,
        ):
            service = PullRequestService(db)
            service.process_analysis(pull_request_id)
    finally:
        clear_log_context()
        db.close()
