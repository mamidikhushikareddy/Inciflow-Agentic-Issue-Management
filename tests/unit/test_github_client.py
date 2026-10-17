
"""Mocked contract and safety tests for the GitHub REST client."""

import httpx
import pytest

from inciflow.integrations.github import (
    GITHUB_API_BASE_URL,
    GitHubAPIError,
    GitHubClient,
)


def repository_payload():
    """Build a representative GitHub repository response."""
    return {
        "id": 12345,
        "name": "widget",
        "full_name": "octo/widget",
        "default_branch": "main",
        "archived": False,
        "disabled": False,
        "owner": {"login": "octo"},
    }


def issue_payload(number: int):
    """Build a representative GitHub issue response."""
    return {
        "id": 90000 + number,
        "number": number,
        "title": f"Issue {number}",
        "body": "Test body",
        "state": "open",
        "user": {"login": "octo-user"},
        "labels": [{"name": "bug"}],
        "created_at": "2026-01-01T10:00:00Z",
        "updated_at": "2026-01-02T10:00:00Z",
        "closed_at": None,
    }


def make_client(handler, *, max_pages=5):
    """Build a client backed by an in-memory HTTP transport."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        base_url=GITHUB_API_BASE_URL,
        transport=transport,
        headers={"Authorization": "Bearer test-token"},
        follow_redirects=False,
    )
    return GitHubClient(http_client=http_client, max_pages=max_pages), http_client


def repository_response(request: httpx.Request):
    """Build a repository response tied to its request."""
    return httpx.Response(200, json=repository_payload(), request=request)


def test_normalizes_repository_and_excludes_pull_requests():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[
                issue_payload(1),
                {
                    **issue_payload(2),
                    "pull_request": {
                        "url": "https://api.github.com/repos/octo/widget/pulls/2"
                    },
                },
            ],
            request=request,
        )

    client, http_client = make_client(handler)
    with http_client, client:
        snapshot = client.fetch_snapshot("octo", "widget")

    assert snapshot.repository.github_repo_id == 12345
    assert snapshot.repository.full_name == "octo/widget"
    assert snapshot.repository.is_active is True
    assert len(snapshot.issues) == 1
    assert snapshot.issues[0].issue_number == 1
    assert snapshot.issues[0].labels == ["bug"]
    assert snapshot.issues[0].author_login == "octo-user"
    assert requests[1].url.params["state"] == "all"
    assert requests[1].url.params["per_page"] == "100"


def test_follows_link_header_to_fetch_second_page():
    requested_pages = []

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        page = int(request.url.params["page"])
        requested_pages.append(page)

        if page == 1:
            return httpx.Response(
                200,
                json=[issue_payload(number) for number in range(1, 101)],
                headers={
                    "Link": (
                        "<https://api.github.com/repos/octo/widget/issues"
                        "?state=all&per_page=100&page=2&sort=created"
                        '&direction=asc>; rel="next"'
                    )
                },
                request=request,
            )

        return httpx.Response(
            200,
            json=[issue_payload(101)],
            request=request,
        )

    client, http_client = make_client(handler)
    with http_client, client:
        snapshot = client.fetch_snapshot("octo", "widget", max_issues=101)

    assert requested_pages == [1, 2]
    assert len(snapshot.issues) == 101
    assert snapshot.issues[-1].issue_number == 101


def test_refuses_to_return_snapshot_when_page_limit_is_reached():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(1)],
            headers={
                "Link": (
                    '<https://api.github.com/repos/octo/widget/issues?page=2>; '
                    'rel="next"'
                )
            },
            request=request,
        )

    client, http_client = make_client(handler, max_pages=1)
    with http_client, client, pytest.raises(
        GitHubAPIError, match="pagination limit"
    ):
        client.fetch_snapshot("octo", "widget", max_issues=101)


def test_rejects_issue_count_over_configured_snapshot_limit():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(1), issue_payload(2), issue_payload(3)],
            request=request,
        )

    client, http_client = make_client(handler)
    with http_client, client, pytest.raises(
        GitHubAPIError, match="exceeds the configured issue limit"
    ):
        client.fetch_snapshot("octo", "widget", max_issues=2)


def test_api_error_does_not_expose_authorization_token():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return httpx.Response(
                401,
                json={"message": "Bad credentials"},
                request=request,
            )

        raise AssertionError(
            "Issues endpoint must not be called after repository failure."
        )

    client, http_client = make_client(handler)
    with http_client, client, pytest.raises(GitHubAPIError) as error:
        client.fetch_snapshot("octo", "widget")

    assert "401" in str(error.value)
    assert "test-token" not in str(error.value)
    assert "Bad credentials" not in str(error.value)


def test_invalid_json_is_reported_as_safe_api_error():
    def handler(request):
        return httpx.Response(
            200,
            content=b"not-json",
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client, http_client = make_client(handler)
    with http_client, client, pytest.raises(
        GitHubAPIError, match="invalid JSON"
    ):
        client.fetch_snapshot("octo", "widget")


def test_rejects_empty_owner_and_invalid_page_limit():
    def handler(request):
        raise AssertionError("Invalid input must fail before making requests.")

    client, http_client = make_client(handler)
    with http_client, client, pytest.raises(
        ValueError, match="must not be empty"
    ):
        client.fetch_snapshot("", "widget")

    with pytest.raises(ValueError, match="max_pages"):
        GitHubClient(
            http_client=httpx.Client(base_url=GITHUB_API_BASE_URL),
            max_pages=6,
        )




def test_fetch_issue_batch_returns_next_page_checkpoint():
    after_cursor = "Y3Vyc29yOnYyOpLPAAABcF52EajOIdabCA=="

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        assert request.url.params["page"] == "1"
        return httpx.Response(
            200,
            json=[issue_payload(1), issue_payload(2)],
            headers={
                "Link": (
                    '<https://api.github.com/repos/octo/widget/issues'
                    '?state=all&per_page=100&sort=created&direction=asc'
                    f'&after={httpx.QueryParams({"after": after_cursor})["after"]}>'
                    '; rel="next"'
                )
            },
            request=request,
        )

    client, http_client = make_client(handler)
    with http_client, client:
        batch = client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={},
        )

    assert batch.expected_cursor_payload == {}
    assert batch.cursor_payload == {
        "mode": "backfill",
        "page": 2,
        "after": after_cursor,
    }
    assert batch.completed is False
    assert len(batch.issues) == 2

def test_fetch_issue_batch_resumes_and_marks_final_page_complete():
    requested_pages = []

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        page = int(request.url.params["page"])
        requested_pages.append(page)

        if page != 2:
            raise AssertionError(f"Expected page 2, received page {page}.")

        return httpx.Response(
            200,
            json=[issue_payload(101)],
            request=request,
        )

    client, http_client = make_client(handler)
    with http_client, client:
        batch = client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={"mode": "backfill", "page": 2},
        )

    assert requested_pages == [2]
    assert [issue.issue_number for issue in batch.issues] == [101]
    assert batch.expected_cursor_payload == {"mode": "backfill", "page": 2}
    assert batch.cursor_payload == {
        "mode": "backfill",
        "page": 2,
        "completed": True,
    }
    assert batch.completed is True


@pytest.mark.parametrize(
    "checkpoint",
    [
        {"mode": "unknown", "page": 1},
        {"mode": "backfill", "page": 0},
        {"mode": "backfill", "page": True},
        {"mode": "backfill", "page": 1.5},
        {"mode": "backfill", "page": 1, "completed": True},
        {"mode": "backfill", "page": 1, "unexpected": "value"},
        {"mode": "backfill", "page": 1, "completed": False},
        {"mode": "backfill", "page": 1, "completed": "false"},
    ],
)
def test_fetch_issue_batch_rejects_invalid_checkpoint(checkpoint):
    def handler(request):
        raise AssertionError("Invalid checkpoint must fail before API requests.")

    client, http_client = make_client(handler)
    with http_client, client, pytest.raises(
        ValueError, match="Invalid or completed backfill checkpoint"
    ):
        client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload=checkpoint,
        )

@pytest.mark.parametrize(
    "untrusted_url",
    [
        "https://attacker.example/steal",
        "http://api.github.com/repos/octo/widget/issues?page=2",
        "https://api.github.com.attacker.example/repos/octo/widget/issues?page=2",
        "https://user:password@api.github.com/repos/octo/widget/issues?page=2",
        "https://api.github.com:8443/repos/octo/widget/issues?page=2",
    ],
)
def test_snapshot_rejects_untrusted_pagination_url(untrusted_url):
    requests = []

    def handler(request):
        requests.append(request)

        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(1)],
            headers={"Link": f'<{untrusted_url}>; rel="next"'},
            request=request,
        )

    client, http_client = make_client(handler)

    with (
        http_client,
        client,
        pytest.raises(GitHubAPIError, match="untrusted destination"),
    ):
        client.fetch_snapshot("octo", "widget", max_issues=101)

    # Only the repository request and the first issues page are allowed.
    assert len(requests) == 2
    assert all(request.url.host == "api.github.com" for request in requests)


@pytest.mark.parametrize(
    "untrusted_url",
    [
        "https://attacker.example/steal",
        "http://api.github.com/repos/octo/widget/issues?page=2",
        "https://api.github.com.attacker.example/repos/octo/widget/issues?page=2",
        "https://user:password@api.github.com/repos/octo/widget/issues?page=2",
        "https://api.github.com:8443/repos/octo/widget/issues?page=2",
    ],
)
def test_issue_batch_rejects_untrusted_pagination_url(untrusted_url):
    requests = []

    def handler(request):
        requests.append(request)

        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(1)],
            headers={"Link": f'<{untrusted_url}>; rel="next"'},
            request=request,
        )

    client, http_client = make_client(handler)

    with (
        http_client,
        client,
        pytest.raises(GitHubAPIError, match="untrusted destination"),
    ):
        client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={},
        )

    # The untrusted next-page URL must never be requested.
    assert len(requests) == 2
    assert all(request.url.host == "api.github.com" for request in requests)

from datetime import UTC, datetime


def test_fetch_updated_issue_batch_uses_since_and_updated_sort():
    requested = []

    def handler(request):
        requested.append(request)
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(1)],
            request=request,
        )

    client, http_client = make_client(handler)

    since = datetime(2026, 10, 15, 14, 58, tzinfo=UTC)
    watermark = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)

    with http_client, client:
        batch = client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=since,
            watermark=watermark,
        )

    issues_request = requested[1]
    assert issues_request.url.params["since"] == since.isoformat().replace(
        "+00:00", "Z"
    )
    assert issues_request.url.params["sort"] == "updated"
    assert issues_request.url.params["direction"] == "asc"
    assert issues_request.url.params["per_page"] == "100"
    assert [issue.issue_number for issue in batch.issues] == [1]
    assert batch.watermark == watermark
    assert batch.completed is True


def test_fetch_updated_issue_batch_follows_trusted_pagination():
    requested_pages = []

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        page = int(request.url.params["page"])
        requested_pages.append(page)

        if page == 1:
            return httpx.Response(
                200,
                json=[issue_payload(1)],
                headers={
                    "Link": (
                        "<https://api.github.com/repos/octo/widget/issues"
                        "?since=2026-10-15T14%3A58%3A00Z&sort=updated"
                        "&direction=asc&per_page=100&page=2>; rel=\"next\""
                    )
                },
                request=request,
            )

        return httpx.Response(
            200,
            json=[issue_payload(2)],
            request=request,
        )

    client, http_client = make_client(handler)

    with http_client, client:
        batch = client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=datetime(2026, 10, 15, 14, 58, tzinfo=UTC),
            watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
        )

    assert requested_pages == [1, 2]
    assert [issue.issue_number for issue in batch.issues] == [1, 2]
    assert batch.completed is True


def test_fetch_updated_issue_batch_rejects_page_limit_without_partial_batch():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(1)],
            headers={
                "Link": (
                    '<https://api.github.com/repos/octo/widget/issues?page=2>; '
                    'rel="next"'
                )
            },
            request=request,
        )

    client, http_client = make_client(handler, max_pages=1)

    with (
        http_client,
        client,
        pytest.raises(GitHubAPIError, match="pagination limit"),
    ):
        client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=datetime(2026, 10, 15, 14, 58, tzinfo=UTC),
            watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
        )

def test_fetch_issue_batch_recovers_cursor_for_page_11():
    after_cursor = "Y3Vyc29yOnYyOpLPAAABcF52EajOIdabCA=="
    requested_issue_params = []

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        params = request.url.params
        requested_issue_params.append(dict(params))

        if params.get("page") == "10":
            return httpx.Response(
                200,
                json=[issue_payload(1000)],
                headers={
                    "Link": (
                        "https://api.github.com/repos/octo/widget/issues"
                        "?state=all&per_page=100&sort=created&direction=asc"
                        f"&after={httpx.QueryParams({'after': after_cursor})['after']}"
                        '; rel="next"'
                    )
                },
                request=request,
            )

        assert params.get("after") == after_cursor
        assert "page" not in params

        return httpx.Response(
            200,
            json=[issue_payload(1001)],
            request=request,
        )

    client, http_client = make_client(handler)

    with http_client, client:
        batch = client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={"mode": "backfill", "page": 11},
        )

    assert [params.get("page") for params in requested_issue_params] == [
        "10",
        None,
    ]
    assert [issue.issue_number for issue in batch.issues] == [1001]
    assert batch.expected_cursor_payload == {"mode": "backfill", "page": 11}
    assert batch.completed is True

# Additional edge-case tests for GitHub client safety and validation.

def test_transport_error_is_wrapped_without_exposing_details():
    def handler(request):
        raise httpx.ConnectError(
            "connection failed with sensitive details",
            request=request,
        )

    client, http_client = make_client(handler)

    with (
        http_client,
        client,
        pytest.raises(GitHubAPIError, match="GitHub API request failed") as error,
    ):
        client.fetch_repository("octo", "widget")

    assert "sensitive details" not in str(error.value)


def test_closing_client_does_not_close_injected_http_client():
    def handler(request):
        return repository_response(request)

    client, http_client = make_client(handler)

    client.close()

    assert not http_client.is_closed

    # The injected client remains usable after the wrapper is closed.
    response = http_client.get("/repos/octo/widget")
    assert response.status_code == 200

    http_client.close()


@pytest.mark.parametrize(
    ("owner", "repository"),
    [
        ("octo/other", "widget"),
        ("octo", "widget/issues"),
        ("octo\\other", "widget"),
        ("octo", "widget\\issues"),
        ("..", "widget"),
        ("octo", "."),
        ("octo\nother", "widget"),
    ],
)
def test_repository_path_rejects_invalid_segments(owner, repository):
    with pytest.raises(ValueError, match="Invalid GitHub owner or repository"):
        GitHubClient._repository_path(owner, repository)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        "not-an-issue-list",
        [None],
        ["not-an-issue"],
    ],
)
def test_issue_payload_validation_rejects_invalid_shapes(payload):
    with pytest.raises(GitHubAPIError, match="invalid issue"):
        GitHubClient._validate_issue_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("number", True),
        ("id", "123"),
        ("title", None),
        ("state", 123),
        ("user", "not-a-user-object"),
        ("labels", "bug"),
        ("labels", [None]),
        ("labels", [{"name": 123}]),
        ("created_at", "not-a-timestamp"),
        ("created_at", "2026-01-01T10:00:00"),
        ("updated_at", "2026-01-02T10:00:00"),
        ("closed_at", "not-a-timestamp"),
    ],
)
def test_issue_normalization_rejects_malformed_fields(field, value):
    payload = issue_payload(1)
    payload[field] = value

    with pytest.raises((TypeError, ValueError)):
        GitHubClient._normalize_issue(payload)


def test_incremental_fetch_rejects_naive_since_timestamp():
    from datetime import UTC, datetime

    client, http_client = make_client(
        lambda request: (_ for _ in ()).throw(
            AssertionError("Invalid timestamps must fail before HTTP requests.")
        )
    )

    with (
        http_client,
        client,
        pytest.raises(ValueError, match="since must be timezone-aware"),
    ):
        client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=datetime(2026, 10, 15, 14, 58),
            watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
        )


def test_incremental_fetch_rejects_watermark_before_since():
    from datetime import UTC, datetime

    client, http_client = make_client(
        lambda request: (_ for _ in ()).throw(
            AssertionError("Invalid time bounds must fail before HTTP requests.")
        )
    )

    with (
        http_client,
        client,
        pytest.raises(ValueError, match="watermark must not be earlier than since"),
    ):
        client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            watermark=datetime(2026, 10, 15, 14, 58, tzinfo=UTC),
        )


def test_closing_client_closes_owned_http_client():
    client = GitHubClient()
    http_client = client._client

    assert not http_client.is_closed

    client.close()

    assert http_client.is_closed


def test_client_adds_bearer_token_to_request():
    authorization_headers = []

    def handler(request):
        authorization_headers.append(request.headers.get("Authorization"))
        return repository_response(request)

    http_client = httpx.Client(
        base_url=GITHUB_API_BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    client = GitHubClient(
        token="coverage-test-token",
        http_client=http_client,
    )

    try:
        client._fetch_repository("octo", "widget")
        assert authorization_headers == ["Bearer coverage-test-token"]
    finally:
        client.close()
        http_client.close()


@pytest.mark.parametrize("payload", [None, [], "invalid"])
def test_repository_validation_rejects_non_dictionary_payload(payload):
    with pytest.raises(
        GitHubAPIError,
        match="invalid repository record",
    ):
        GitHubClient._validate_repository_payload(payload)


def test_repository_validation_rejects_missing_required_field():
    payload = repository_payload()
    del payload["owner"]

    with pytest.raises(
        GitHubAPIError,
        match="incomplete",
    ):
        GitHubClient._validate_repository_payload(payload)


def test_repository_validation_rejects_invalid_field_types():
    payload = repository_payload()
    payload["id"] = True

    with pytest.raises(
        GitHubAPIError,
        match="failed validation",
    ):
        GitHubClient._validate_repository_payload(payload)


def test_repository_normalization_wraps_missing_fields():
    payload = {
        "id": 12345,
        "owner": {},
        "name": "widget",
        "full_name": "octo/widget",
    }

    with pytest.raises(
        GitHubAPIError,
        match="failed validation",
    ) as error:
        GitHubClient._normalize_repository(payload)

    assert isinstance(error.value.__cause__, KeyError)

def test_next_link_returns_none_without_response():
    assert GitHubClient._next_link(None) is None


def test_next_link_rejects_malformed_port():
    response = httpx.Response(
        200,
        headers={
            "Link": (
                '<https://api.github.com:invalid/repos/octo/widget/issues?page=2>'
                '; rel="next"'
            )
        },
    )

    with pytest.raises(GitHubAPIError, match="untrusted destination"):
        GitHubClient._next_link(response)


def test_github_datetime_rejects_non_string_value():
    with pytest.raises(TypeError, match="timestamp must be a string"):
        GitHubClient._parse_github_datetime(None)


def test_issue_normalization_preserves_string_labels():
    payload = issue_payload(1)
    payload["labels"] = ["bug", "good first issue"]

    issue = GitHubClient._normalize_issue(payload)

    assert issue.labels == ["bug", "good first issue"]


@pytest.mark.parametrize(
    ("owner", "repository"),
    [
        ("", "widget"),
        ("   ", "widget"),
        ("octo", ""),
        ("octo", "   "),
        (None, "widget"),
        ("octo", None),
    ],
)
def test_repository_path_rejects_empty_or_non_string_segments(
    owner, repository
):
    with pytest.raises(ValueError):
        GitHubClient._repository_path(owner, repository)


def test_backfill_checkpoint_rejects_non_dictionary():
    with pytest.raises(
        TypeError,
        match="Invalid or completed backfill checkpoint",
    ):
        GitHubClient._validate_backfill_checkpoint(None)


def test_cursor_from_url_rejects_missing_after_parameter():
    url = "https://api.github.com/repos/octo/widget/issues?page=2"

    with pytest.raises(
        GitHubAPIError,
        match="usable continuation cursor",
    ):
        GitHubClient._cursor_from_url(url)


def test_fetch_issue_batch_excludes_pull_requests():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[
                issue_payload(1),
                {
                    **issue_payload(2),
                    "pull_request": {
                        "url": "https://api.github.com/repos/octo/widget/pulls/2"
                    },
                },
            ],
            request=request,
        )

    client, http_client = make_client(handler)

    with http_client, client:
        batch = client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={},
        )

    assert [issue.issue_number for issue in batch.issues] == [1]


def test_fetch_issue_batch_wraps_malformed_issue():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        malformed = issue_payload(1)
        malformed["labels"] = "not-a-list"

        return httpx.Response(
            200,
            json=[malformed],
            request=request,
        )

    client, http_client = make_client(handler)

    with http_client, client, pytest.raises(
        GitHubAPIError,
        match="issue record failed validation",
    ) as error:
        client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={},
        )

    assert isinstance(error.value.__cause__, TypeError)


@pytest.mark.parametrize("max_issues", [0, -1, True, False, 1.5, "10", None])
def test_fetch_snapshot_rejects_invalid_max_issues_before_request(max_issues):
    def handler(request):
        raise AssertionError("Invalid max_issues must fail before any API request.")

    client, http_client = make_client(handler)

    with http_client, client, pytest.raises(
        ValueError,
        match="max_issues must be a positive integer",
    ):
        client.fetch_snapshot("octo", "widget", max_issues=max_issues)


def test_fetch_updated_issue_batch_excludes_pull_requests():
    since = datetime(2026, 10, 15, 14, 58, tzinfo=UTC)
    watermark = datetime(2026, 10, 16, 14, 58, tzinfo=UTC)

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[
                issue_payload(1),
                {
                    **issue_payload(2),
                    "pull_request": {
                        "url": "https://api.github.com/repos/octo/widget/pulls/2"
                    },
                },
            ],
            request=request,
        )

    client, http_client = make_client(handler)

    with http_client, client:
        batch = client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=since,
            watermark=watermark,
        )

    assert [issue.issue_number for issue in batch.issues] == [1]


def test_fetch_updated_issue_batch_wraps_malformed_issue():
    since = datetime(2026, 10, 15, 14, 58, tzinfo=UTC)
    watermark = datetime(2026, 10, 16, 14, 58, tzinfo=UTC)

    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        malformed = issue_payload(1)
        malformed["labels"] = "not-a-list"

        return httpx.Response(
            200,
            json=[malformed],
            request=request,
        )

    client, http_client = make_client(handler)

    with http_client, client, pytest.raises(
        GitHubAPIError,
        match="issue record failed validation",
    ) as error:
        client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=since,
            watermark=watermark,
        )

    assert isinstance(error.value.__cause__, TypeError)


def test_next_link_rejects_non_string_url():
    class FakeResponse:
        links = {"next": {"url": None}}

    with pytest.raises(GitHubAPIError, match="invalid pagination link"):
        GitHubClient._next_link(FakeResponse())


def test_fetch_issue_batch_rejects_issue_count_over_limit():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(number) for number in range(1, 502)],
            request=request,
        )

    client, http_client = make_client(handler)

    with (
        http_client,
        client,
        pytest.raises(GitHubAPIError, match="exceeds the configured issue limit"),
    ):
        client.fetch_issue_batch(
            "octo",
            "widget",
            expected_cursor_payload={"mode": "backfill", "page": 1},
        )


def test_fetch_updated_issue_batch_rejects_issue_count_over_limit():
    def handler(request):
        if request.url.path == "/repos/octo/widget":
            return repository_response(request)

        return httpx.Response(
            200,
            json=[issue_payload(number) for number in range(1, 502)],
            request=request,
        )

    client, http_client = make_client(handler)

    with (
        http_client,
        client,
        pytest.raises(GitHubAPIError, match="exceeds the configured issue limit"),
    ):
        client.fetch_updated_issue_batch(
            "octo",
            "widget",
            since=datetime(2026, 10, 15, 14, 58, tzinfo=UTC),
            watermark=datetime(2026, 10, 16, 14, 58, tzinfo=UTC),
        )
