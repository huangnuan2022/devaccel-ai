from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes import get_cloudwatch_logs_service
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


def test_observability_cloudwatch_events_endpoint_uses_correlation(
    client: TestClient,
) -> None:
    class FakeCloudWatchLogsService:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def get_events(self, **kwargs: object) -> list[object]:
            self.calls.append(kwargs)

            class Event:
                message = "task-123 failed with TimeoutError"
                timestamp = 1714200000000
                ingestion_time = 1714200000100
                event_id = "event-1"
                log_stream_name = "ecs/api/task-123"

            return [Event()]

    fake_cloudwatch = FakeCloudWatchLogsService()
    response = client.post(
        "/api/v1/observability/github-check-runs",
        json={
            "repo_full_name": "acme/payments",
            "github_check_run_id": 123456789,
            "cloudwatch_log_group": "/aws/ecs/devaccel",
            "cloudwatch_log_stream": "ecs/api/task-123",
            "task_id": "task-123",
        },
    )
    correlation_id = response.json()["correlation_id"]

    from app.main import app

    app.dependency_overrides[get_cloudwatch_logs_service] = lambda: fake_cloudwatch
    try:
        events_response = client.get(
            f"/api/v1/observability/correlations/{correlation_id}/cloudwatch-events"
        )
    finally:
        app.dependency_overrides.pop(get_cloudwatch_logs_service, None)

    assert events_response.status_code == 200
    body = events_response.json()
    assert body["correlation_id"] == "task:task-123"
    assert body["log_group_name"] == "/aws/ecs/devaccel"
    assert body["log_stream_name"] == "ecs/api/task-123"
    assert body["filter_pattern"] == '"task-123"'
    assert body["events"][0]["message"] == "task-123 failed with TimeoutError"
    assert fake_cloudwatch.calls == [
        {
            "log_group_name": "/aws/ecs/devaccel",
            "log_stream_name": "ecs/api/task-123",
            "filter_pattern": '"task-123"',
            "limit": 50,
        }
    ]
