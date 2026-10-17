
"""Run one resumable batch of historical GitHub issue ingestion."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from inciflow.core.config import settings
from inciflow.ingestion.sync_service import (
    StaleCheckpointError,
    ingest_github_issue_batch,
)
from inciflow.integrations.github import GitHubAPIError, GitHubClient
from inciflow.persistence.database import get_session_factory
from inciflow.persistence.repositories.integration_syncs import (
    get_or_create_github_repository_sync,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Ingest one resumable batch of historical GitHub issues."
    )
    parser.add_argument(
        "--owner",
        default=settings.github_owner,
        help="GitHub repository owner.",
    )
    parser.add_argument(
        "--repository",
        default=settings.github_repository,
        help="GitHub repository name.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity.",
    )
    return parser


def _validate_incomplete_checkpoint(payload: dict[str, Any]) -> None:
    """Reject malformed or completed checkpoints before fetching a batch."""
    if not isinstance(payload, dict):
        raise TypeError("Backfill checkpoint must be a dictionary.")

    if payload == {}:
        return

    if (
        set(payload)
        not in (
            {"mode", "page"},
            {"mode", "page", "after"},
        )
        or payload.get("mode") != "backfill"
        or type(payload.get("page")) is not int
        or payload["page"] < 1
        or (
            "after" in payload
            and (
                not isinstance(payload["after"], str)
                or not payload["after"]
            )
        )
    ):
        raise ValueError("Invalid or completed backfill checkpoint.")


def main(argv: list[str] | None = None) -> int:
    """Fetch and atomically persist a single historical batch."""
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.owner.strip() or not args.repository.strip():
        logger.error("GitHub owner and repository must not be empty.")
        return 2

    session_factory = get_session_factory()

    try:
        with GitHubClient(token=settings.github_token) as client:
            # Fetch repository metadata to obtain its stable GitHub ID.
            repository = client.fetch_repository(
                args.owner,
                args.repository,
            )

            # Read or initialize the checkpoint in a short-lived session.
            with session_factory() as session:
                sync_record = get_or_create_github_repository_sync(
                    session,
                    github_repository_id=repository.github_repo_id,
                )
                checkpoint = dict(sync_record.cursor_payload or {})

                # This helper leaves transaction ownership to its caller.
                # Commit initialization before closing the session.
                session.commit()

            if checkpoint.get("completed") is True:
                logger.info(
                    "Historical backfill is already complete for %s/%s.",
                    args.owner,
                    args.repository,
                )
                return 0

            _validate_incomplete_checkpoint(checkpoint)

            # Fetch the batch without holding a database session open.
            batch = client.fetch_issue_batch(
                args.owner,
                args.repository,
                checkpoint,
            )

            # The ingestion service owns the atomic write transaction.
            with session_factory() as ingestion_session:
                result = ingest_github_issue_batch(
                    ingestion_session,
                    batch=batch,
                )

            logger.info(
                "Backfill batch persisted for %s/%s: "
                "issues=%d completed=%s",
                args.owner,
                args.repository,
                len(batch.issues),
                batch.completed,
            )
            logger.debug("Ingestion result: %r", result)

            if batch.completed:
                logger.info("Historical backfill completed.")
            else:
                logger.info(
                    "Next checkpoint: %s",
                    batch.cursor_payload,
                )

        return 0

    except StaleCheckpointError:
        logger.error(
            "The backfill checkpoint changed during ingestion. "
            "No automatic retry was attempted; inspect the saved checkpoint "
            "before running the command again."
        )
        return 1
    except (GitHubAPIError, ValueError) as exc:
        logger.error("Backfill stopped: %s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error during historical backfill.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
