import logging

import httpx

from app.core.config import get_settings
from app.services.exceptions import GitHubPullRequestContentError
from app.services.github_app_auth import GitHubAppAuthService

logger = logging.getLogger(__name__)


class GitHubPullRequestContentService:
    def __init__(
        self,
        client: httpx.Client | None = None,
        app_auth_service: GitHubAppAuthService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.client = client or httpx.Client(timeout=20.0)
        self.app_auth_service = app_auth_service or GitHubAppAuthService()

    def fetch_pull_request_patch_bundle(
        self,
        repo_full_name: str,
        pr_number: int,
        installation_id: int | None = None,
    ) -> str:
        owner, repo = self._parse_repo_full_name(repo_full_name)
        files: list[dict] = []
        page = 1
        auth_mode = (
            "installation"
            if installation_id is not None
            else "token"
            if self.settings.github_token
            else "anonymous"
        )

        logger.info(
            "Fetching GitHub pull request patch bundle repo=%s pr_number=%s auth_mode=%s",
            repo_full_name,
            pr_number,
            auth_mode,
        )

        while True:
            response = self.client.get(
                f"{self.settings.github_api_url}/repos/{owner}/{repo}/pulls/{pr_number}/files",
                headers=self._build_headers(installation_id),
                params={"per_page": 100, "page": page},
            )
            if response.status_code >= 400:
                logger.warning(
                    "GitHub pull request files request failed repo=%s pr_number=%s "
                    "page=%s status_code=%s",
                    repo_full_name,
                    pr_number,
                    page,
                    response.status_code,
                )
                raise GitHubPullRequestContentError(
                    f"Failed to fetch pull request files for {repo_full_name}#{pr_number}: "
                    f"HTTP {response.status_code}"
                )

            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubPullRequestContentError(
                    f"Unexpected GitHub response while fetching pull request files for "
                    f"{repo_full_name}#{pr_number}"
                )

            if not payload:
                break

            files.extend(payload)
            if len(payload) < 100:
                break
            page += 1

        if not files:
            raise GitHubPullRequestContentError(
                f"No pull request files returned for {repo_full_name}#{pr_number}"
            )

        sections: list[str] = []
        for file_info in files:
            filename = file_info.get("filename", "unknown")
            status = file_info.get("status", "modified")
            patch = file_info.get("patch")
            if not isinstance(patch, str) or not patch.strip():
                continue
            sections.append(f"diff --git a/{filename} b/{filename}")
            sections.append(f"# file_status: {status}")
            sections.append(patch)

        if not sections:
            raise GitHubPullRequestContentError(
                f"Pull request {repo_full_name}#{pr_number} did not contain textual patch data"
            )

        logger.info(
            "Fetched GitHub pull request patch bundle repo=%s pr_number=%s "
            "files=%s patch_sections=%s",
            repo_full_name,
            pr_number,
            len(files),
            len(sections) // 3,
        )
        return "\n".join(sections)

    def _build_headers(self, installation_id: int | None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.settings.github_api_version,
        }
        if installation_id is not None:
            headers["Authorization"] = (
                f"Bearer {self.app_auth_service.get_installation_access_token(installation_id)}"
            )
        elif self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    def _parse_repo_full_name(self, repo_full_name: str) -> tuple[str, str]:
        parts = repo_full_name.split("/", maxsplit=1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise GitHubPullRequestContentError(f"Invalid repo_full_name: {repo_full_name}")
        return parts[0], parts[1]
