"""FastAPI application entry point."""

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inciflow.ingestion.schemas import IngestionResponse, SnapshotIngest
from inciflow.ingestion.service import ingest_repository_snapshot
from inciflow.persistence.database import get_db_session

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
