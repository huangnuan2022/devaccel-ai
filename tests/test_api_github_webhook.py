from fastapi.testclient import TestClient

from app.api.routes import get_github_webhook_workflow_service
from app.main import app
from app.services.exceptions import InvalidWebhookPayloadError, InvalidWebhookSignatureError, TaskDispatchError


def test_github_webhook_returns_accepted_when_workflow_creates_job() -> None:
    class FakeRecord:
        id = 123

    class FakeWorkflow:
        def handle_webhook(
            self,
            event_name: str,
            signature: str,
            raw_body: bytes,
            payload: dict,
            delivery_id: str,
        ) -> FakeRecord:
            assert event_name == "pull_request"
            assert delivery_id == "delivery-123"
            return FakeRecord()

    app.dependency_overrides[get_github_webhook_workflow_service] = lambda: FakeWorkflow()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-123",
            },
            json={"action": "opened"},
        )

        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "pull_request_id": 123}
        assert response.headers["X-Request-ID"] != ""
    finally:
        app.dependency_overrides.clear()


def test_github_webhook_returns_ignored_when_workflow_ignores_event() -> None:
    class FakeWorkflow:
        def handle_webhook(
            self,
            event_name: str,
            signature: str,
            raw_body: bytes,
            payload: dict,
            delivery_id: str,
        ) -> None:
            return None

    app.dependency_overrides[get_github_webhook_workflow_service] = lambda: FakeWorkflow()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-ignored",
            },
            json={"action": "closed"},
        )

        assert response.status_code == 202
        assert response.json() == {"status": "ignored"}
        assert response.headers["X-Request-ID"] != ""
    finally:
        app.dependency_overrides.clear()


def test_github_webhook_preserves_supplied_request_id_header() -> None:
    class FakeWorkflow:
        def handle_webhook(
            self,
            event_name: str,
            signature: str,
            raw_body: bytes,
            payload: dict,
            delivery_id: str,
        ) -> None:
            return None

    app.dependency_overrides[get_github_webhook_workflow_service] = lambda: FakeWorkflow()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-request-id",
                "X-Request-ID": "req-explicit-123",
            },
            json={"action": "opened"},
        )

        assert response.status_code == 202
        assert response.headers["X-Request-ID"] == "req-explicit-123"
    finally:
        app.dependency_overrides.clear()


def test_github_webhook_returns_422_when_delivery_id_is_missing() -> None:
    class FakeWorkflow:
        def handle_webhook(
            self,
            event_name: str,
            signature: str,
            raw_body: bytes,
            payload: dict,
            delivery_id: str,
        ) -> None:
            raise AssertionError("Workflow should not be called when delivery id is missing")

    app.dependency_overrides[get_github_webhook_workflow_service] = lambda: FakeWorkflow()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/webhooks/github",
            headers={"X-GitHub-Event": "pull_request"},
            json={"action": "opened"},
        )

        assert response.status_code == 422
        assert response.json() == {"detail": "Missing GitHub webhook delivery id"}
    finally:
        app.dependency_overrides.clear()


def test_github_webhook_translates_workflow_errors() -> None:
    class SignatureWorkflow:
        def handle_webhook(self, **kwargs: object) -> None:
            raise InvalidWebhookSignatureError("Invalid GitHub webhook signature")

    class PayloadWorkflow:
        def handle_webhook(self, **kwargs: object) -> None:
            raise InvalidWebhookPayloadError("Missing or invalid GitHub webhook field: number")

    class DispatchWorkflow:
        def handle_webhook(self, **kwargs: object) -> None:
            raise TaskDispatchError("Failed to dispatch pull request analysis for record 1")

    client = TestClient(app)

    try:
        app.dependency_overrides[get_github_webhook_workflow_service] = lambda: SignatureWorkflow()
        signature_response = client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-signature",
            },
            json={"action": "opened"},
        )

        app.dependency_overrides[get_github_webhook_workflow_service] = lambda: PayloadWorkflow()
        payload_response = client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-payload",
            },
            json={"action": "opened"},
        )

        app.dependency_overrides[get_github_webhook_workflow_service] = lambda: DispatchWorkflow()
        dispatch_response = client.post(
            "/api/v1/webhooks/github",
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-dispatch",
            },
            json={"action": "opened"},
        )

        assert signature_response.status_code == 401
        assert payload_response.status_code == 422
        assert dispatch_response.status_code == 503
    finally:
        app.dependency_overrides.clear()
