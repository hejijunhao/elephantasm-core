"""BYOK (Bring Your Own Key) model - encrypted storage for customer API keys."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.database.mixins.timestamp import TimestampMixin


class BYOKProvider(str, Enum):
    """Supported BYOK providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class BYOKKeyBase(SQLModel):
    """Shared fields for BYOKKey model."""
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    provider: str = Field(max_length=50, description="Provider: openai, anthropic")
    key_prefix: str = Field(max_length=20, description="First chars for identification (e.g., sk-proj-)")


class BYOKKey(BYOKKeyBase, TimestampMixin, table=True):
    """BYOK Key entity - encrypted storage for customer API keys.

    Security notes:
    - encrypted_key uses Fernet symmetric encryption
    - Key Encryption Key (KEK) stored in BYOK_ENCRYPTION_KEY env var
    - Keys decrypted only at point of use (LLM calls)
    - Consider migration to AWS Secrets Manager / GCP Secret Manager for production
    """
    __tablename__ = "byok_keys"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_byok_org_provider"),
    )

    id: UUID = Field(default=None, primary_key=True, sa_column_kwargs={"server_default": text("gen_random_uuid()")})

    # Encrypted key (Fernet symmetric encryption)
    encrypted_key: str = Field(description="Fernet-encrypted API key")


class BYOKKeyCreate(SQLModel):
    """Data required to create a BYOK key (key will be encrypted before storage)."""
    provider: str = Field(max_length=50)
    api_key: str = Field(description="Plain API key (will be encrypted)")


class BYOKKeyRead(SQLModel):
    """Data returned when reading a BYOK key (never returns the actual key)."""
    id: UUID
    organization_id: UUID
    provider: str
    key_prefix: str
    created_at: datetime
    updated_at: datetime


class BYOKKeyUpdate(SQLModel):
    """Fields that can be updated (replaces the key)."""
    api_key: str = Field(description="New plain API key (will be encrypted)")
