import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.log_context import bind_log_context
from app.db.session import get_db
from app.schemas.flaky_test import FlakyTestTriageRequest, FlakyTestTriageResponse
from app.schemas.pull_request import PullRequestAnalysisResponse, PullRequestAnalyzeRequest
from app.services.async_dispatch import AsyncWorkflowDispatcher
from app.services.exceptions import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    TaskDispatchError,
)
from app.services.flaky_triage import FlakyTestService
from app.services.github import GitHubWebhookService
from app.services.pr_analysis import PullRequestService
from app.services.sqs_step_functions_dispatcher import SqsStepFunctionsDispatcher
from app.services.step_functions_dispatcher import StepFunctionsDispatcher
from app.services.task_dispatcher import TaskDispatcher
from app.services.workflows import (
    FlakyTestWorkflowService,
    GitHubWebhookWorkflowService,
    PullRequestAnalysisWorkflowService,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def get_github_webhook_service() -> GitHubWebhookService:
    return GitHubWebhookService()


def get_task_dispatcher() -> AsyncWorkflowDispatcher:
    backend = get_settings().async_dispatch_backend.strip().lower()
    if backend == "celery":
        return TaskDispatcher()
    if backend == "step_functions":
        return StepFunctionsDispatcher()
    if backend == "sqs_step_functions":
        return SqsStepFunctionsDispatcher()
    raise RuntimeError(f"Unsupported async_dispatch_backend: {backend}")


def get_pull_request_service(db: Annotated[Session, Depends(get_db)]) -> PullRequestService:
    return PullRequestService(db)


def get_flaky_test_service(db: Annotated[Session, Depends(get_db)]) -> FlakyTestService:
    return FlakyTestService(db)


def get_pull_request_analysis_workflow_service(
    pr_service: Annotated[PullRequestService, Depends(get_pull_request_service)],
    dispatcher: Annotated[AsyncWorkflowDispatcher, Depends(get_task_dispatcher)],
) -> PullRequestAnalysisWorkflowService:
    return PullRequestAnalysisWorkflowService(
        pr_service=pr_service,
        dispatcher=dispatcher,
    )


def get_github_webhook_workflow_service(
    webhook_service: Annotated[GitHubWebhookService, Depends(get_github_webhook_service)],
    pr_workflow: Annotated[
        PullRequestAnalysisWorkflowService,
        Depends(get_pull_request_analysis_workflow_service),
    ],
) -> GitHubWebhookWorkflowService:
    return GitHubWebhookWorkflowService(
        github_webhook_service=webhook_service,
        pr_analysis_workflow=pr_workflow,
    )


def get_flaky_test_workflow_service(
    flaky_test_service: Annotated[FlakyTestService, Depends(get_flaky_test_service)],
    dispatcher: Annotated[AsyncWorkflowDispatcher, Depends(get_task_dispatcher)],
) -> FlakyTestWorkflowService:
    return FlakyTestWorkflowService(
        flaky_test_service=flaky_test_service,
        dispatcher=dispatcher,
    )


def _require_flaky_triage_ingest_token(authorization: str) -> None:
    token = get_settings().flaky_triage_ingest_token.strip()
    if not token:
        return

    expected = f"Bearer {token}"
    if authorization.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid flaky triage ingest token")


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    workflow: Annotated[
        GitHubWebhookWorkflowService,
        Depends(get_github_webhook_workflow_service),
    ],
    x_github_event: Annotated[str, Header()] = "",
    x_hub_signature_256: Annotated[str, Header()] = "",
    x_github_delivery: Annotated[str, Header()] = "",
) -> dict[str, str | int]:
    raw_body = await request.body()
    payload = await request.json()
    try:
        if not x_github_delivery.strip():
            raise InvalidWebhookPayloadError("Missing GitHub webhook delivery id")
        with bind_log_context(delivery_id=x_github_delivery):
            logger.info("Received GitHub webhook event=%s", x_github_event or "-")
            record = workflow.handle_webhook(
                event_name=x_github_event,
                signature=x_hub_signature_256,
                raw_body=raw_body,
                payload=payload,
                delivery_id=x_github_delivery,
            )
            if record is None:
                return {"status": "ignored"}
            logger.info("Accepted GitHub webhook pull_request_id=%s", record.id)
            return {"status": "accepted", "pull_request_id": record.id}
    except InvalidWebhookSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except InvalidWebhookPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/pull-requests/analyze", response_model=PullRequestAnalysisResponse, status_code=202)
def create_pull_request_analysis(
    payload: PullRequestAnalyzeRequest,
    workflow: Annotated[
        PullRequestAnalysisWorkflowService,
        Depends(get_pull_request_analysis_workflow_service),
    ],
) -> PullRequestAnalysisResponse:
    try:
        record = workflow.enqueue_analysis(payload)
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    logger.info(
        "Accepted pull request analysis request pull_request_id=%s repo=%s pr_number=%s",
        record.id,
        record.repo_full_name,
        record.pr_number,
    )
    return PullRequestAnalysisResponse(
        id=record.id,
        repo_full_name=record.repo_full_name,
        pr_number=record.pr_number,
        title=record.title,
        author=record.author,
        status=record.status,
        error_message=record.error_message,
        created_at=record.created_at,
    )


@router.get("/pull-requests/{pull_request_id}", response_model=PullRequestAnalysisResponse)
def get_pull_request_analysis(
    pull_request_id: int,
    service: Annotated[PullRequestService, Depends(get_pull_request_service)],
) -> PullRequestAnalysisResponse:
    record = service.get_analysis(pull_request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Pull request not found")

    latest = record.analyses[-1] if record.analyses else None
    return PullRequestAnalysisResponse(
        id=record.id,
        repo_full_name=record.repo_full_name,
        pr_number=record.pr_number,
        title=record.title,
        author=record.author,
        status=record.status,
        error_message=record.error_message,
        summary=latest.summary if latest else None,
        risks=latest.risks if latest else None,
        suggested_tests=latest.suggested_tests if latest else None,
        created_at=record.created_at,
    )


@router.post("/flaky-tests/triage", response_model=FlakyTestTriageResponse, status_code=202)
def create_flaky_test_triage(
    payload: FlakyTestTriageRequest,
    workflow: Annotated[
        FlakyTestWorkflowService,
        Depends(get_flaky_test_workflow_service),
    ],
    authorization: Annotated[str, Header()] = "",
) -> FlakyTestTriageResponse:
    _require_flaky_triage_ingest_token(authorization)
    try:
        run = workflow.enqueue_triage(payload)
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    logger.info(
        "Accepted flaky triage request flaky_test_id=%s test_name=%s",
        run.id,
        run.test_name,
    )
    return FlakyTestTriageResponse.model_validate(run)


@router.get("/flaky-tests/{flaky_test_id}", response_model=FlakyTestTriageResponse)
def get_flaky_test_triage(
    flaky_test_id: int,
    service: Annotated[FlakyTestService, Depends(get_flaky_test_service)],
) -> FlakyTestTriageResponse:
    run = service.get_triage(flaky_test_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Flaky test run not found")
    return FlakyTestTriageResponse.model_validate(run)
