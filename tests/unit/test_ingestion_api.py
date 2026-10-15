"""HTTP tests for the repository ingestion endpoint."""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from inciflow.ingestion.service import IngestionResult
from inciflow.main import app
from inciflow.persistence.database import get_db_session


@pytest.fixture
def client():
    from unittest.mock import MagicMock

    session = MagicMock()

    def override_get_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def valid_payload() -> dict:
    return {
        "repository": {
            "github_repo_id": 12345,
            "owner": "example",
            "name": "sample",
            "full_name": "example/sample",
            "default_branch": "main",
            "is_active": True,
        },
        "issues": [
            {
                "github_issue_id": 98765,
                "issue_number": 1,
                "title": "Example issue",
                "state": "open",
                "labels": ["bug"],
            }
        ],
    }


def test_ingestion_endpoint_returns_snapshot_summary(client):
    repository_id = uuid4()
    synced_at = datetime.now(UTC)
    result = IngestionResult(
        repository_id=repository_id,
        issue_count=1,
        synced_at=synced_at,
    )

    with patch(
        "inciflow.main.ingest_repository_snapshot",
        return_value=result,
    ) as mock_ingest:
        response = client.post(
            "/api/v1/ingestion/snapshots",
            json=valid_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == str(repository_id)
    assert body["issue_count"] == 1
    assert datetime.fromisoformat(body["synced_at"]) == synced_at
    mock_ingest.assert_called_once()


def test_ingestion_endpoint_rejects_invalid_issue_state(client):
    payload = valid_payload()
    payload["issues"][0]["state"] = "pending"

    with patch("inciflow.main.ingest_repository_snapshot") as mock_ingest:
        response = client.post(
            "/api/v1/ingestion/snapshots",
            json=payload,
        )

    assert response.status_code == 422
    mock_ingest.assert_not_called()


def test_ingestion_endpoint_returns_conflict_without_database_details(client):
    error = IntegrityError(
        "INSERT",
        {},
        RuntimeError("private database detail"),
    )

    with patch(
        "inciflow.main.ingest_repository_snapshot",
        side_effect=error,
    ):
        response = client.post(
            "/api/v1/ingestion/snapshots",
            json=valid_payload(),
        )

    assert response.status_code == 409
    assert "conflicts with existing" in response.json()["detail"]
    assert "private database detail" not in response.text


def test_ingestion_endpoint_rejects_duplicate_snapshot_ids(client):
    payload = valid_payload()
    payload["issues"].append(
        {
            **payload["issues"][0],
            "issue_number": 2,
        }
    )

    with patch(
        "inciflow.main.ingest_repository_snapshot",
        side_effect=ValueError("Snapshot contains duplicate GitHub issue IDs."),
    ):
        response = client.post(
            "/api/v1/ingestion/snapshots",
            json=payload,
        )

    assert response.status_code == 422
    assert "duplicate GitHub issue IDs" in response.json()["detail"]
