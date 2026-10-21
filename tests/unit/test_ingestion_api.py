
"""HTTP tests for the repository ingestion endpoint."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from inciflow.ingestion.service import IngestionResult
from inciflow.main import app
from inciflow.persistence.database import get_db_session


@pytest.fixture
def client():
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


def test_github_sync_endpoint_rejects_missing_secret(client):
    response = client.post("/api/v1/integrations/github/sync")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing sync credentials."


def test_github_sync_endpoint_accepts_valid_secret(client):
    from types import SimpleNamespace

    result = SimpleNamespace(
        completed=True,
        repository_id="test-repository-id",
        issue_count=3,
        persisted_at=datetime.now(UTC),
    )

    with (
        patch("inciflow.main.settings") as mock_settings,
        patch("inciflow.main.get_session_factory") as mock_factory,
        patch("inciflow.main.GitHubClient") as mock_client_class,
        patch(
            "inciflow.main.sync_updated_github_issues",
            return_value=result,
        ) as mock_sync,
    ):
        mock_settings.inciflow_sync_trigger_secret = "test-secret"
        mock_settings.github_token = "test-token"
        mock_settings.github_owner = "example"
        mock_settings.github_repository = "sample"
        mock_settings.github_sync_overlap_seconds = 120

        session = MagicMock()
        mock_factory.return_value.return_value = session
        mock_client_class.return_value.__enter__.return_value = MagicMock()

        response = client.post(
            "/api/v1/integrations/github/sync",
            headers={"X-Inciflow-Sync-Secret": "test-secret"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["issues_persisted"] == 3
    mock_sync.assert_called_once()
    session.close.assert_called_once()


def test_github_sync_endpoint_accepts_valid_secret_with_test_settings(client):
    from types import SimpleNamespace

    result = SimpleNamespace(
        completed=True,
        repository_id="test-repository-id",
        issue_count=3,
        persisted_at=datetime.now(UTC),
    )

    test_settings = SimpleNamespace(
        inciflow_sync_trigger_secret="test-secret",
        github_token="test-token",
        github_owner="example",
        github_repository="sample",
        github_sync_overlap_seconds=120,
    )

    with (
        patch("inciflow.main.settings", test_settings),
        patch("inciflow.main.get_session_factory") as mock_factory,
        patch("inciflow.main.GitHubClient") as mock_client_class,
        patch(
            "inciflow.main.sync_updated_github_issues",
            return_value=result,
        ) as mock_sync,
    ):
        session = MagicMock()
        mock_factory.return_value.return_value = session
        mock_client_class.return_value.__enter__.return_value = MagicMock()

        response = client.post(
            "/api/v1/integrations/github/sync",
            headers={"X-Inciflow-Sync-Secret": "test-secret"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["issues_persisted"] == 3
    mock_sync.assert_called_once()
    session.close.assert_called_once()


def test_github_sync_endpoint_rejects_invalid_secret(client):
    from types import SimpleNamespace

    test_settings = SimpleNamespace(
        inciflow_sync_trigger_secret="expected-secret",
        github_token="test-token",
        github_owner="example",
        github_repository="sample",
        github_sync_overlap_seconds=120,
    )

    with patch("inciflow.main.settings", test_settings):
        response = client.post(
            "/api/v1/integrations/github/sync",
            headers={"X-Inciflow-Sync-Secret": "wrong-secret"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing sync credentials."


def test_github_sync_endpoint_returns_generic_error_on_sync_failure(client):
    from types import SimpleNamespace

    test_settings = SimpleNamespace(
        inciflow_sync_trigger_secret="test-secret",
        github_token="test-token",
        github_owner="example",
        github_repository="sample",
        github_sync_overlap_seconds=120,
    )

    with (
        patch("inciflow.main.settings", test_settings),
        patch("inciflow.main.get_session_factory") as mock_factory,
        patch("inciflow.main.GitHubClient") as mock_client_class,
        patch(
            "inciflow.main.sync_updated_github_issues",
            side_effect=RuntimeError("private internal detail"),
        ),
        patch(
            "inciflow.main.get_repository_by_full_name",
            return_value=None,
        ),
    ):
        session = MagicMock()
        mock_factory.return_value.return_value = session
        mock_client_class.return_value.__enter__.return_value = MagicMock()

        response = client.post(
            "/api/v1/integrations/github/sync",
            headers={"X-Inciflow-Sync-Secret": "test-secret"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "GitHub synchronization failed. Check server logs."
    )
    assert "private internal detail" not in response.text
    assert session.close.call_count == 2

def test_github_sync_failure_marks_registered_repository_failed(client):
    from types import SimpleNamespace

    test_settings = SimpleNamespace(
        inciflow_sync_trigger_secret="test-secret",
        github_token="test-token",
        github_owner="example",
        github_repository="sample",
        github_sync_overlap_seconds=120,
    )
    repository_record = SimpleNamespace(github_repo_id=12345)

    with (
        patch("inciflow.main.settings", test_settings),
        patch("inciflow.main.get_session_factory") as mock_factory,
        patch("inciflow.main.GitHubClient") as mock_client_class,
        patch(
            "inciflow.main.sync_updated_github_issues",
            side_effect=RuntimeError("private internal detail"),
        ),
        patch(
            "inciflow.main.get_repository_by_full_name",
            return_value=repository_record,
        ),
        patch(
            "inciflow.main.mark_github_repository_sync_failed"
        ) as mock_mark_failed,
    ):
        sync_session = MagicMock()
        failure_session = MagicMock()
        mock_factory.return_value.side_effect = [
            sync_session,
            failure_session,
        ]
        mock_client_class.return_value.__enter__.return_value = MagicMock()

        response = client.post(
            "/api/v1/integrations/github/sync",
            headers={"X-Inciflow-Sync-Secret": "test-secret"},
        )

    assert response.status_code == 500
    mock_mark_failed.assert_called_once()
    assert mock_mark_failed.call_args.kwargs["github_repository_id"] == 12345
    assert mock_mark_failed.call_args.kwargs["error_message"] == (
        "RuntimeError: GitHub synchronization failed."
    )
    assert mock_mark_failed.call_args.kwargs["started_at"].tzinfo is not None
    failure_session.begin.assert_called_once()
    sync_session.close.assert_called_once()
    failure_session.close.assert_called_once()
