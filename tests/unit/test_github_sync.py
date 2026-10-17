
"""Focused tests for recurring GitHub synchronization orchestration."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from inciflow.ingestion.github_sync import sync_updated_github_issues


@patch("inciflow.ingestion.github_sync.ingest_updated_issue_batch")
@patch("inciflow.ingestion.github_sync.get_or_create_github_repository_sync")
def test_first_sync_uses_overlap_window(mock_get_sync, mock_ingest):
    now = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    repository_data = SimpleNamespace(github_repo_id=123)
    first_cursor = {
        "mode": "backfill",
        "page": 3,
        "completed": True,
    }

    client = MagicMock()
    client.fetch_repository.return_value = repository_data
    client.fetch_updated_issue_batch.return_value = SimpleNamespace(
        repository=repository_data,
        issues=[],
        watermark=now,
        completed=True,
    )
    mock_get_sync.return_value = SimpleNamespace(cursor_payload=first_cursor)
    session = MagicMock()

    sync_updated_github_issues(
        session,
        owner="octo",
        repository="widget",
        github_client=client,
        now=now,
        overlap_seconds=120,
    )

    client.fetch_repository.assert_called_once_with("octo", "widget")
    client.fetch_updated_issue_batch.assert_called_once_with(
        "octo",
        "widget",
        since=now - timedelta(seconds=120),
        watermark=now,
    )
    mock_ingest.assert_called_once_with(
        session,
        repository_data=repository_data,
        issues=[],
        expected_cursor_payload=first_cursor,
        expected_watermark=None,
        new_watermark=now,
        overlap_seconds=120,
    )


@patch("inciflow.ingestion.github_sync.ingest_updated_issue_batch")
@patch("inciflow.ingestion.github_sync.get_or_create_github_repository_sync")
def test_recurring_sync_reuses_stored_watermark_with_overlap(
    mock_get_sync,
    mock_ingest,
):
    now = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    stored_watermark = datetime(2026, 10, 15, 14, 30, tzinfo=UTC)
    cursor = {
        "mode": "backfill",
        "page": 3,
        "completed": True,
        "updated_sync": {
            "watermark": stored_watermark.isoformat(),
            "overlap_seconds": 120,
        },
    }
    repository_data = SimpleNamespace(github_repo_id=123)

    client = MagicMock()
    client.fetch_repository.return_value = repository_data
    client.fetch_updated_issue_batch.return_value = SimpleNamespace(
        repository=repository_data,
        issues=[],
        watermark=now,
        completed=True,
    )
    mock_get_sync.return_value = SimpleNamespace(cursor_payload=cursor)
    session = MagicMock()

    sync_updated_github_issues(
        session,
        owner="octo",
        repository="widget",
        github_client=client,
        now=now,
        overlap_seconds=120,
    )

    client.fetch_updated_issue_batch.assert_called_once_with(
        "octo",
        "widget",
        since=stored_watermark - timedelta(seconds=120),
        watermark=now,
    )
    mock_ingest.assert_called_once_with(
        session,
        repository_data=repository_data,
        issues=[],
        expected_cursor_payload=cursor,
        expected_watermark=stored_watermark,
        new_watermark=now,
        overlap_seconds=120,
    )


@patch("inciflow.ingestion.github_sync.get_or_create_github_repository_sync")
def test_malformed_stored_watermark_stops_before_fetching_updates(
    mock_get_sync,
):
    now = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    client = MagicMock()
    client.fetch_repository.return_value = SimpleNamespace(github_repo_id=123)
    mock_get_sync.return_value = SimpleNamespace(
        cursor_payload={
            "mode": "backfill",
            "page": 3,
            "completed": True,
            "updated_sync": "invalid",
        }
    )

    with pytest.raises(TypeError, match="updated_sync"):
        sync_updated_github_issues(
            MagicMock(),
            owner="octo",
            repository="widget",
            github_client=client,
            now=now,
        )

    client.fetch_updated_issue_batch.assert_not_called()


@pytest.mark.parametrize("overlap_seconds", [-1, True, 1.5])
def test_invalid_overlap_is_rejected_before_network_requests(
    overlap_seconds,
):
    client = MagicMock()

    with pytest.raises(ValueError, match="overlap_seconds"):
        sync_updated_github_issues(
            MagicMock(),
            owner="octo",
            repository="widget",
            github_client=client,
            overlap_seconds=overlap_seconds,
        )

    client.fetch_repository.assert_not_called()


@patch("inciflow.ingestion.github_sync.get_or_create_github_repository_sync")
def test_incomplete_backfill_stops_before_fetching_updates(mock_get_sync):
    now = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    repository_data = SimpleNamespace(github_repo_id=123)
    client = MagicMock()
    client.fetch_repository.return_value = repository_data
    mock_get_sync.return_value = SimpleNamespace(
        cursor_payload={
            "mode": "backfill",
            "page": 2,
            "completed": False,
        }
    )

    with pytest.raises(RuntimeError, match="backfill must be completed"):
        sync_updated_github_issues(
            MagicMock(),
            owner="octo",
            repository="widget",
            github_client=client,
            now=now,
        )

    client.fetch_updated_issue_batch.assert_not_called()

def test_sync_rejects_non_datetime_now_before_network_requests():
    client = MagicMock()

    with pytest.raises(TypeError, match="now must be a datetime"):
        sync_updated_github_issues(
            MagicMock(),
            owner="octo",
            repository="widget",
            github_client=client,
            now="2026-10-16T12:00:00Z",
        )

    client.fetch_repository.assert_not_called()


def test_sync_rejects_naive_now_before_network_requests():
    client = MagicMock()

    with pytest.raises(ValueError, match="now must be timezone-aware"):
        sync_updated_github_issues(
            MagicMock(),
            owner="octo",
            repository="widget",
            github_client=client,
            now=datetime(2026, 10, 16, 12, 0),
        )

    client.fetch_repository.assert_not_called()


def test_read_watermark_returns_none_when_watermark_is_missing():
    from inciflow.ingestion.github_sync import _read_watermark

    assert _read_watermark({}) is None
    assert _read_watermark({"updated_sync": {}}) is None
    assert _read_watermark({"updated_sync": {"watermark": None}}) is None


def test_read_watermark_rejects_non_string_watermark():
    from inciflow.ingestion.github_sync import _read_watermark

    with pytest.raises(TypeError, match="watermark must be an ISO-8601 string"):
        _read_watermark({"updated_sync": {"watermark": 123}})


def test_read_watermark_rejects_invalid_timestamp():
    from inciflow.ingestion.github_sync import _read_watermark

    with pytest.raises(
        ValueError,
        match="Stored watermark is not a valid timestamp",
    ) as error:
        _read_watermark({"updated_sync": {"watermark": "not-a-timestamp"}})

    assert isinstance(error.value.__cause__, ValueError)


def test_read_watermark_rejects_timezone_naive_timestamp():
    from inciflow.ingestion.github_sync import _read_watermark

    with pytest.raises(
        ValueError,
        match="Stored watermark must be timezone-aware",
    ):
        _read_watermark(
            {"updated_sync": {"watermark": "2026-10-16T12:00:00"}}
        )
