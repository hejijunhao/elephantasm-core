"""Domain operations for Synthesis Config - business logic layer.

CRUD operations for per-anima synthesis configuration.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from app.models.database.synthesis_config import SynthesisConfig, SynthesisConfigUpdate
from app.workflows.memory_synthesis.config import (
    TIME_WEIGHT,
    EVENT_WEIGHT,
    TOKEN_WEIGHT,
    SYNTHESIS_THRESHOLD,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    SYNTHESIS_JOB_INTERVAL_HOURS,
)


class SynthesisConfigOperations:
    """
    Synthesis Config business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def get_by_anima_id(
        session: Session,
        anima_id: UUID
    ) -> Optional[SynthesisConfig]:
        """
        Get synthesis config for anima.

        Returns:
            SynthesisConfig if exists, None otherwise
        """
        statement = select(SynthesisConfig).where(SynthesisConfig.anima_id == anima_id)
        return session.exec(statement).first()

    @staticmethod
    def get_or_create_default(
        session: Session,
        anima_id: UUID
    ) -> SynthesisConfig:
        """
        Get existing config or create with defaults from env vars.

        Auto-creates config on first access per anima.
        Uses env var defaults for backwards compatibility.

        Returns:
            SynthesisConfig (existing or newly created)
        """
        # Try to get existing
        config = SynthesisConfigOperations.get_by_anima_id(session, anima_id)

        if config:
            return config

        # Create with env var defaults
        config = SynthesisConfig(
            anima_id=anima_id,
            time_weight=TIME_WEIGHT,
            event_weight=EVENT_WEIGHT,
            token_weight=TOKEN_WEIGHT,
            threshold=SYNTHESIS_THRESHOLD,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            job_interval_hours=SYNTHESIS_JOB_INTERVAL_HOURS,
        )

        session.add(config)
        session.flush()
        session.refresh(config)

        return config

    @staticmethod
    def update(
        session: Session,
        anima_id: UUID,
        data: SynthesisConfigUpdate
    ) -> SynthesisConfig:
        """
        Update synthesis config for anima.

        Creates with defaults if doesn't exist.
        Only updates provided fields (partial update).

        Args:
            session: Database session
            anima_id: Anima UUID
            data: Update data (all fields optional)

        Returns:
            Updated SynthesisConfig

        Raises:
            ValueError: If anima doesn't exist
        """
        # Verify anima exists
        from app.domain.anima_operations import AnimaOperations
        anima = AnimaOperations.get_by_id(session, anima_id)
        if not anima:
            raise ValueError(f"Anima {anima_id} not found")

        # Get or create config
        config = SynthesisConfigOperations.get_or_create_default(session, anima_id)

        # Update provided fields
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(config, key, value)

        # Update timestamp
        config.updated_at = datetime.now(timezone.utc)

        session.add(config)
        session.flush()
        session.refresh(config)

        return config

    @staticmethod
    def delete(
        session: Session,
        anima_id: UUID
    ) -> bool:
        """
        Delete synthesis config for anima.

        Hard delete (no soft delete for config).
        Next access will recreate with defaults.

        Returns:
            True if deleted, False if not found
        """
        config = SynthesisConfigOperations.get_by_anima_id(session, anima_id)

        if not config:
            return False

        session.delete(config)
        session.flush()

        return True
