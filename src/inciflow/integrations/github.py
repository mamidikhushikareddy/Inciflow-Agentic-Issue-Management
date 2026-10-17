
"""GitHub API client for repository and issue ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self
from urllib.parse import urlparse

import httpx

from inciflow.ingestion.schemas import (
    GitHubIssueBatch,
    IssueIngest,
    RepositoryIngest,
    SnapshotIngest,
)

GITHUB_API_BASE_URL = "https://api.github.com"
PAGE_SIZE = 100
MAX_ISSUES_PER_SNAPSHOT = 500
DEFAULT_MAX_PAGES = 5
MAX_ALLOWED_PAGES = 5


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API response cannot be processed."""


class GitHubClient:
    """Synchronous, bounded client for GitHub's REST API."""

    API_BASE_URL = GITHUB_API_BASE_URL

    def __init__(
        self,
        token: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if (
            type(max_pages) is not int
            or not 1 <= max_pages <= MAX_ALLOWED_PAGES
        ):
            raise ValueError(
                f"max_pages must be an integer between "
                f"1 and {MAX_ALLOWED_PAGES}."
            )

        self._token = token
        self._max_pages = max_pages
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=GITHUB_API_BASE_URL,
            timeout=30.0,
            follow_redirects=False,
        )
        self._last_response: httpx.Response | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client only when this instance owns it."""
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _repository_path(owner: str, repository: str) -> str:
        """Validate repository path segments before building an endpoint."""
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("GitHub owner must not be empty.")

        if not isinstance(repository, str) or not repository.strip():
            raise ValueError("GitHub repository must not be empty.")

        if (
            "/" in owner
            or "/" in repository
            or "\\" in owner
            or "\\" in repository
            or owner in {".", ".."}
            or repository in {".", ".."}
            or any(ord(char) < 32 for char in owner + repository)
        ):
            raise ValueError("Invalid GitHub owner or repository.")

        return f"/repos/{owner}/{repository}"

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Request JSON while retaining response headers for pagination."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = self._client.get(
                path,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise GitHubAPIError("GitHub API request failed.") from exc

        self._last_response = response

        if response.is_error:
            raise GitHubAPIError(
                f"GitHub API returned HTTP {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise GitHubAPIError("GitHub returned invalid JSON.") from exc

    @staticmethod
    def _next_link(response: httpx.Response | None) -> str | None:
        """Return the next pagination URL only when its destination is trusted."""
        if response is None:
            return None

        next_link = response.links.get("next")
        if not next_link:
            return None

        url = next_link.get("url")
        if not isinstance(url, str):
            raise GitHubAPIError("GitHub returned an invalid pagination link.")

        try:
            parsed = urlparse(url)
            valid_port = parsed.port in (None, 443)
        except ValueError:
            parsed = urlparse("")
            valid_port = False

        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.github.com"
            or parsed.username is not None
            or parsed.password is not None
            or not valid_port
            or not parsed.path.startswith("/")
        ):
            raise GitHubAPIError(
                "GitHub returned a pagination link with an untrusted destination."
            )

        return url

    @staticmethod
    def _validate_repository_payload(payload: Any) -> dict[str, Any]:
        """Validate the required repository fields returned by GitHub."""
        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub returned an invalid repository record.")

        required = ("id", "name", "full_name", "owner")
        if any(key not in payload for key in required):
            raise GitHubAPIError("GitHub repository record is incomplete.")

        if (
            type(payload["id"]) is not int
            or not isinstance(payload["name"], str)
            or not isinstance(payload["full_name"], str)
            or not isinstance(payload["owner"], dict)
            or not isinstance(payload["owner"].get("login"), str)
        ):
            raise GitHubAPIError("GitHub repository record failed validation.")

        return payload

    @staticmethod
    def _normalize_repository(payload: dict[str, Any]) -> RepositoryIngest:
        """Convert GitHub repository metadata into the ingestion schema."""
        try:
            return RepositoryIngest(
                github_repo_id=payload["id"],
                owner=payload["owner"]["login"],
                name=payload["name"],
                full_name=payload["full_name"],
                default_branch=payload.get("default_branch") or "main",
                is_active=not payload.get("archived", False),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubAPIError(
                "GitHub repository record failed validation."
            ) from exc

    def _fetch_repository(
        self,
        owner: str,
        repository: str,
    ) -> RepositoryIngest:
        payload = self._get_json(self._repository_path(owner, repository))
        return self._normalize_repository(
            self._validate_repository_payload(payload)
        )

    def fetch_repository(
        self,
        owner: str,
        repository: str,
    ) -> RepositoryIngest:
        """Fetch and normalize repository metadata."""
        return self._fetch_repository(owner, repository)

    @staticmethod
    def _validate_issue_payload(payload: Any) -> list[dict[str, Any]]:
        """Validate the shape of an issue-list response."""
        if not isinstance(payload, list):
            raise GitHubAPIError("GitHub returned an invalid issue list.")

        if any(not isinstance(item, dict) for item in payload):
            raise GitHubAPIError("GitHub returned an invalid issue record.")

        return payload

    @staticmethod
    def _is_pull_request(item: dict[str, Any]) -> bool:
        """GitHub's issues endpoint also returns pull requests."""
        return "pull_request" in item

    @staticmethod
    def _parse_github_datetime(value: Any) -> datetime:
        """Parse an ISO timestamp and normalize it to UTC."""
        if not isinstance(value, str):
            raise TypeError("GitHub timestamp must be a string.")

        try:
            parsed = datetime.fromisoformat(
                value[:-1] + "+00:00" if value.endswith("Z") else value
            )
        except ValueError as exc:
            raise ValueError("GitHub timestamp is invalid.") from exc

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("GitHub timestamp must be timezone-aware.")

        return parsed.astimezone(UTC)

    @classmethod
    def _normalize_issue(cls, item: dict[str, Any]) -> IssueIngest:
        """Convert a GitHub issue payload into the ingestion schema."""
        user = item.get("user")
        if user is not None and not isinstance(user, dict):
            raise TypeError("GitHub issue user must be an object or null.")

        labels = item.get("labels", [])
        if not isinstance(labels, list):
            raise TypeError("GitHub issue labels must be a list.")

        normalized_labels: list[str] = []
        for label in labels:
            if isinstance(label, str):
                normalized_labels.append(label)
            elif isinstance(label, dict) and isinstance(label.get("name"), str):
                normalized_labels.append(label["name"])
            else:
                raise TypeError("GitHub issue contains an invalid label.")

        number = item.get("number")
        github_issue_id = item.get("id")
        title = item.get("title")
        state = item.get("state")

        if (
            type(number) is not int
            or type(github_issue_id) is not int
            or not isinstance(title, str)
            or not isinstance(state, str)
        ):
            raise ValueError("GitHub issue is missing required fields.")

        return IssueIngest(
            github_issue_id=github_issue_id,
            issue_number=number,
            title=title,
            body=item.get("body"),
            state=state,
            author_login=user.get("login") if user else None,
            labels=normalized_labels,
            created_at_github=cls._parse_github_datetime(
                item.get("created_at")
            ),
            updated_at_github=cls._parse_github_datetime(
                item.get("updated_at")
            ),
            closed_at_github=(
                cls._parse_github_datetime(item["closed_at"])
                if item.get("closed_at") is not None
                else None
            ),
        )

    @staticmethod
    def _validate_backfill_checkpoint(
        checkpoint: dict[str, Any],
    ) -> int:
        """Validate an incomplete historical-backfill checkpoint."""
        if not isinstance(checkpoint, dict):
            raise TypeError("Invalid or completed backfill checkpoint.")

        if checkpoint == {}:
            return 1

        if (
            set(checkpoint)
            not in (
                {"mode", "page"},
                {"mode", "page", "after"},
            )
            or checkpoint.get("mode") != "backfill"
            or type(checkpoint.get("page")) is not int
            or checkpoint["page"] < 1
            or (
                "after" in checkpoint
                and (
                    not isinstance(checkpoint["after"], str)
                    or not checkpoint["after"]
                )
            )
        ):
            raise ValueError("Invalid or completed backfill checkpoint.")

        return checkpoint["page"]

    @staticmethod
    def _cursor_from_url(url: str) -> str:
        """Extract a usable continuation cursor from a trusted URL."""
        cursor = httpx.URL(url).params.get("after")
        if not cursor:
            raise GitHubAPIError(
                "GitHub did not provide a usable continuation cursor."
            )
        return cursor

    def fetch_issue_batch(
        self,
        owner: str,
        repository: str,
        expected_cursor_payload: dict[str, Any],
    ) -> GitHubIssueBatch:
        """Fetch one historical batch and calculate its next checkpoint."""
        page = self._validate_backfill_checkpoint(expected_cursor_payload)
        repository_path = self._repository_path(owner, repository)
        repository_data = self._fetch_repository(owner, repository)

        params: dict[str, Any] = {
            "state": "all",
            "sort": "created",
            "direction": "asc",
            "per_page": PAGE_SIZE,
        }

        if "after" in expected_cursor_payload:
            params["after"] = expected_cursor_payload["after"]
        elif page == 11:
            # Recover the continuation cursor from the last supported page.
            self._get_json(
                f"{repository_path}/issues",
                params={**params, "page": 10},
            )
            previous_url = self._next_link(self._last_response)

            if previous_url is None:
                raise GitHubAPIError("Cannot recover the cursor from page 10.")

            params["after"] = self._cursor_from_url(previous_url)
        else:
            params["page"] = page

        payload = self._get_json(
            f"{repository_path}/issues",
            params=params,
        )
        response = self._last_response

        issues: list[IssueIngest] = []
        for item in self._validate_issue_payload(payload):
            if self._is_pull_request(item):
                continue

            try:
                issues.append(self._normalize_issue(item))
            except (KeyError, TypeError, ValueError) as exc:
                raise GitHubAPIError(
                    "A GitHub issue record failed validation."
                ) from exc

            if len(issues) > MAX_ISSUES_PER_SNAPSHOT:
                raise GitHubAPIError(
                    "The batch exceeds the configured issue limit."
                )

        next_url = self._next_link(response)
        completed = next_url is None

        if completed:
            cursor_payload = {
                "mode": "backfill",
                "page": page,
                "completed": True,
            }
        else:
            cursor_payload = {
                "mode": "backfill",
                "page": page + 1,
                "after": self._cursor_from_url(next_url),
            }

        return GitHubIssueBatch(
            repository=repository_data,
            issues=issues,
            expected_cursor_payload=expected_cursor_payload,
            cursor_payload=cursor_payload,
            completed=completed,
        )

    def fetch_updated_issue_batch(
        self,
        owner: str,
        repository: str,
        *,
        since: datetime,
        watermark: datetime,
    ) -> GitHubIssueBatch:
        """Fetch bounded, incrementally updated issues through Link pagination."""
        for field_name, value in (("since", since), ("watermark", watermark)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware.")

        if watermark < since:
            raise ValueError("watermark must not be earlier than since.")

        repository_data = self._fetch_repository(owner, repository)
        params: dict[str, Any] = {
            "state": "all",
            "sort": "updated",
            "direction": "asc",
            "per_page": PAGE_SIZE,
            "since": since.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "page": 1,
        }

        issues: list[IssueIngest] = []
        next_path: str | None = (
            f"{self._repository_path(owner, repository)}/issues"
        )
        next_params: dict[str, Any] | None = params
        page_count = 0

        while next_path is not None:
            if page_count >= self._max_pages:
                raise GitHubAPIError("GitHub pagination limit reached.")

            payload = self._get_json(next_path, params=next_params)
            response = self._last_response
            page_count += 1

            for item in self._validate_issue_payload(payload):
                if self._is_pull_request(item):
                    continue

                try:
                    issues.append(self._normalize_issue(item))
                except (KeyError, TypeError, ValueError) as exc:
                    raise GitHubAPIError(
                        "A GitHub issue record failed validation."
                    ) from exc

                if len(issues) > MAX_ISSUES_PER_SNAPSHOT:
                    raise GitHubAPIError(
                        "The batch exceeds the configured issue limit."
                    )

            next_url = self._next_link(response)
            if next_url is not None and page_count >= self._max_pages:
                raise GitHubAPIError("GitHub pagination limit reached.")

            next_path = next_url
            next_params = None

        return GitHubIssueBatch(
            repository=repository_data,
            issues=issues,
            expected_cursor_payload={},
            cursor_payload={},
            completed=True,
            watermark=watermark,
        )

    def fetch_snapshot(
        self,
        owner: str,
        repository: str,
        *,
        max_issues: int = MAX_ISSUES_PER_SNAPSHOT,
    ) -> SnapshotIngest:
        """Fetch a bounded repository issue snapshot."""
        if type(max_issues) is not int or max_issues < 1:
            raise ValueError("max_issues must be a positive integer.")

        repository_data = self._fetch_repository(owner, repository)
        issues: list[IssueIngest] = []

        next_path: str | None = (
            f"{self._repository_path(owner, repository)}/issues"
        )
        next_params: dict[str, Any] | None = {
            "state": "all",
            "sort": "created",
            "direction": "asc",
            "per_page": PAGE_SIZE,
            "page": 1,
        }
        page_count = 0

        while next_path is not None:
            if page_count >= self._max_pages:
                raise GitHubAPIError("GitHub pagination limit reached.")

            payload = self._get_json(next_path, params=next_params)
            response = self._last_response
            page_count += 1

            for item in self._validate_issue_payload(payload):
                if self._is_pull_request(item):
                    continue

                try:
                    issues.append(self._normalize_issue(item))
                except (KeyError, TypeError, ValueError) as exc:
                    raise GitHubAPIError(
                        "A GitHub issue record failed validation."
                    ) from exc

                if len(issues) > max_issues:
                    raise GitHubAPIError(
                        "The snapshot exceeds the configured issue limit."
                    )

            next_url = self._next_link(response)
            if next_url is not None and page_count >= self._max_pages:
                raise GitHubAPIError("GitHub pagination limit reached.")

            next_path = next_url
            next_params = None

        return SnapshotIngest(
            repository=repository_data,
            issues=issues,
        )
