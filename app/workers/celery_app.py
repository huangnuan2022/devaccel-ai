from celery import Celery
from kombu import Queue

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "devaccel_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.pr_analysis", "app.tasks.flaky_triage"],
)

celery_app.conf.task_queues = (
    Queue("pr-analysis"),
    Queue("flaky-triage"),
)

celery_app.conf.task_routes = {
    "pr.analyze": {"queue": "pr-analysis"},
    "flaky.triage": {"queue": "flaky-triage"},
}
