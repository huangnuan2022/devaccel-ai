from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.pull_request import PullRequestAnalysis, PullRequestRecord
from app.api.routes import get_pull_request_analysis_workflow_service
from app.services.exceptions import TaskDispatchError


def test_create_pull_request_analysis_enqueues_job(client: TestClient, db_session: Session) -> None:
    payload = {
        "repo_full_name": "acme/payments",
        "pr_number": 42,
        "title": "Refactor payment retry flow",
        "author": "alice",
        "diff_text": "+++ services/payment.py\n+ retry_count += 1",
    }

    with patch("app.api.routes.TaskDispatcher.dispatch_pull_request_analysis") as dispatch_mock:
        response = client.post("/api/v1/pull-requests/analyze", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["error_message"] is None
    assert body["summary"] is None
    assert body["risks"] is None
    assert body["suggested_tests"] is None

    record = db_session.get(PullRequestRecord, body["id"])
    assert record is not None
    assert record.repo_full_name == "acme/payments"
    dispatch_mock.assert_called_once_with(record.id)


def test_get_pull_request_analysis_returns_latest_analysis(
    client: TestClient, db_session: Session
) -> None:
    record = PullRequestRecord(
        repo_full_name="acme/payments",
        pr_number=42,
        title="Refactor payment retry flow",
        author="alice",
        diff_text="+++ services/payment.py\n+ retry_count += 1",
        status="completed",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    db_session.add(
        PullRequestAnalysis(
            pull_request_id=record.id,
            summary="PR analysis summary",
            risks="PR analysis risks",
            suggested_tests="PR analysis suggested tests",
            model_provider="mock",
        )
    )
    db_session.commit()

    response = client.get(f"/api/v1/pull-requests/{record.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": record.id,
        "repo_full_name": "acme/payments",
        "pr_number": 42,
        "title": "Refactor payment retry flow",
        "author": "alice",
        "status": "completed",
        "error_message": None,
        "summary": "PR analysis summary",
        "risks": "PR analysis risks",
        "suggested_tests": "PR analysis suggested tests",
        "created_at": response.json()["created_at"],
    }


def test_get_pull_request_analysis_returns_failed_error_message(
    client: TestClient, db_session: Session
) -> None:
    record = PullRequestRecord(
        repo_full_name="acme/payments",
        pr_number=42,
        title="Refactor payment retry flow",
        author="alice",
        diff_text="+++ services/payment.py\n+ retry_count += 1",
        status="failed",
        error_message="OpenAI request failed: timeout",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    response = client.get(f"/api/v1/pull-requests/{record.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_message"] == "OpenAI request failed: timeout"
    assert response.json()["summary"] is None


def test_get_pull_request_analysis_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/pull-requests/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Pull request not found"}


def test_create_pull_request_analysis_returns_422_for_invalid_payload(client: TestClient) -> None:
    response = client.post(
        "/api/v1/pull-requests/analyze",
        json={
            "repo_full_name": "acme/payments",
            "pr_number": "not-an-int",
            "title": "Refactor payment retry flow",
            "author": "alice",
        },
    )

    assert response.status_code == 422


def test_create_pull_request_analysis_returns_503_when_dispatch_fails() -> None:
    class FailingWorkflow:
        def enqueue_analysis(self, payload: object) -> object:
            raise TaskDispatchError("Failed to dispatch pull request analysis for record 1")

    app.dependency_overrides[get_pull_request_analysis_workflow_service] = lambda: FailingWorkflow()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/pull-requests/analyze",
            json={
                "repo_full_name": "acme/payments",
                "pr_number": 42,
                "title": "Refactor payment retry flow",
                "author": "alice",
                "diff_text": "+++ services/payment.py\n+ retry_count += 1",
            },
        )

        assert response.status_code == 503
        assert "Failed to dispatch pull request analysis" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
