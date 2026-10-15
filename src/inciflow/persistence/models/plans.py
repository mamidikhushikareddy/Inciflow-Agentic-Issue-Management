"""Versioned proposed resolutions for issues."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from inciflow.persistence.base import Base


class ResolutionPlan(Base):
    __tablename__ = "resolution_plans"
    __table_args__ = (
        UniqueConstraint("issue_id", "version", name="uq_resolution_plan_issue_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'approved', 'rejected', "
            "'stale', 'executing', 'completed', 'failed')",
            name="status_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("issues.id", ondelete="RESTRICT"),
        nullable=False,
    )
    triage_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("triage_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    plan_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(100), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
