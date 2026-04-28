from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.observability import ObservabilityCorrelation
from app.schemas.flaky_test import FlakyTestTriageRequest
from app.services.async_dispatch import AsyncDispatchResult
from app.services.flaky_triage import FlakyTestService
from app.services.workflows import FlakyTestWorkflowService


def test_flaky_triage_ingest_and_dispatch_updates_observability_correlation(
    db_session: Session,
) -> None:
    settings = get_settings()
    original_log_group = settings.cloudwatch_log_group
    settings.cloudwatch_log_group = "/aws/ecs/devaccel"
    try:
        flaky_service = FlakyTestService(db_session)
        dispatcher = Mock()
        dispatcher.dispatch_flaky_test_triage.return_value = AsyncDispatchResult(
            task_id="celery-task-123",
            backend_name="celery",
        )
        workflow = FlakyTestWorkflowService(
            flaky_test_service=flaky_service,
            dispatcher=dispatcher,
        )
        payload = FlakyTestTriageRequest(
            test_name="test_retry_payment_timeout",
            suite_name="payments.integration",
            branch_name="main",
            ci_provider="github_actions",
            repo_full_name="acme/payments",
            workflow_name="CI",
            job_name="pytest",
            run_url="https://github.com/acme/payments/actions/runs/123",
            commit_sha="abc123def456",
            github_check_run_id=987654321,
            github_check_run_name="pytest",
            github_check_run_status="completed",
            github_check_run_conclusion="failure",
            github_check_run_url="https://github.com/acme/payments/runs/987654321",
            cloudwatch_log_stream="ecs/api/celery-task-123",
            failure_log="TimeoutError: operation exceeded 30 seconds",
        )

        run = workflow.enqueue_triage(payload)

        correlation = db_session.query(ObservabilityCorrelation).one()
        assert correlation.correlation_id == f"flaky_test_run:{run.id}"
        assert correlation.flaky_test_id == run.id
        assert correlation.repo_full_name == "acme/payments"
        assert correlation.github_check_run_id == 987654321
        assert correlation.github_workflow_name == "CI"
        assert correlation.github_job_name == "pytest"
        assert correlation.github_run_url == "https://github.com/acme/payments/actions/runs/123"
        assert correlation.cloudwatch_log_group == "/aws/ecs/devaccel"
        assert correlation.cloudwatch_log_stream == "ecs/api/celery-task-123"
        assert correlation.dispatch_backend == "celery"
        assert correlation.task_id == "celery-task-123"
    finally:
        settings.cloudwatch_log_group = original_log_group


def test_observability_github_check_run_endpoint_records_and_fetches_correlation(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/observability/github-check-runs",
        json={
            "repo_full_name": "acme/payments",
            "commit_sha": "abc123def456",
            "github_check_run_id": 123456789,
            "github_check_run_name": "pytest",
            "github_check_run_status": "completed",
            "github_check_run_conclusion": "failure",
            "github_check_run_url": "https://github.com/acme/payments/runs/123456789",
            "github_workflow_name": "CI",
            "github_job_name": "pytest",
            "github_run_url": "https://github.com/acme/payments/actions/runs/123",
            "cloudwatch_log_group": "/aws/ecs/devaccel",
            "cloudwatch_log_stream": "ecs/api/task-123",
            "task_id": "task-123",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["correlation_id"] == "task:task-123"
    assert body["github_check_run_id"] == 123456789
    assert body["cloudwatch_log_stream"] == "ecs/api/task-123"

    fetch_response = client.get(
        f"/api/v1/observability/correlations/{body['correlation_id']}"
    )

    assert fetch_response.status_code == 200
    assert fetch_response.json()["repo_full_name"] == "acme/payments"
    assert fetch_response.json()["github_check_run_conclusion"] == "failure"
