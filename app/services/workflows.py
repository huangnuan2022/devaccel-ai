import logging

from app.core.log_context import bind_log_context
from app.models.flaky_test import FlakyTestRun
from app.models.pull_request import PullRequestRecord
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.schemas.pull_request import PullRequestAnalyzeRequest
from app.services.exceptions import TaskDispatchError
from app.services.flaky_triage import FlakyTestService
from app.services.github import GitHubWebhookService
from app.services.pr_analysis import PullRequestService
from app.services.task_dispatcher import TaskDispatcher

logger = logging.getLogger(__name__)


class PullRequestAnalysisWorkflowService:
    def __init__(self, pr_service: PullRequestService, dispatcher: TaskDispatcher) -> None:
        self.pr_service = pr_service
        self.dispatcher = dispatcher

    def enqueue_analysis(
        self, payload: PullRequestAnalyzeRequest, delivery_id: str | None = None
    ) -> PullRequestRecord:
        with bind_log_context(delivery_id=delivery_id, installation_id=payload.installation_id):
            record = self.pr_service.create_analysis_job_with_delivery(
                payload, delivery_id=delivery_id
            )
            try:
                task_id = self.dispatcher.dispatch_pull_request_analysis(record.id)
            except Exception as exc:
                self.pr_service.mark_dispatch_failed(record.id, str(exc))
                raise TaskDispatchError(
                    f"Failed to dispatch pull request analysis for record {record.id}"
                ) from exc
            with bind_log_context(task_id=task_id, pull_request_id=record.id):
                logger.info(
                    "Dispatched pull request analysis task pull_request_id=%s task_id=%s",
                    record.id,
                    task_id,
                )
            return record


class GitHubWebhookWorkflowService:
    def __init__(
        self,
        github_webhook_service: GitHubWebhookService,
        pr_analysis_workflow: PullRequestAnalysisWorkflowService,
    ) -> None:
        self.github_webhook_service = github_webhook_service
        self.pr_analysis_workflow = pr_analysis_workflow

    def handle_webhook(
        self,
        event_name: str,
        signature: str,
        raw_body: bytes,
        payload: dict,
        delivery_id: str,
    ) -> PullRequestRecord | None:
        with bind_log_context(delivery_id=delivery_id):
            existing = self.pr_analysis_workflow.pr_service.get_by_delivery_id(delivery_id)
            if existing is not None:
                logger.info(
                    "Reused existing pull request record for duplicate delivery pull_request_id=%s",
                    existing.id,
                )
                return existing

            analyze_request = self.github_webhook_service.handle_event(
                event_name=event_name,
                signature=signature,
                raw_body=raw_body,
                payload=payload,
            )
            if analyze_request is None:
                logger.info("Ignored GitHub webhook event=%s", event_name)
                return None
            return self.pr_analysis_workflow.enqueue_analysis(
                analyze_request, delivery_id=delivery_id
            )


class FlakyTestWorkflowService:
    def __init__(self, flaky_test_service: FlakyTestService, dispatcher: TaskDispatcher) -> None:
        self.flaky_test_service = flaky_test_service
        self.dispatcher = dispatcher

    def enqueue_triage(self, payload: FlakyTestTriageRequest) -> FlakyTestRun:
        run = self.flaky_test_service.create_triage_job(payload)
        try:
            task_id = self.dispatcher.dispatch_flaky_test_triage(run.id)
        except Exception as exc:
            self.flaky_test_service.mark_dispatch_failed(run.id, str(exc))
            raise TaskDispatchError(f"Failed to dispatch flaky test triage for run {run.id}") from exc
        with bind_log_context(task_id=task_id, flaky_test_id=run.id):
            logger.info(
                "Dispatched flaky triage task flaky_test_id=%s task_id=%s",
                run.id,
                task_id,
            )
        return run
