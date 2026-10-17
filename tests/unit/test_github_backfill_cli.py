
"""Regression tests for Inciflow's historical GitHub issue backfill."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from inciflow.integrations.github import (
    GITHUB_API_BASE_URL,
    GitHubAPIError,
    GitHubClient,
)

OWNER = "octo"
REPOSITORY = "widget"
REPOSITORY_URL = f"{GITHUB_API_BASE_URL}/repos/{OWNER}/{REPOSITORY}"
ISSUES_URL = f"{REPOSITORY_URL}/issues"

PAGE_11_CURSOR = "Y3Vyc29yOnYyOpLPAAABcF52EajOIdabCA=="


def repository_payload() -> dict:
    """Return a minimal valid GitHub repository response."""
    return {
        "id": 12345,
        "name": REPOSITORY,
        "full_name": f"{OWNER}/{REPOSITORY}",
        "owner": {"login": OWNER},
        "default_branch": "main",
        "archived": False,
    }


def issue_payload(number: int = 1) -> dict:
    """Return a minimal valid GitHub issue response."""
    return {
        "id": 90000 + number,
        "number": number,
        "title": f"Test issue {number}",
        "body": "Backfill regression test",
        "state": "open",
        "html_url": (
            f"https://github.com/{OWNER}/{REPOSITORY}/issues/{number}"
        ),
        "user": {"login": "test-user"},
        "labels": [{"name": "bug"}],
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-02T10:00:00Z",
        "closed_at": None,
    }


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_pages: int = 5,
) -> tuple[GitHubClient, httpx.Client]:
    """Create a GitHub client backed by an in-memory HTTP transport."""
    http_client = httpx.Client(
        base_url=GITHUB_API_BASE_URL,
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-token"},
        follow_redirects=False,
    )

    client = GitHubClient(
        http_client=http_client,
        max_pages=max_pages,
    )
    return client, http_client


def json_response(
    request: httpx.Request,
    payload: object,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a JSON response associated with a request."""
    return httpx.Response(
        status_code=200,
        json=payload,
        headers=headers,
        request=request,
    )


def test_first_backfill_batch_advances_checkpoint() -> None:
    """An initial checkpoint fetches page one and advances to page two."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == f"/repos/{OWNER}/{REPOSITORY}":
            return json_response(request, repository_payload())

        assert request.url.path == f"/repos/{OWNER}/{REPOSITORY}/issues"
        assert request.url.params["page"] == "1"

        next_url = (
            f"{ISSUES_URL}?state=all&sort=created&direction=asc"
            f"&per_page=100&page=2&after=next-cursor"
        )
        return json_response(
            request,
            [issue_payload(1)],
            headers={"Link": f'<{next_url}>; rel="next"'},
        )

    client, http_client = make_client(handler)
    try:
        batch = client.fetch_issue_batch(OWNER, REPOSITORY, {})

        assert batch.completed is False
        assert len(batch.issues) == 1
        assert batch.issues[0].issue_number == 1
        assert batch.expected_cursor_payload == {}
        assert batch.cursor_payload == {
            "mode": "backfill",
            "page": 2,
            "after": "next-cursor",
        }
        assert len(requests) == 2
    finally:
        client.close()
        http_client.close()


def test_backfill_resumes_using_existing_cursor() -> None:
    """A saved cursor is reused rather than replaced with page pagination."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == f"/repos/{OWNER}/{REPOSITORY}":
            return json_response(request, repository_payload())

        assert request.url.params["after"] == PAGE_11_CURSOR
        assert "page" not in request.url.params

        return json_response(request, [issue_payload(1004)])

    checkpoint = {
        "mode": "backfill",
        "page": 11,
        "after": PAGE_11_CURSOR,
    }

    client, http_client = make_client(handler)
    try:
        batch = client.fetch_issue_batch(
            OWNER,
            REPOSITORY,
            checkpoint,
        )

        assert batch.expected_cursor_payload == checkpoint
        assert batch.completed is True
        assert batch.cursor_payload == {
            "mode": "backfill",
            "page": 11,
            "completed": True,
        }
        assert [issue.issue_number for issue in batch.issues] == [1004]
        assert len(requests) == 2
    finally:
        client.close()
        http_client.close()


def test_page_11_recovers_cursor_from_page_10() -> None:
    """Page 11 uses the continuation cursor recovered from page 10."""
    requests: list[httpx.Request] = []

    page_10_next_url = (
        f"{ISSUES_URL}?state=all&sort=created&direction=asc"
        f"&per_page=100&page=11"
        f"&after={httpx.QueryParams({'after': PAGE_11_CURSOR})['after']}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == f"/repos/{OWNER}/{REPOSITORY}":
            return json_response(request, repository_payload())

        if request.url.params.get("page") == "10":
            return json_response(
                request,
                [],
                headers={"Link": f'<{page_10_next_url}>; rel="next"'},
            )

        assert request.url.params["after"] == PAGE_11_CURSOR
        assert "page" not in request.url.params

        # No further Link header: this is the final batch.
        return json_response(request, [issue_payload(1004)])

    client, http_client = make_client(handler)
    try:
        batch = client.fetch_issue_batch(
            OWNER,
            REPOSITORY,
            {"mode": "backfill", "page": 11},
        )

        assert batch.completed is True
        assert batch.cursor_payload == {
            "mode": "backfill",
            "page": 11,
            "completed": True,
        }
        assert [issue.issue_number for issue in batch.issues] == [1004]

        issue_requests = [
            request
            for request in requests
            if request.url.path.endswith("/issues")
        ]
        assert len(issue_requests) == 2
        assert issue_requests[0].url.params["page"] == "10"
        assert issue_requests[1].url.params["after"] == PAGE_11_CURSOR
        assert "page" not in issue_requests[1].url.params
    finally:
        client.close()
        http_client.close()


def test_page_11_fails_if_page_10_has_no_next_link() -> None:
    """Recovery must stop instead of guessing a cursor."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/repos/{OWNER}/{REPOSITORY}":
            return json_response(request, repository_payload())

        return json_response(request, [])

    client, http_client = make_client(handler)
    try:
        with pytest.raises(
            GitHubAPIError,
            match="Cannot recover the cursor from page 10",
        ):
            client.fetch_issue_batch(
                OWNER,
                REPOSITORY,
                {"mode": "backfill", "page": 11},
            )
    finally:
        client.close()
        http_client.close()


@pytest.mark.parametrize(
    "checkpoint",
    [
        {"mode": "backfill", "page": 0},
        {"mode": "backfill", "page": -1},
        {"mode": "backfill", "page": True},
        {"mode": "backfill", "page": 1, "completed": False},
        {"mode": "backfill", "page": 1, "after": ""},
        {"mode": "backfill", "page": 1, "unexpected": "value"},
    ],
)
def test_invalid_backfill_checkpoint_is_rejected(
    checkpoint: dict,
) -> None:
    """Malformed or completed checkpoints cannot start a new batch."""
    client, http_client = make_client(
        lambda request: json_response(request, repository_payload())
    )
    try:
        with pytest.raises(
            ValueError,
            match="Invalid or completed backfill checkpoint",
        ):
            client.fetch_issue_batch(OWNER, REPOSITORY, checkpoint)
    finally:
        client.close()
        http_client.close()
