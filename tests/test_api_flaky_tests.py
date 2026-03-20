from collections.abc import Generator
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.flaky_test import FlakyTestRun
from app.services.exceptions import TaskDispatchError
from app.api.routes import get_flaky_test_workflow_service


def make_test_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def test_create_flaky_test_triage_enqueues_job() -> None:
    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
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
        assert body["cluster_key"] == "pending"
        assert body["suspected_root_cause"] == ""
        assert body["suggested_fix"] == ""

        run = db.get(FlakyTestRun, body["id"])
        assert run is not None
        assert run.test_name == "test_retry_payment_timeout"
        dispatch_mock.assert_called_once_with(run.id)
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_get_flaky_test_triage_returns_completed_result() -> None:
    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
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
        db.add(run)
        db.commit()
        db.refresh(run)

        client = TestClient(app)
        response = client.get(f"/api/v1/flaky-tests/{run.id}")

        assert response.status_code == 200
        assert response.json() == {
            "id": run.id,
            "test_name": "test_retry_payment_timeout",
            "suite_name": "payments.integration",
            "branch_name": "main",
            "status": "completed",
            "cluster_key": "cluster:test_retry_payment_timeout",
            "suspected_root_cause": "Intermittent timeout while waiting for retry completion",
            "suggested_fix": "Stabilize async wait and add retry instrumentation",
            "created_at": response.json()["created_at"],
        }
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_get_flaky_test_triage_returns_404_when_missing() -> None:
    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        response = client.get("/api/v1/flaky-tests/999")

        assert response.status_code == 404
        assert response.json() == {"detail": "Flaky test run not found"}
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_create_flaky_test_triage_returns_422_for_invalid_payload() -> None:
    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/flaky-tests/triage",
            json={
                "test_name": "test_retry_payment_timeout",
                "suite_name": "payments.integration",
                "branch_name": "main",
            },
        )

        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_create_flaky_test_triage_returns_503_when_dispatch_fails() -> None:
    class FailingWorkflow:
        def enqueue_triage(self, payload: object) -> object:
            raise TaskDispatchError("Failed to dispatch flaky test triage for run 1")

    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
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
        db.close()
