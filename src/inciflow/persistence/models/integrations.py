"""Synchronization state for external integrations."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from inciflow.persistence.base import Base


class IntegrationSync(Base):
    __tablename__ = "integration_syncs"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="direction_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'synced', 'failed', 'conflict')",
            name="status_allowed",
        ),
        UniqueConstraint(
            "integration_name",
            "entity_type",
            "entity_id",
            "direction",
            name="uq_integration_sync_entity_direction",
        ),
        Index("ix_integration_syncs_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    integration_name: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    external_id: Mapped[str | None] = mapped_column(String(512))
    cursor_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
