"""Identity model - emergent behavioral fingerprint for an Anima."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, Text, CheckConstraint, text
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

    Based on MBTI framework with spectrum values for nuanced representation.
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

    # MBTI Type (derived from spectrums or set directly)
    personality_type: Optional[PersonalityType] = Field(default=None, index=True)

    # Dimension Spectrums (0.0 to 1.0)
    # 0.0 = strong first pole, 1.0 = strong second pole
    energy_spectrum: Optional[float] = Field(default=None)       # E(0) ↔ I(1)
    information_spectrum: Optional[float] = Field(default=None)  # S(0) ↔ N(1)
    decision_spectrum: Optional[float] = Field(default=None)     # T(0) ↔ F(1)
    lifestyle_spectrum: Optional[float] = Field(default=None)    # J(0) ↔ P(1)

    # Extended Traits (JSONB for flexibility)
    traits: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))

    # Longform Descriptions
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    communication_style: Optional[str] = Field(default=None, sa_column=Column(Text))
    decision_patterns: Optional[str] = Field(default=None, sa_column=Column(Text))
    interaction_preferences: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Evolution Tracking
    confidence: Optional[float] = Field(default=None)
    last_assessed_at: Optional[datetime] = Field(default=None)
    assessment_count: int = Field(default=0)

    # Soft delete
    is_deleted: bool = Field(default=False)

    # Relationships
    anima: Optional["Anima"] = Relationship(back_populates="identity")
    audit_logs: list["IdentityAuditLog"] = Relationship(back_populates="identity")

    __table_args__ = (
        CheckConstraint(
            "energy_spectrum >= 0.0 AND energy_spectrum <= 1.0",
            name="ck_identity_energy_spectrum_range"
        ),
        CheckConstraint(
            "information_spectrum >= 0.0 AND information_spectrum <= 1.0",
            name="ck_identity_information_spectrum_range"
        ),
        CheckConstraint(
            "decision_spectrum >= 0.0 AND decision_spectrum <= 1.0",
            name="ck_identity_decision_spectrum_range"
        ),
        CheckConstraint(
            "lifestyle_spectrum >= 0.0 AND lifestyle_spectrum <= 1.0",
            name="ck_identity_lifestyle_spectrum_range"
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_identity_confidence_range"
        ),
    )

    def derive_type_from_spectrums(self) -> Optional[str]:
        """Derive MBTI type from spectrum values."""
        if None in [self.energy_spectrum, self.information_spectrum,
                    self.decision_spectrum, self.lifestyle_spectrum]:
            return None

        e_i = "I" if self.energy_spectrum > 0.5 else "E"
        s_n = "N" if self.information_spectrum > 0.5 else "S"
        t_f = "F" if self.decision_spectrum > 0.5 else "T"
        j_p = "P" if self.lifestyle_spectrum > 0.5 else "J"

        return f"{e_i}{s_n}{t_f}{j_p}"


# DTOs

class IdentityBase(SQLModel):
    """Shared fields for Identity operations."""
    personality_type: Optional[PersonalityType] = None
    energy_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    information_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    decision_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    lifestyle_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    traits: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    communication_style: Optional[str] = None
    decision_patterns: Optional[str] = None
    interaction_preferences: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class IdentityCreate(IdentityBase):
    """Data required to create an Identity. anima_id set separately."""
    pass


class IdentityRead(IdentityBase):
    """Data returned when reading an Identity."""
    id: UUID
    anima_id: UUID
    last_assessed_at: Optional[datetime]
    assessment_count: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class IdentityUpdate(SQLModel):
    """Fields that can be updated (partial update support)."""
    personality_type: Optional[PersonalityType] = None
    energy_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    information_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    decision_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    lifestyle_spectrum: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    traits: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    communication_style: Optional[str] = None
    decision_patterns: Optional[str] = None
    interaction_preferences: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class IdentityAssessment(SQLModel):
    """Payload for personality assessment submission."""
    personality_type: str = Field(max_length=4)
    spectrums: dict[str, float]  # energy, information, decision, lifestyle
    confidence: float = Field(ge=0.0, le=1.0)
    trigger_source: Optional[str] = None
