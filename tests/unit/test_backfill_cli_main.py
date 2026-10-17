"""Unit tests for the historical GitHub backfill CLI entry point."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import inciflow.cli.backfill_github as cli
from inciflow.ingestion.sync_service import StaleCheckpointError
from inciflow.integrations.github import GitHubAPIError


@pytest.fixture
def cli_mocks(monkeypatch):
    """Replace external dependencies with mocks."""
    client = MagicMock()
    github_context = MagicMock()
    github_context.__enter__.return_value = client
    monkeypatch.setattr(
        cli, "GitHubClient", MagicMock(return_value=github_context)
    )

    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    session_factory = MagicMock(return_value=session_context)
    monkeypatch.setattr(cli, "get_session_factory", MagicMock(return_value=session_factory))

    repository = SimpleNamespace(github_repo_id=12345)
    client.fetch_repository.return_value = repository

    sync_record = SimpleNamespace(cursor_payload={})
    monkeypatch.setattr(
        cli,
        "get_or_create_github_repository_sync",
        MagicMock(return_value=sync_record),
    )

    batch = SimpleNamespace(
        issues=[SimpleNamespace(issue_number=1)],
        completed=False,
        cursor_payload={"mode": "backfill", "page": 2},
    )
    client.fetch_issue_batch.return_value = batch
    monkeypatch.setattr(
        cli,
        "ingest_github_issue_batch",
        MagicMock(return_value={"persisted": 1}),
    )

    return SimpleNamespace(
        client=client,
        session=session,
        session_factory=session_factory,
        sync_record=sync_record,
        batch=batch,
    )


def test_empty_owner_returns_usage_error(monkeypatch):
    get_factory = MagicMock()
    monkeypatch.setattr(cli, "get_session_factory", get_factory)

    assert cli.main(["--owner", " ", "--repository", "widget"]) == 2
    get_factory.assert_not_called()


def test_completed_checkpoint_exits_without_fetching_batch(cli_mocks):
    cli_mocks.sync_record.cursor_payload = {
        "mode": "backfill", "page": 100, "completed": True
    }

    assert cli.main(["--owner", "octo", "--repository", "widget"]) == 0
    cli_mocks.client.fetch_issue_batch.assert_not_called()
    cli.ingest_github_issue_batch.assert_not_called()


def test_successful_batch_returns_zero(cli_mocks):
    assert cli.main(["--owner", "octo", "--repository", "widget"]) == 0

    cli_mocks.client.fetch_issue_batch.assert_called_once_with(
        "octo", "widget", {}
    )
    cli.ingest_github_issue_batch.assert_called_once_with(
        cli_mocks.session, batch=cli_mocks.batch
    )
    cli_mocks.session.commit.assert_called_once()


def test_invalid_checkpoint_returns_one_without_ingesting(cli_mocks):
    cli_mocks.sync_record.cursor_payload = {
        "mode": "backfill", "page": 0
    }

    assert cli.main(["--owner", "octo", "--repository", "widget"]) == 1
    cli_mocks.client.fetch_issue_batch.assert_not_called()
    cli.ingest_github_issue_batch.assert_not_called()


def test_github_api_error_returns_one(cli_mocks):
    cli_mocks.client.fetch_repository.side_effect = GitHubAPIError(
        "simulated API failure"
    )

    assert cli.main(["--owner", "octo", "--repository", "widget"]) == 1


def test_stale_checkpoint_returns_one_without_retry(cli_mocks):
    cli.ingest_github_issue_batch.side_effect = StaleCheckpointError(
        "simulated stale checkpoint"
    )

    assert cli.main(["--owner", "octo", "--repository", "widget"]) == 1
    cli.ingest_github_issue_batch.assert_called_once()


def test_completed_batch_logs_completion_and_returns_zero(cli_mocks, caplog):
    cli_mocks.batch.completed = True

    with caplog.at_level("INFO"):
        exit_code = cli.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 0
    assert "Historical backfill completed." in caplog.text
    cli.ingest_github_issue_batch.assert_called_once()


def test_unexpected_error_returns_one_and_logs_exception(cli_mocks, caplog):
    cli_mocks.client.fetch_repository.side_effect = TypeError(
        "unexpected test failure"
    )

    with caplog.at_level("ERROR"):
        exit_code = cli.main(
            ["--owner", "octo", "--repository", "widget"]
        )

    assert exit_code == 1
    assert "Unexpected error during historical backfill." in caplog.text
    assert "unexpected test failure" in caplog.text


def test_checkpoint_validator_rejects_non_dictionary():
    with pytest.raises(
        TypeError,
        match="Backfill checkpoint must be a dictionary",
    ):
        cli._validate_incomplete_checkpoint([])
