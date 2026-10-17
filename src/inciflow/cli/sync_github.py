
"""Run one explicit recurring GitHub issue synchronization."""

import argparse
import logging
import sys

from sqlalchemy.exc import SQLAlchemyError

from inciflow.core.config import settings
from inciflow.ingestion.github_sync import sync_updated_github_issues
from inciflow.ingestion.sync_service import StaleCheckpointError
from inciflow.integrations.github import GitHubAPIError, GitHubClient
from inciflow.persistence.database import get_session_factory

logger = logging.getLogger("inciflow.github_sync")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Synchronize updated GitHub issues into Inciflow."
    )
    parser.add_argument(
        "--owner",
        default=settings.github_owner,
        help="GitHub repository owner (defaults to GITHUB_OWNER).",
    )
    parser.add_argument(
        "--repository",
        default=settings.github_repository,
        help="GitHub repository name (defaults to GITHUB_REPOSITORY).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one recurring synchronization and return an exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    args = build_parser().parse_args(argv)

    owner = args.owner.strip() if args.owner else ""
    repository = args.repository.strip() if args.repository else ""

    if not owner or not repository:
        print(
            "Configuration error: provide --owner and --repository, "
            "or set GITHUB_OWNER and GITHUB_REPOSITORY in .env.",
            file=sys.stderr,
        )
        return 2

    session = None

    try:
        session = get_session_factory()()

        with GitHubClient(token=settings.github_token) as github_client:
            result = sync_updated_github_issues(
                session,
                owner=owner,
                repository=repository,
                github_client=github_client,
                overlap_seconds=settings.github_sync_overlap_seconds,
            )

        if not result.completed:
            logger.error("Synchronization returned an incomplete result.")
            return 1

        logger.info("GitHub synchronization completed successfully.")
        logger.info("Repository ID: %s", result.repository_id)
        logger.info("Issues persisted: %d", result.issue_count)
        logger.info(
            "Persisted at (UTC): %s",
            result.persisted_at.isoformat(),
        )
        return 0

    except (
        GitHubAPIError,
        StaleCheckpointError,
        SQLAlchemyError,
        RuntimeError,
        ValueError,
    ) as exc:
        logger.error("GitHub synchronization failed: %s", exc)
        return 1

    except Exception:
        logger.exception("Unexpected error during GitHub synchronization.")
        return 1

    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
