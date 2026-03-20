from collections.abc import Generator
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.pull_request import PullRequestAnalysis, PullRequestRecord
from app.services.exceptions import TaskDispatchError
from app.api.routes import get_pull_request_analysis_workflow_service


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


def test_create_pull_request_analysis_enqueues_job() -> None:
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
        assert body["summary"] is None
        assert body["risks"] is None
        assert body["suggested_tests"] is None

        record = db.get(PullRequestRecord, body["id"])
        assert record is not None
        assert record.repo_full_name == "acme/payments"
        dispatch_mock.assert_called_once_with(record.id)
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_get_pull_request_analysis_returns_latest_analysis() -> None:
    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        record = PullRequestRecord(
            repo_full_name="acme/payments",
            pr_number=42,
            title="Refactor payment retry flow",
            author="alice",
            diff_text="+++ services/payment.py\n+ retry_count += 1",
            status="completed",
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        db.add(
            PullRequestAnalysis(
                pull_request_id=record.id,
                summary="PR analysis summary",
                risks="PR analysis risks",
                suggested_tests="PR analysis suggested tests",
                model_provider="mock",
            )
        )
        db.commit()

        client = TestClient(app)
        response = client.get(f"/api/v1/pull-requests/{record.id}")

        assert response.status_code == 200
        assert response.json() == {
            "id": record.id,
            "repo_full_name": "acme/payments",
            "pr_number": 42,
            "title": "Refactor payment retry flow",
            "author": "alice",
            "status": "completed",
            "summary": "PR analysis summary",
            "risks": "PR analysis risks",
            "suggested_tests": "PR analysis suggested tests",
            "created_at": response.json()["created_at"],
        }
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_get_pull_request_analysis_returns_404_when_missing() -> None:
    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        client = TestClient(app)
        response = client.get("/api/v1/pull-requests/999")

        assert response.status_code == 404
        assert response.json() == {"detail": "Pull request not found"}
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_create_pull_request_analysis_returns_422_for_invalid_payload() -> None:
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
            "/api/v1/pull-requests/analyze",
            json={
                "repo_full_name": "acme/payments",
                "pr_number": "not-an-int",
                "title": "Refactor payment retry flow",
                "author": "alice",
            },
        )

        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_create_pull_request_analysis_returns_503_when_dispatch_fails() -> None:
    class FailingWorkflow:
        def enqueue_analysis(self, payload: object) -> object:
            raise TaskDispatchError("Failed to dispatch pull request analysis for record 1")

    db = make_test_db()

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
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
        db.close()
