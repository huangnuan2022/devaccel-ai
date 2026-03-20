from app.db.session import SessionLocal
from app.services.pr_analysis import PullRequestService
from app.workers.celery_app import celery_app


@celery_app.task(name="pr.analyze")
def analyze_pull_request_task(pull_request_id: int) -> None:
    db = SessionLocal()
    try:
        service = PullRequestService(db)
        service.process_analysis(pull_request_id)
    finally:
        db.close()
