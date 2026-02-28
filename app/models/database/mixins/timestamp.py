"""Timestamp mixin for created_at and updated_at fields."""

from datetime import datetime, timezone
from sqlmodel import Field, SQLModel


class TimestampMixin(SQLModel):
    """Adds created_at and updated_at timestamps."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        description="When this record was created"
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
        description="When this record was last updated"
    )
