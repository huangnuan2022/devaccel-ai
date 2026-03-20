from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.flaky_test import FlakyTestRun
from app.api.routes import get_flaky_test_workflow_service
from app.services.exceptions import TaskDispatchError


def test_create_flaky_test_triage_enqueues_job(client: TestClient, db_session: Session) -> None:
    payload = {
        "test_name": "test_retry_payment_timeout",
        "suite_name": "payments.integration",
        "branch_name": "main",
        "failure_log": "TimeoutError: operation exceeded 30 seconds",
    }

    with patch("app.api.routes.TaskDispatcher.dispatch_flaky_test_triage") as dispatch_mock:
        response = client.post("/api/v1/flaky-tests/triage", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["error_message"] is None
    assert body["cluster_key"] == "pending"
    assert body["suspected_root_cause"] == ""
    assert body["suggested_fix"] == ""

    run = db_session.get(FlakyTestRun, body["id"])
    assert run is not None
    assert run.test_name == "test_retry_payment_timeout"
    dispatch_mock.assert_called_once_with(run.id)


def test_get_flaky_test_triage_returns_completed_result(
    client: TestClient, db_session: Session
) -> None:
    run = FlakyTestRun(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
        status="completed",
        cluster_key="cluster:test_retry_payment_timeout",
        suspected_root_cause="Intermittent timeout while waiting for retry completion",
        suggested_fix="Stabilize async wait and add retry instrumentation",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    response = client.get(f"/api/v1/flaky-tests/{run.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": run.id,
        "test_name": "test_retry_payment_timeout",
        "suite_name": "payments.integration",
        "branch_name": "main",
        "status": "completed",
        "error_message": None,
        "cluster_key": "cluster:test_retry_payment_timeout",
        "suspected_root_cause": "Intermittent timeout while waiting for retry completion",
        "suggested_fix": "Stabilize async wait and add retry instrumentation",
        "created_at": response.json()["created_at"],
    }


def test_get_flaky_test_triage_returns_failed_error_message(
    client: TestClient, db_session: Session
) -> None:
    run = FlakyTestRun(
        test_name="test_retry_payment_timeout",
        suite_name="payments.integration",
        branch_name="main",
        failure_log="TimeoutError: operation exceeded 30 seconds",
        status="failed",
        error_message="OpenAI response was not valid JSON",
        cluster_key="pending",
        suspected_root_cause="",
        suggested_fix="",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    response = client.get(f"/api/v1/flaky-tests/{run.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_message"] == "OpenAI response was not valid JSON"


def test_get_flaky_test_triage_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/flaky-tests/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Flaky test run not found"}


def test_create_flaky_test_triage_returns_422_for_invalid_payload(client: TestClient) -> None:
    response = client.post(
        "/api/v1/flaky-tests/triage",
        json={
            "test_name": "test_retry_payment_timeout",
            "suite_name": "payments.integration",
            "branch_name": "main",
        },
    )

    assert response.status_code == 422


def test_create_flaky_test_triage_returns_503_when_dispatch_fails() -> None:
    class FailingWorkflow:
        def enqueue_triage(self, payload: object) -> object:
            raise TaskDispatchError("Failed to dispatch flaky test triage for run 1")

    app.dependency_overrides[get_flaky_test_workflow_service] = lambda: FailingWorkflow()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/flaky-tests/triage",
            json={
                "test_name": "test_retry_payment_timeout",
                "suite_name": "payments.integration",
                "branch_name": "main",
                "failure_log": "TimeoutError: operation exceeded 30 seconds",
            },
        )

        assert response.status_code == 503
        assert "Failed to dispatch flaky test triage" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
