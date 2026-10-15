"""PostgreSQL integration tests for persistence repositories."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from inciflow.core.config import settings
from inciflow.persistence.database import get_engine
from inciflow.persistence.models.issues import Issue
from inciflow.persistence.models.repositories import Repository
from inciflow.persistence.repositories.issues import (
    get_issue_by_github_id,
    list_issues,
    upsert_issue,
)
from inciflow.persistence.repositories.repositories import upsert_repository


@pytest.fixture
def db_session():
    """Provide a rollback-isolated session against inciflow_test only."""
    if settings.database_name != "inciflow_test":
        pytest.skip("PostgreSQL integration tests require inciflow_test.")

    engine = get_engine()

    with engine.connect() as verification_connection:
        actual_database = verification_connection.scalar(
            text("SELECT current_database()")
        )

    if actual_database != "inciflow_test":
        pytest.fail(
            "Safety check failed: connected to "
            f"{actual_database!r}, not inciflow_test."
        )

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()


def make_github_repo_id() -> int:
    """Generate a positive ID unlikely to collide with another test."""
    return uuid4().int % 1_000_000_000_000 + 1


def test_repository_upsert_updates_existing_row(db_session: Session):
    github_repo_id = make_github_repo_id()
    repository = upsert_repository(
        db_session,
        github_repo_id=github_repo_id,
        owner="inciflow-test",
        name="first-name",
        full_name=f"inciflow-test/{github_repo_id}",
    )
    original_id = repository.id

    updated = upsert_repository(
        db_session,
        github_repo_id=github_repo_id,
        owner="inciflow-test",
        name="renamed",
        full_name=f"inciflow-test/{github_repo_id}",
        default_branch="develop",
    )

    assert updated.id == original_id
    assert updated.name == "renamed"
    assert updated.default_branch == "develop"


def test_issue_upsert_is_idempotent_and_refreshes_values(db_session: Session):
    github_repo_id = make_github_repo_id()
    repository = upsert_repository(
        db_session,
        github_repo_id=github_repo_id,
        owner="inciflow-test",
        name="issues",
        full_name=f"inciflow-test/{github_repo_id}",
    )

    github_issue_id = make_github_repo_id()
    first = upsert_issue(
        db_session,
        repository_id=repository.id,
        github_issue_id=github_issue_id,
        issue_number=1,
        title="Original title",
        labels=["bug"],
    )
    original_issue_id = first.id

    updated = upsert_issue(
        db_session,
        repository_id=repository.id,
        github_issue_id=github_issue_id,
        issue_number=1,
        title="Updated title",
        labels=["bug", "verified"],
    )

    assert updated.id == original_issue_id
    assert updated.title == "Updated title"
    assert updated.labels == ["bug", "verified"]

    fetched = get_issue_by_github_id(
        db_session,
        repository_id=repository.id,
        github_issue_id=github_issue_id,
    )
    assert fetched is not None
    assert fetched.id == original_issue_id
    assert fetched.title == "Updated title"


def test_issue_pagination_returns_expected_records(db_session: Session):
    github_repo_id = make_github_repo_id()
    repository = upsert_repository(
        db_session,
        github_repo_id=github_repo_id,
        owner="inciflow-test",
        name="pagination",
        full_name=f"inciflow-test/{github_repo_id}",
    )

    for number in (1, 2, 3):
        upsert_issue(
            db_session,
            repository_id=repository.id,
            github_issue_id=make_github_repo_id(),
            issue_number=number,
            title=f"Issue {number}",
        )

    first_page = list_issues(
        db_session, repository_id=repository.id, limit=2
    )
    second_page = list_issues(
        db_session, repository_id=repository.id, limit=2, offset=2
    )

    assert [issue.issue_number for issue in first_page] == [3, 2]
    assert [issue.issue_number for issue in second_page] == [1]


def test_repository_changes_rollback_without_persisting(db_session: Session):
    github_repo_id = make_github_repo_id()

    repository = upsert_repository(
        db_session,
        github_repo_id=github_repo_id,
        owner="inciflow-test",
        name="rollback",
        full_name=f"inciflow-test/{github_repo_id}",
    )
    repository_id = repository.id

    db_session.rollback()

    with Session(get_engine()) as verification_session:
        persisted = verification_session.scalar(
            select(Repository).where(
                Repository.github_repo_id == github_repo_id
            )
        )

    assert persisted is None

    # Ensure the test does not accidentally leave issue rows behind.
    with Session(get_engine()) as verification_session:
        persisted_issue = verification_session.scalar(
            select(Issue).where(Issue.repository_id == repository_id)
        )
    assert persisted_issue is None


def test_ingestion_rolls_back_entire_snapshot_on_database_conflict() -> None:
    """A later issue conflict must roll back all writes in the snapshot."""
    from sqlalchemy import delete, select
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession

    from inciflow.ingestion.schemas import IssueIngest, RepositoryIngest
    from inciflow.ingestion.service import ingest_repository_snapshot
    from inciflow.persistence.repositories.issues import upsert_issue

    if settings.database_name != "inciflow_test":
        pytest.skip("PostgreSQL integration tests require inciflow_test.")

    engine = get_engine()
    with engine.connect() as connection:
        actual_database = connection.scalar(text("SELECT current_database()"))

    if actual_database != "inciflow_test":
        pytest.fail("Safety check failed: connected to a non-test database.")

    github_repo_id = make_github_repo_id()
    baseline_issue_id = make_github_repo_id()
    first_new_issue_id = make_github_repo_id()
    conflicting_issue_id = make_github_repo_id()

    original_name = f"repo-{github_repo_id}"
    original_full_name = f"rollback-test/{original_name}"

    try:
        with OrmSession(engine) as setup_session:
            repository = upsert_repository(
                setup_session,
                github_repo_id=github_repo_id,
                owner="rollback-test",
                name=original_name,
                full_name=original_full_name,
                default_branch="main",
            )
            upsert_issue(
                setup_session,
                repository_id=repository.id,
                github_issue_id=baseline_issue_id,
                issue_number=1,
                title="Existing baseline issue",
                state="open",
            )
            setup_session.commit()

        repository_payload = RepositoryIngest(
            github_repo_id=github_repo_id,
            owner="rollback-test",
            name=f"renamed-{github_repo_id}",
            full_name=f"rollback-test/renamed-{github_repo_id}",
            default_branch="develop",
        )

        issue_payloads = [
            IssueIngest(
                github_issue_id=first_new_issue_id,
                issue_number=2,
                title="New issue that must be rolled back",
                state="open",
            ),
            IssueIngest(
                github_issue_id=conflicting_issue_id,
                issue_number=1,
                title="Conflicting issue number",
                state="open",
            ),
        ]

        with OrmSession(engine) as ingestion_session, pytest.raises(IntegrityError):
            ingest_repository_snapshot(
                ingestion_session,
                repository_data=repository_payload,
                issues=issue_payloads,
            )

        with OrmSession(engine) as verification_session:
            repository = verification_session.scalar(
                select(Repository).where(
                    Repository.github_repo_id == github_repo_id
                )
            )
            assert repository is not None
            assert repository.name == original_name
            assert repository.full_name == original_full_name
            assert repository.default_branch == "main"

            persisted_issues = list(
                verification_session.scalars(
                    select(Issue)
                    .where(Issue.repository_id == repository.id)
                    .order_by(Issue.issue_number)
                ).all()
            )

            assert [
                (issue.issue_number, issue.title)
                for issue in persisted_issues
            ] == [(1, "Existing baseline issue")]

    finally:
        with OrmSession(engine) as cleanup_session:
            repository = cleanup_session.scalar(
                select(Repository).where(
                    Repository.github_repo_id == github_repo_id
                )
            )
            if repository is not None:
                cleanup_session.execute(
                    delete(Issue).where(
                        Issue.repository_id == repository.id
                    )
                )
                cleanup_session.delete(repository)
                cleanup_session.commit()
