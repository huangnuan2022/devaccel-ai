import logging

from sqlalchemy.orm import Session, selectinload

from app.core.log_context import bind_log_context
from app.models.pull_request import PullRequestAnalysis, PullRequestRecord
from app.schemas.pull_request import PullRequestAnalyzeRequest
from app.services.exceptions import (
    GitHubPullRequestContentError,
    LLMProviderConfigurationError,
    LLMProviderInvocationError,
)
from app.services.github_pr_content import GitHubPullRequestContentService
from app.services.llm import LLMClient
from app.services.observability import ObservabilityService

WEBHOOK_DIFF_PLACEHOLDER = (
    "GitHub webhook payload does not include unified diff text. Fetch from GitHub API."
)


logger = logging.getLogger(__name__)


class PullRequestService:
    def __init__(
        self,
        db: Session,
        llm_client: LLMClient | None = None,
        github_content_service: GitHubPullRequestContentService | None = None,
    ) -> None:
        self.db = db
        self.llm_client = llm_client or LLMClient()
        self.github_content_service = github_content_service or GitHubPullRequestContentService()

    def create_analysis_job(self, payload: PullRequestAnalyzeRequest) -> PullRequestRecord:
        return self.create_analysis_job_with_delivery(payload)

    def create_analysis_job_with_delivery(
        self, payload: PullRequestAnalyzeRequest, delivery_id: str | None = None
    ) -> PullRequestRecord:
        record = PullRequestRecord(
            delivery_id=delivery_id,
            installation_id=payload.installation_id,
            repo_full_name=payload.repo_full_name,
            pr_number=payload.pr_number,
            title=payload.title,
            author=payload.author,
            diff_text=payload.diff_text,
            status="queued",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        ObservabilityService(self.db).record_pull_request_ingest(record)
        with bind_log_context(
            pull_request_id=record.id,
            delivery_id=record.delivery_id,
            installation_id=record.installation_id,
        ):
            logger.info(
                "Created pull request analysis job id=%s repo=%s pr_number=%s delivery_id=%s",
                record.id,
                record.repo_full_name,
                record.pr_number,
                record.delivery_id,
            )
        return record

    def get_by_delivery_id(self, delivery_id: str) -> PullRequestRecord | None:
        return (
            self.db.query(PullRequestRecord)
            .filter(PullRequestRecord.delivery_id == delivery_id)
            .first()
        )

    def process_analysis(self, pull_request_id: int) -> PullRequestRecord:
        record = self.db.get(PullRequestRecord, pull_request_id)
        if record is None:
            raise ValueError(f"Pull request {pull_request_id} not found")

        with bind_log_context(
            pull_request_id=record.id,
            delivery_id=record.delivery_id,
            installation_id=record.installation_id,
        ):
            logger.info(
                "Starting pull request analysis processing id=%s repo=%s pr_number=%s status=%s",
                record.id,
                record.repo_full_name,
                record.pr_number,
                record.status,
            )

            try:
                diff_text = record.diff_text
                if diff_text == WEBHOOK_DIFF_PLACEHOLDER:
                    logger.info(
                        "Pull request analysis requires GitHub patch fetch id=%s "
                        "repo=%s pr_number=%s",
                        record.id,
                        record.repo_full_name,
                        record.pr_number,
                    )
                    diff_text = self.github_content_service.fetch_pull_request_patch_bundle(
                        record.repo_full_name,
                        record.pr_number,
                        installation_id=record.installation_id,
                    )
                    record.diff_text = diff_text

                result = self.llm_client.analyze_pull_request(diff_text, record.title)
            except (
                GitHubPullRequestContentError,
                LLMProviderConfigurationError,
                LLMProviderInvocationError,
            ) as exc:
                logger.warning(
                    "Pull request analysis failed id=%s repo=%s pr_number=%s error=%s",
                    record.id,
                    record.repo_full_name,
                    record.pr_number,
                    exc,
                )
                self.mark_processing_failed(record.id, str(exc))
                raise

            analysis = PullRequestAnalysis(
                pull_request_id=record.id,
                summary=result.summary,
                risks=result.risks,
                suggested_tests=result.suggested_tests,
                model_provider=self.llm_client.provider_name,
            )
            record.status = "completed"
            record.error_message = None
            self.db.add(analysis)
            self.db.commit()
            self.db.refresh(record)
            logger.info(
                "Completed pull request analysis id=%s provider=%s",
                record.id,
                self.llm_client.provider_name,
            )
            return record

    def mark_dispatch_failed(
        self, pull_request_id: int, error_message: str | None = None
    ) -> PullRequestRecord:
        record = self.db.get(PullRequestRecord, pull_request_id)
        if record is None:
            raise ValueError(f"Pull request {pull_request_id} not found")

        record.status = "dispatch_failed"
        record.error_message = error_message
        self.db.commit()
        self.db.refresh(record)
        with bind_log_context(
            pull_request_id=record.id,
            delivery_id=record.delivery_id,
            installation_id=record.installation_id,
        ):
            logger.warning(
                "Marked pull request analysis dispatch_failed id=%s error_message=%s",
                record.id,
                record.error_message,
            )
        return record

    def mark_processing_failed(self, pull_request_id: int, error_message: str) -> PullRequestRecord:
        record = self.db.get(PullRequestRecord, pull_request_id)
        if record is None:
            raise ValueError(f"Pull request {pull_request_id} not found")

        record.status = "failed"
        record.error_message = error_message
        self.db.commit()
        self.db.refresh(record)
        with bind_log_context(
            pull_request_id=record.id,
            delivery_id=record.delivery_id,
            installation_id=record.installation_id,
        ):
            logger.warning(
                "Marked pull request analysis failed id=%s error_message=%s",
                record.id,
                record.error_message,
            )
        return record

    def get_analysis(self, pull_request_id: int) -> PullRequestRecord | None:
        return (
            self.db.query(PullRequestRecord)
            .options(selectinload(PullRequestRecord.analyses))
            .filter(PullRequestRecord.id == pull_request_id)
            .first()
        )
