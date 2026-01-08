"""Identity model - emergent behavioral fingerprint for an Anima."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from pydantic import model_serializer, model_validator
from sqlalchemy import Column, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, Relationship

from app.models.database.mixins.timestamp import TimestampMixin

if TYPE_CHECKING:
    from app.models.database.animas import Anima
    from app.models.database.identity_audit_log import IdentityAuditLog


class PersonalityType(str, Enum):
    """16 MBTI personality types."""
    ISTJ = "ISTJ"
    ISFJ = "ISFJ"
    INFJ = "INFJ"
    INTJ = "INTJ"
    ISTP = "ISTP"
    ISFP = "ISFP"
    INFP = "INFP"
    INTP = "INTP"
    ESTP = "ESTP"
    ESFP = "ESFP"
    ENFP = "ENFP"
    ENTP = "ENTP"
    ESTJ = "ESTJ"
    ESFJ = "ESFJ"
    ENFJ = "ENFJ"
    ENTJ = "ENTJ"


class Identity(TimestampMixin, SQLModel, table=True):
    """
    Emergent behavioral fingerprint for an Anima.

    Simplified model: personality_type + self (JSONB for Anima self-reflection).
    Tracks evolution over time via audit log.
    """
    __tablename__ = "identities"

    id: UUID = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")}
    )
    anima_id: UUID = Field(
        foreign_key="animas.id",
        unique=True,
        index=True,
        nullable=False
    )

    # MBTI Type
    personality_type: Optional[PersonalityType] = Field(default=None, index=True)

    # Self-reflection (JSONB) - updated by Anima via Dreamer loop
    # Example: {"essence": "...", "purpose": "...", "arc": "...", "non_negotiables": [...]}
    self_: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column("self", JSONB)
    )

    # Communication style (kept for response shaping)
    communication_style: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Soft delete
    is_deleted: bool = Field(default=False)

    # Relationships
    anima: Optional["Anima"] = Relationship(back_populates="identity")
    audit_logs: list["IdentityAuditLog"] = Relationship(back_populates="identity")


# DTOs
# Note: Using model_validator to accept "self" from JSON input and map to "self_",
# since SQLModel's Field(alias=...) doesn't work correctly with Pydantic v2


class IdentityBase(SQLModel):
    """Shared fields for Identity operations."""
    personality_type: Optional[PersonalityType] = None
    self_: Optional[dict[str, Any]] = Field(default=None)
    communication_style: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def map_self_field(cls, data: Any) -> Any:
        """Map 'self' key to 'self_' for compatibility with JSON input."""
        if isinstance(data, dict) and "self" in data and "self_" not in data:
            data["self_"] = data.pop("self")
        return data


class IdentityCreate(IdentityBase):
    """Data required to create an Identity. anima_id set separately."""
    pass


class IdentityRead(SQLModel):
    """Data returned when reading an Identity."""
    id: UUID
    anima_id: UUID
    personality_type: Optional[PersonalityType] = None
    self_: Optional[dict[str, Any]] = Field(default=None)
    communication_style: Optional[str] = None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def map_self_field(cls, data: Any) -> Any:
        """Map 'self' or ORM self_ attribute to self_ field."""
        if isinstance(data, dict) and "self" in data and "self_" not in data:
            data["self_"] = data.pop("self")
        return data

    @model_serializer(mode="wrap")
    def serialize_model(self, handler) -> dict[str, Any]:
        """Serialize 'self_' as 'self' for API responses."""
        result = handler(self)
        if "self_" in result:
            result["self"] = result.pop("self_")
        return result


class IdentityUpdate(SQLModel):
    """Fields that can be updated (partial update support)."""
    personality_type: Optional[PersonalityType] = None
    self_: Optional[dict[str, Any]] = Field(default=None)
    communication_style: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def map_self_field(cls, data: Any) -> Any:
        """Map 'self' key to 'self_' for compatibility with JSON input."""
        if isinstance(data, dict) and "self" in data and "self_" not in data:
            data["self_"] = data.pop("self")
        return data
