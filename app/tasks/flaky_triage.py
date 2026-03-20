from app.db.session import SessionLocal
from app.services.flaky_triage import FlakyTestService
from app.workers.celery_app import celery_app


@celery_app.task(name="flaky.triage")
def triage_flaky_test_task(flaky_test_id: int) -> None:
    db = SessionLocal()
    try:
        service = FlakyTestService(db)
        service.process_triage(flaky_test_id)
    finally:
        db.close()
