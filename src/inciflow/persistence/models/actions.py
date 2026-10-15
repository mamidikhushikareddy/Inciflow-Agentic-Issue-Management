"""Approved, idempotent actions against external systems."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from inciflow.persistence.base import Base


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('add_label', 'remove_label', 'add_comment', "
            "'close_issue', 'reopen_issue', 'assign_issue')",
            name="action_type_allowed",
        ),
        CheckConstraint(
            "status IN ('proposed', 'authorized', 'executing', 'succeeded', "
            "'failed', 'uncertain', 'cancelled')",
            name="status_allowed",
        ),
        Index("ix_actions_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("issues.id", ondelete="RESTRICT"),
        nullable=False,
    )
    resolution_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("resolution_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("approvals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    idempotency_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(1024))
    result_payload: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
