"""Validated contracts for GitHub ingestion."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RepositoryIngest(BaseModel):
    """Normalized repository metadata received from GitHub."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    github_repo_id: int = Field(gt=0)
    owner: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=3, max_length=511)
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    is_active: bool = True

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        parts = value.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("full_name must use the owner/repository format.")
        return value


class IssueIngest(BaseModel):
    """Normalized issue metadata received from GitHub."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    github_issue_id: int = Field(gt=0)
    issue_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=1024)
    body: str | None = None
    state: Literal["open", "closed"]
    author_login: str | None = Field(default=None, max_length=255)
    labels: list[str] = Field(default_factory=list, max_length=100)
    created_at_github: datetime | None = None
    updated_at_github: datetime | None = None
    closed_at_github: datetime | None = None

    @field_validator(
        "created_at_github",
        "updated_at_github",
        "closed_at_github",
    )
    @classmethod
    def require_timezone_aware_timestamps(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("GitHub timestamps must include a timezone.")
        return value

class SnapshotIngest(BaseModel):
    """One repository and its current issue snapshot."""

    model_config = ConfigDict(extra="forbid")

    repository: RepositoryIngest
    issues: list[IssueIngest] = Field(max_length=500)


class IngestionResponse(BaseModel):
    """Public response for a successfully ingested snapshot."""

    repository_id: __import__("uuid").UUID
    issue_count: int = Field(ge=0)
    synced_at: datetime



class GitHubIssueBatch(BaseModel):
    """One bounded batch of issues and its checkpoint transition."""

    model_config = ConfigDict(extra="forbid")

    repository: RepositoryIngest
    issues: list[IssueIngest] = Field(max_length=500)
    expected_cursor_payload: dict[str, Any]
    cursor_payload: dict[str, Any]
    completed: bool
    watermark: datetime | None = None
