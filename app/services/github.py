import hashlib
import hmac
from typing import Any

from app.core.config import get_settings
from app.schemas.pull_request import PullRequestAnalyzeRequest
from app.services.exceptions import InvalidWebhookPayloadError, InvalidWebhookSignatureError
from app.services.pr_analysis import WEBHOOK_DIFF_PLACEHOLDER


class GitHubWebhookService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def handle_event(
        self, event_name: str, signature: str, raw_body: bytes, payload: dict
    ) -> PullRequestAnalyzeRequest | None:
        if event_name != "pull_request":
            return None

        self._verify_signature(signature, raw_body)

        action = payload.get("action", "")
        if action not in {"opened", "synchronize", "reopened"}:
            return None

        pr = self._require_mapping(payload, "pull_request")
        repo = self._require_mapping(payload, "repository")
        user = self._require_mapping(pr, "user")
        installation = self._require_mapping(payload, "installation")

        return PullRequestAnalyzeRequest(
            repo_full_name=self._require_str(repo, "full_name"),
            pr_number=self._require_int(payload, "number"),
            title=self._require_str(pr, "title"),
            author=self._require_str(user, "login"),
            installation_id=self._require_int(installation, "id"),
            # GitHub webhook payload does not include a unified diff body.
            # Keep the placeholder semantically honest until a GitHub diff fetch
            # is introduced in a later integration step.
            diff_text=WEBHOOK_DIFF_PLACEHOLDER,
        )

    def _verify_signature(self, signature: str, raw_body: bytes) -> None:
        secret = self.settings.github_webhook_secret
        if not secret:
            return

        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidWebhookSignatureError("Invalid GitHub webhook signature")

    def _require_mapping(self, payload: dict[str, Any], field: str) -> dict[str, Any]:
        value = payload.get(field)
        if not isinstance(value, dict):
            raise InvalidWebhookPayloadError(f"Missing or invalid GitHub webhook field: {field}")
        return value

    def _require_str(self, payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise InvalidWebhookPayloadError(f"Missing or invalid GitHub webhook field: {field}")
        return value

    def _require_int(self, payload: dict[str, Any], field: str) -> int:
        value = payload.get(field)
        if not isinstance(value, int):
            raise InvalidWebhookPayloadError(f"Missing or invalid GitHub webhook field: {field}")
        return value
