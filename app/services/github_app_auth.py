import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import get_settings
from app.services.exceptions import GitHubPullRequestContentError


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class GitHubAppAuthService:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self.client = client or httpx.Client(timeout=20.0)
        self._token_cache: dict[int, tuple[str, datetime | None]] = {}

    def get_installation_access_token(self, installation_id: int) -> str:
        cached = self._token_cache.get(installation_id)
        if cached is not None:
            token, expires_at = cached
            if expires_at is None or expires_at > datetime.now(timezone.utc) + timedelta(minutes=1):
                return token

        jwt_token = self._create_app_jwt()
        response = self.client.post(
            f"{self.settings.github_api_url}/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt_token}",
                "X-GitHub-Api-Version": self.settings.github_api_version,
            },
        )
        if response.status_code >= 400:
            raise GitHubPullRequestContentError(
                f"Failed to create installation access token for installation {installation_id}: "
                f"HTTP {response.status_code}"
            )

        payload = response.json()
        token = payload.get("token")
        expires_at_raw = payload.get("expires_at")
        if not isinstance(token, str) or not token:
            raise GitHubPullRequestContentError(
                f"GitHub installation token response did not contain a token for installation {installation_id}"
            )

        expires_at: datetime | None = None
        if isinstance(expires_at_raw, str) and expires_at_raw:
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))

        self._token_cache[installation_id] = (token, expires_at)
        return token

    def _create_app_jwt(self) -> str:
        app_id = self.settings.github_app_id
        private_key_path = self.settings.github_private_key_path
        if not app_id or not private_key_path:
            raise GitHubPullRequestContentError(
                "GitHub App authentication requires github_app_id and github_private_key_path"
            )

        now = datetime.now(timezone.utc)
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": app_id,
        }

        signing_input = (
            f"{_b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
            f"{_b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
        )
        with open(private_key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(key_file.read(), password=None)
        signature = private_key.sign(
            signing_input.encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return f"{signing_input}.{_b64url(signature)}"
