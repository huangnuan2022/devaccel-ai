from sqlalchemy.orm import Session, selectinload

from app.models.pull_request import PullRequestAnalysis, PullRequestRecord
from app.schemas.pull_request import PullRequestAnalyzeRequest
from app.services.github_pr_content import GitHubPullRequestContentService
from app.services.llm import LLMClient


WEBHOOK_DIFF_PLACEHOLDER = (
    "GitHub webhook payload does not include unified diff text. Fetch from GitHub API."
)


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

        diff_text = record.diff_text
        if diff_text == WEBHOOK_DIFF_PLACEHOLDER:
            diff_text = self.github_content_service.fetch_pull_request_patch_bundle(
                record.repo_full_name,
                record.pr_number,
                installation_id=record.installation_id,
            )
            record.diff_text = diff_text

        result = self.llm_client.analyze_pull_request(diff_text, record.title)
        analysis = PullRequestAnalysis(
            pull_request_id=record.id,
            summary=result.summary,
            risks=result.risks,
            suggested_tests=result.suggested_tests,
            model_provider=self.llm_client.provider_name,
        )
        record.status = "completed"
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(record)
        return record

    def mark_dispatch_failed(self, pull_request_id: int) -> PullRequestRecord:
        record = self.db.get(PullRequestRecord, pull_request_id)
        if record is None:
            raise ValueError(f"Pull request {pull_request_id} not found")

        record.status = "dispatch_failed"
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_analysis(self, pull_request_id: int) -> PullRequestRecord | None:
        return (
            self.db.query(PullRequestRecord)
            .options(selectinload(PullRequestRecord.analyses))
            .filter(PullRequestRecord.id == pull_request_id)
            .first()
        )
