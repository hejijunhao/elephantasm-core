"""Domain operations for IOConfig - business logic layer.

CRUD operations for per-anima I/O configuration.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlmodel import Session, select

from app.models.database.io_config import (
    IOConfig,
    IOConfigUpdate,
    DEFAULT_READ_SETTINGS,
    DEFAULT_WRITE_SETTINGS,
)


def _deep_merge(base: dict, updates: dict) -> dict:
    """
    Deep merge updates into base dict.

    - Nested dicts are merged recursively
    - Lists and scalars are replaced entirely
    - None values in updates are preserved (explicit null)
    """
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class IOConfigOperations:
    """
    IOConfig business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def get_by_anima_id(
        session: Session,
        anima_id: UUID
    ) -> Optional[IOConfig]:
        """
        Get IOConfig for anima.

        Returns:
            IOConfig if exists, None otherwise
        """
        statement = select(IOConfig).where(IOConfig.anima_id == anima_id)
        return session.exec(statement).first()

    @staticmethod
    def get_or_create(
        session: Session,
        anima_id: UUID
    ) -> IOConfig:
        """
        Get existing config or create with defaults.

        Auto-creates config on first access per anima.
        Uses DEFAULT_READ_SETTINGS and DEFAULT_WRITE_SETTINGS.

        Returns:
            IOConfig (existing or newly created)
        """
        # Try to get existing
        config = IOConfigOperations.get_by_anima_id(session, anima_id)

        if config:
            return config

        # Create with defaults
        config = IOConfig(
            anima_id=anima_id,
            read_settings=DEFAULT_READ_SETTINGS.copy(),
            write_settings=DEFAULT_WRITE_SETTINGS.copy(),
        )

        session.add(config)
        session.flush()
        session.refresh(config)

        return config

    @staticmethod
    def update_read_settings(
        session: Session,
        anima_id: UUID,
        settings: dict[str, Any]
    ) -> IOConfig:
        """
        Update read (inbound) settings. Deep merges with existing.

        Creates config with defaults if doesn't exist.

        Args:
            session: Database session
            anima_id: Anima UUID
            settings: Partial read settings to merge

        Returns:
            Updated IOConfig

        Raises:
            ValueError: If anima doesn't exist
        """
        # Verify anima exists
        from app.domain.anima_operations import AnimaOperations
        anima = AnimaOperations.get_by_id(session, anima_id)
        if not anima:
            raise ValueError(f"Anima {anima_id} not found")

        # Get or create config
        config = IOConfigOperations.get_or_create(session, anima_id)

        # Deep merge settings
        config.read_settings = _deep_merge(config.read_settings, settings)
        config.updated_at = datetime.now(timezone.utc)

        session.add(config)
        session.flush()
        session.refresh(config)

        return config

    @staticmethod
    def update_write_settings(
        session: Session,
        anima_id: UUID,
        settings: dict[str, Any]
    ) -> IOConfig:
        """
        Update write (outbound) settings. Deep merges with existing.

        Creates config with defaults if doesn't exist.

        Args:
            session: Database session
            anima_id: Anima UUID
            settings: Partial write settings to merge

        Returns:
            Updated IOConfig

        Raises:
            ValueError: If anima doesn't exist
        """
        # Verify anima exists
        from app.domain.anima_operations import AnimaOperations
        anima = AnimaOperations.get_by_id(session, anima_id)
        if not anima:
            raise ValueError(f"Anima {anima_id} not found")

        # Get or create config
        config = IOConfigOperations.get_or_create(session, anima_id)

        # Deep merge settings
        config.write_settings = _deep_merge(config.write_settings, settings)
        config.updated_at = datetime.now(timezone.utc)

        session.add(config)
        session.flush()
        session.refresh(config)

        return config

    @staticmethod
    def update(
        session: Session,
        anima_id: UUID,
        data: IOConfigUpdate
    ) -> IOConfig:
        """
        Update IOConfig with partial data.

        Both read_settings and write_settings are deep merged.
        Creates config with defaults if doesn't exist.

        Args:
            session: Database session
            anima_id: Anima UUID
            data: Update data (all fields optional)

        Returns:
            Updated IOConfig

        Raises:
            ValueError: If anima doesn't exist
        """
        # Verify anima exists
        from app.domain.anima_operations import AnimaOperations
        anima = AnimaOperations.get_by_id(session, anima_id)
        if not anima:
            raise ValueError(f"Anima {anima_id} not found")

        # Get or create config
        config = IOConfigOperations.get_or_create(session, anima_id)

        # Deep merge provided settings
        if data.read_settings is not None:
            config.read_settings = _deep_merge(config.read_settings, data.read_settings)
        if data.write_settings is not None:
            config.write_settings = _deep_merge(config.write_settings, data.write_settings)

        config.updated_at = datetime.now(timezone.utc)

        session.add(config)
        session.flush()
        session.refresh(config)

        return config

    @staticmethod
    def reset_to_defaults(
        session: Session,
        anima_id: UUID
    ) -> IOConfig:
        """
        Reset IOConfig to default settings.

        Creates config if doesn't exist.

        Args:
            session: Database session
            anima_id: Anima UUID

        Returns:
            Reset IOConfig

        Raises:
            ValueError: If anima doesn't exist
        """
        # Verify anima exists
        from app.domain.anima_operations import AnimaOperations
        anima = AnimaOperations.get_by_id(session, anima_id)
        if not anima:
            raise ValueError(f"Anima {anima_id} not found")

        # Get or create config
        config = IOConfigOperations.get_or_create(session, anima_id)

        # Reset to defaults
        config.read_settings = DEFAULT_READ_SETTINGS.copy()
        config.write_settings = DEFAULT_WRITE_SETTINGS.copy()
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
        Delete IOConfig for anima.

        Hard delete (no soft delete for config).
        Next access will recreate with defaults.

        Returns:
            True if deleted, False if not found
        """
        config = IOConfigOperations.get_by_anima_id(session, anima_id)

        if not config:
            return False

        session.delete(config)
        session.flush()

        return True

    @staticmethod
    def get_defaults() -> dict[str, Any]:
        """
        Get default settings for UI reference.

        Returns:
            Dict with read_settings and write_settings defaults
        """
        return {
            "read_settings": DEFAULT_READ_SETTINGS.copy(),
            "write_settings": DEFAULT_WRITE_SETTINGS.copy(),
        }
