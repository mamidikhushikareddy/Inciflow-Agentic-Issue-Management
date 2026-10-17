
"""Tests for the explicit recurring GitHub synchronization CLI."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from inciflow.cli import sync_github


def test_missing_repository_configuration_exits_without_resources(capsys):
    with (
        patch.object(sync_github, "build_parser") as build_parser,
        patch.object(sync_github, "get_session_factory") as factory,
        patch.object(sync_github, "GitHubClient") as client,
    ):
        build_parser.return_value.parse_args.return_value = SimpleNamespace(
            owner=None,
            repository=None,
        )

        exit_code = sync_github.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Configuration error" in captured.err
    factory.assert_not_called()
    client.assert_not_called()


def test_successful_sync_reports_result_and_closes_resources(caplog):
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    result = SimpleNamespace(
        completed=True,
        repository_id="repository-123",
        issue_count=4,
        persisted_at=datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
    )
    github_client = MagicMock()
    github_context = MagicMock()
    github_context.__enter__.return_value = github_client

    with (
        patch.object(
            sync_github,
            "get_session_factory",
            return_value=session_factory,
        ),
        patch.object(
            sync_github,
            "GitHubClient",
            return_value=github_context,
        ),
        patch.object(
            sync_github,
            "sync_updated_github_issues",
            return_value=result,
        ) as sync,
        caplog.at_level("INFO", logger="inciflow.github_sync"),
    ):
        exit_code = sync_github.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 0
    sync.assert_called_once()
    assert sync.call_args.kwargs["owner"] == "octo"
    assert sync.call_args.kwargs["repository"] == "widget"
    session.close.assert_called_once()
    github_context.__exit__.assert_called_once()
    assert "completed successfully" in caplog.text


def test_sync_failure_returns_nonzero_and_closes_session():
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    github_context = MagicMock()
    github_context.__enter__.return_value = MagicMock()

    with (
        patch.object(
            sync_github,
            "get_session_factory",
            return_value=session_factory,
        ),
        patch.object(
            sync_github,
            "GitHubClient",
            return_value=github_context,
        ),
        patch.object(
            sync_github,
            "sync_updated_github_issues",
            side_effect=RuntimeError("Backfill incomplete"),
        ),
    ):
        exit_code = sync_github.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 1
    session.close.assert_called_once()
    github_context.__exit__.assert_called_once()


def test_incomplete_sync_result_returns_nonzero_and_closes_session(caplog):
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    result = SimpleNamespace(completed=False)
    github_context = MagicMock()
    github_context.__enter__.return_value = MagicMock()

    with (
        patch.object(
            sync_github,
            "get_session_factory",
            return_value=session_factory,
        ),
        patch.object(
            sync_github,
            "GitHubClient",
            return_value=github_context,
        ),
        patch.object(
            sync_github,
            "sync_updated_github_issues",
            return_value=result,
        ),
        caplog.at_level("ERROR", logger="inciflow.github_sync"),
    ):
        exit_code = sync_github.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 1
    assert "incomplete result" in caplog.text
    session.close.assert_called_once()
    github_context.__exit__.assert_called_once()


def test_unexpected_sync_error_is_logged_and_session_is_closed(caplog):
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    github_context = MagicMock()
    github_context.__enter__.return_value = MagicMock()

    with (
        patch.object(
            sync_github,
            "get_session_factory",
            return_value=session_factory,
        ),
        patch.object(
            sync_github,
            "GitHubClient",
            return_value=github_context,
        ),
        patch.object(
            sync_github,
            "sync_updated_github_issues",
            side_effect=TypeError("unexpected test failure"),
        ),
        caplog.at_level("ERROR", logger="inciflow.github_sync"),
    ):
        exit_code = sync_github.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 1
    assert "Unexpected error during GitHub synchronization" in caplog.text
    assert "unexpected test failure" in caplog.text
    session.close.assert_called_once()
    github_context.__exit__.assert_called_once()


def test_session_factory_failure_returns_nonzero_without_closing_session():
    with (
        patch.object(
            sync_github,
            "get_session_factory",
            side_effect=RuntimeError("database unavailable"),
        ),
        patch.object(sync_github, "GitHubClient") as github_client,
    ):
        exit_code = sync_github.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 1
    github_client.assert_not_called()
