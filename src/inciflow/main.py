"""FastAPI application entry point."""

import hmac
from datetime import UTC, datetime
import logging

from inciflow.persistence.repositories.repositories import (
    get_repository_by_full_name,
)
from inciflow.persistence.repositories.integration_syncs import (
    mark_github_repository_sync_failed,
)

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inciflow.ingestion.schemas import IngestionResponse, SnapshotIngest
from inciflow.ingestion.service import ingest_repository_snapshot
from inciflow.persistence.database import get_db_session, get_session_factory
from inciflow.core.config import settings
from inciflow.integrations.github import GitHubAPIError, GitHubClient
from inciflow.ingestion.github_sync import sync_updated_github_issues
from inciflow.ingestion.sync_service import StaleCheckpointError
from sqlalchemy.exc import SQLAlchemyError


app = FastAPI(
    title="Inciflow API",
    description="Evidence-grounded GitHub issue management and resolution orchestration.",
    version="0.1.0",
)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    """Describe the running application."""
    return {
        "application": "Inciflow",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    """Confirm that the application process is responding."""
    return {"status": "alive"}


@app.post(
    "/api/v1/ingestion/snapshots",
    response_model=IngestionResponse,
    status_code=status.HTTP_200_OK,
    tags=["ingestion"],
)
def ingest_snapshot(
    payload: SnapshotIngest,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> IngestionResponse:
    """Validate and atomically ingest a repository issue snapshot."""
    try:
        result = ingest_repository_snapshot(
            session,
            repository_data=payload.repository,
            issues=payload.issues,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Snapshot conflicts with existing repository or issue data.",
        ) from exc

    return IngestionResponse(
        repository_id=result.repository_id,
        issue_count=result.issue_count,
        synced_at=result.synced_at,
    )


@app.post("/api/v1/integrations/github/sync", tags=["integrations"])
def trigger_github_sync(
    x_inciflow_sync_secret: str | None = Header(default=None),
) -> dict[str, object]:
    """Trigger one authenticated incremental GitHub synchronization."""
    expected_secret = settings.inciflow_sync_trigger_secret

    if (
        not expected_secret
        or not x_inciflow_sync_secret
        or not hmac.compare_digest(x_inciflow_sync_secret, expected_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing sync credentials.",
        )

    if (
        not settings.github_token
        or not settings.github_owner
        or not settings.github_repository
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub synchronization is not configured.",
        )

    started_at = datetime.now(UTC)
    session = None

    try:
        session = get_session_factory()()

        with GitHubClient(token=settings.github_token) as github_client:
            result = sync_updated_github_issues(
                session,
                owner=settings.github_owner,
                repository=settings.github_repository,
                github_client=github_client,
                overlap_seconds=settings.github_sync_overlap_seconds,
            )

        if not result.completed:
            raise RuntimeError("GitHub synchronization did not complete.")

        return {
            "status": "completed",
            "repository_id": result.repository_id,
            "issues_persisted": result.issue_count,
            "persisted_at": result.persisted_at.isoformat(),
        }

    except HTTPException:
        raise
    except (
        GitHubAPIError,
        StaleCheckpointError,
        SQLAlchemyError,
        RuntimeError,
        ValueError,
    ) as exc:
        logging.getLogger("inciflow.github_sync_api").exception(
            "GitHub synchronization failed."
        )

        if session is not None:
            try:
                session.rollback()
            except SQLAlchemyError:
                logging.getLogger("inciflow.github_sync_api").exception(
                    "Failed to roll back the GitHub sync transaction."
                )

        if session is not None:
            session.close()
            session = None

        failure_session = None
        try:
            failure_session = get_session_factory()()
            with failure_session.begin():
                full_name = (
                    f"{settings.github_owner}/{settings.github_repository}"
                )
                repository_record = get_repository_by_full_name(
                    failure_session, full_name
                )

                if repository_record is not None:
                    mark_github_repository_sync_failed(
                        failure_session,
                        github_repository_id=repository_record.github_repo_id,
                        error_message=(
                            f"{type(exc).__name__}: "
                            "GitHub synchronization failed."
                        ),
                        started_at=started_at,
                    )
        except (SQLAlchemyError, RuntimeError, ValueError):
            logging.getLogger("inciflow.github_sync_api").exception(
                "Could not persist the GitHub sync failure state."
            )
        finally:
            if failure_session is not None:
                failure_session.close()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub synchronization failed. Check server logs.",
        ) from exc
    finally:
        if session is not None:
            session.close()
