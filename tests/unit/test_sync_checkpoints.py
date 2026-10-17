
"""Unit tests for independent GitHub backfill and recurring-sync checkpoints."""

from datetime import UTC, datetime

import pytest


def test_incremental_checkpoint_preserves_backfill_checkpoint():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    backfill = {
        "mode": "backfill",
        "page": 12,
        "completed": True,
    }
    watermark = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)

    updated = advance_incremental_checkpoint(
        current_payload=backfill,
        expected_watermark=None,
        new_watermark=watermark,
        overlap_seconds=120,
    )

    assert updated["mode"] == "backfill"
    assert updated["page"] == 12
    assert updated["completed"] is True
    assert updated["updated_sync"]["watermark"] == watermark.isoformat()
    assert updated["updated_sync"]["overlap_seconds"] == 120


def test_incremental_checkpoint_rejects_naive_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="timezone-aware"):
        advance_incremental_checkpoint(
            current_payload={"mode": "backfill", "page": 1, "completed": True},
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 0),
            overlap_seconds=120,
        )


@pytest.mark.parametrize("overlap_seconds", [-1, True, 1.5])
def test_incremental_checkpoint_rejects_invalid_overlap(overlap_seconds):
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="overlap_seconds"):
        advance_incremental_checkpoint(
            current_payload={"mode": "backfill", "page": 1, "completed": True},
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            overlap_seconds=overlap_seconds,
        )

def test_incremental_checkpoint_rejects_stale_expected_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    current_payload = {
        "mode": "backfill",
        "page": 12,
        "completed": True,
        "updated_sync": {
            "watermark": "2026-10-15T15:00:00+00:00",
            "overlap_seconds": 120,
        },
    }

    with pytest.raises(ValueError, match="Stored watermark does not match"):
        advance_incremental_checkpoint(
            current_payload=current_payload,
            expected_watermark=datetime(2026, 10, 15, 14, 59, tzinfo=UTC),
            new_watermark=datetime(2026, 10, 15, 15, 5, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_backwards_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    current_payload = {
        "updated_sync": {
            "watermark": "2026-10-15T15:00:00+00:00",
            "overlap_seconds": 120,
        },
    }

    with pytest.raises(ValueError, match="cannot move backwards"):
        advance_incremental_checkpoint(
            current_payload=current_payload,
            expected_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            new_watermark=datetime(2026, 10, 15, 14, 59, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_malformed_updated_sync():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="updated_sync must be a dictionary"):
        advance_incremental_checkpoint(
            current_payload={"updated_sync": "invalid"},
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_does_not_mutate_original_payload():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    original = {
        "mode": "backfill",
        "page": 12,
        "completed": True,
    }

    updated = advance_incremental_checkpoint(
        current_payload=original,
        expected_watermark=None,
        new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
        overlap_seconds=120,
    )

    assert "updated_sync" not in original
    assert "updated_sync" in updated
    assert updated is not original

from unittest.mock import Mock, patch


def test_updated_issue_batch_preserves_backfill_checkpoint():
    from inciflow.ingestion.schemas import RepositoryIngest
    from inciflow.ingestion.sync_service import ingest_updated_issue_batch

    current_payload = {
        "mode": "backfill",
        "page": 12,
        "completed": True,
    }
    repository = RepositoryIngest(
        github_repo_id=12345,
        owner="example",
        name="repo",
        full_name="example/repo",
    )
    session = Mock()
    result = Mock()

    with patch(
        "inciflow.ingestion.sync_service.ingest_incremental_batch",
        return_value=result,
    ) as ingest:
        returned = ingest_updated_issue_batch(
            session,
            repository_data=repository,
            issues=[],
            expected_cursor_payload=current_payload,
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            overlap_seconds=120,
        )

    assert returned is result
    kwargs = ingest.call_args.kwargs
    assert kwargs["expected_cursor_payload"] == current_payload
    assert kwargs["cursor_payload"]["mode"] == "backfill"
    assert kwargs["cursor_payload"]["page"] == 12
    assert kwargs["cursor_payload"]["completed"] is True
    assert kwargs["cursor_payload"]["updated_sync"] == {
        "watermark": "2026-10-15T15:00:00+00:00",
        "overlap_seconds": 120,
    }
    assert kwargs["completed"] is True
    assert kwargs["external_updated_at"] == datetime(
        2026, 10, 15, 15, 0, tzinfo=UTC
    )


def test_updated_issue_batch_rejects_stale_watermark_before_ingestion():
    from inciflow.ingestion.schemas import RepositoryIngest
    from inciflow.ingestion.sync_service import ingest_updated_issue_batch

    repository = RepositoryIngest(
        github_repo_id=12345,
        owner="example",
        name="repo",
        full_name="example/repo",
    )
    current_payload = {
        "updated_sync": {
            "watermark": "2026-10-15T15:00:00+00:00",
            "overlap_seconds": 120,
        }
    }

    with patch(
        "inciflow.ingestion.sync_service.ingest_incremental_batch"
    ) as ingest, pytest.raises(ValueError, match="Stored watermark does not match"):
        ingest_updated_issue_batch(
            Mock(),
            repository_data=repository,
            issues=[],
            expected_cursor_payload=current_payload,
            expected_watermark=datetime(
                2026, 10, 15, 14, 59, tzinfo=UTC
            ),
            new_watermark=datetime(2026, 10, 15, 15, 5, tzinfo=UTC),
            overlap_seconds=120,
        )

    ingest.assert_not_called()


def test_incremental_checkpoint_rejects_non_dictionary_payload():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(TypeError, match="current_payload must be a dictionary"):
        advance_incremental_checkpoint(
            current_payload=[],
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_non_datetime_new_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(TypeError, match="new_watermark must be a datetime"):
        advance_incremental_checkpoint(
            current_payload={},
            expected_watermark=None,
            new_watermark="2026-10-15T15:00:00+00:00",
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_non_datetime_expected_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(
        TypeError,
        match="expected_watermark must be a datetime or None",
    ):
        advance_incremental_checkpoint(
            current_payload={},
            expected_watermark="2026-10-15T15:00:00+00:00",
            new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_naive_expected_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="expected_watermark must be timezone-aware"):
        advance_incremental_checkpoint(
            current_payload={},
            expected_watermark=datetime(2026, 10, 15, 15, 0),
            new_watermark=datetime(2026, 10, 15, 15, 5, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_non_string_stored_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="Stored watermark must be a string or None"):
        advance_incremental_checkpoint(
            current_payload={"updated_sync": {"watermark": 123}},
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_stored_watermark_without_expected_watermark():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="Stored watermark does not match"):
        advance_incremental_checkpoint(
            current_payload={
                "updated_sync": {
                    "watermark": "2026-10-15T15:00:00+00:00",
                    "overlap_seconds": 120,
                }
            },
            expected_watermark=None,
            new_watermark=datetime(2026, 10, 15, 15, 5, tzinfo=UTC),
            overlap_seconds=120,
        )


def test_incremental_checkpoint_rejects_expected_watermark_without_stored_checkpoint():
    from inciflow.ingestion.checkpoints import advance_incremental_checkpoint

    with pytest.raises(ValueError, match="Stored watermark does not match"):
        advance_incremental_checkpoint(
            current_payload={"mode": "backfill", "page": 12, "completed": True},
            expected_watermark=datetime(2026, 10, 15, 15, 0, tzinfo=UTC),
            new_watermark=datetime(2026, 10, 15, 15, 5, tzinfo=UTC),
            overlap_seconds=120,
        )
