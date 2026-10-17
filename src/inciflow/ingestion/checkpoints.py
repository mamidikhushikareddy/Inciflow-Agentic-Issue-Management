
"""Helpers for advancing recurring-sync checkpoints safely."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


def advance_incremental_checkpoint(
    *,
    current_payload: dict[str, Any],
    expected_watermark: datetime | None,
    new_watermark: datetime,
    overlap_seconds: int,
) -> dict[str, Any]:
    """Advance the recurring-sync watermark without losing backfill state.

    The caller must compare the expected watermark with the persisted
    checkpoint while holding the appropriate database lock.
    This function validates and constructs the next checkpoint only.
    """
    if not isinstance(current_payload, dict):
        raise TypeError("current_payload must be a dictionary.")

    if not isinstance(new_watermark, datetime):
        raise TypeError("new_watermark must be a datetime.")

    if new_watermark.tzinfo is None or new_watermark.utcoffset() is None:
        raise ValueError("new_watermark must be timezone-aware.")

    if expected_watermark is not None:
        if not isinstance(expected_watermark, datetime):
            raise TypeError(
                "expected_watermark must be a datetime or None."
            )

        if (
            expected_watermark.tzinfo is None
            or expected_watermark.utcoffset() is None
        ):
            raise ValueError(
                "expected_watermark must be timezone-aware."
            )

    if type(overlap_seconds) is not int or overlap_seconds < 0:
        raise ValueError(
            "overlap_seconds must be a non-negative integer."
        )

    updated = deepcopy(current_payload)
    existing_incremental = updated.get("updated_sync")

    if existing_incremental is not None:
        if not isinstance(existing_incremental, dict):
            raise ValueError("updated_sync must be a dictionary.")

        stored_watermark = existing_incremental.get("watermark")

        if (
            stored_watermark is not None
            and not isinstance(stored_watermark, str)
        ):
            raise ValueError(
                "Stored watermark must be a string or None."
            )

        if expected_watermark is None:
            if stored_watermark is not None:
                raise ValueError(
                    "Stored watermark does not match expected watermark."
                )
        else:
            expected_text = expected_watermark.astimezone(UTC).isoformat()

            if stored_watermark != expected_text:
                raise ValueError(
                    "Stored watermark does not match expected watermark."
                )

    elif expected_watermark is not None:
        raise ValueError(
            "Stored watermark does not match expected watermark."
        )

    new_watermark_utc = new_watermark.astimezone(UTC)

    if expected_watermark is not None:
        expected_utc = expected_watermark.astimezone(UTC)

        if new_watermark_utc < expected_utc:
            raise ValueError("new_watermark cannot move backwards.")

    updated["updated_sync"] = {
        "watermark": new_watermark_utc.isoformat(),
        "overlap_seconds": overlap_seconds,
    }

    return updated
