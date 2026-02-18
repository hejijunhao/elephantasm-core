"""Domain operations for Identity entity."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlmodel import select

from app.models.database.identity import (
    Identity,
    IdentityCreate,
    IdentityUpdate,
)


class IdentityOperations:
    """Domain operations for Identity entity (1:1 with Anima)."""

    @staticmethod
    def create(
        session: Session,
        anima_id: UUID,
        data: IdentityCreate
    ) -> Identity:
        """Create Identity for an Anima."""
        import logging
        logger = logging.getLogger(__name__)

        # Handle the self_/self field mapping
        create_data = data.model_dump(exclude_unset=True, by_alias=False)
        logger.info(f"[IdentityOperations.create] create_data={create_data}")

        identity = Identity(
            anima_id=anima_id,
            **create_data
        )
        logger.info(f"[IdentityOperations.create] identity.self_={identity.self_}")

        session.add(identity)
        session.flush()
        session.refresh(identity)

        logger.info(f"[IdentityOperations.create] after refresh identity.self_={identity.self_}")
        return identity

    @staticmethod
    def get_by_id(
        session: Session,
        identity_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Identity]:
        """Get Identity by ID."""
        stmt = select(Identity).where(Identity.id == identity_id)
        if not include_deleted:
            stmt = stmt.where(Identity.is_deleted == False)
        return session.exec(stmt).first()

    @staticmethod
    def get_by_anima_id(
        session: Session,
        anima_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Identity]:
        """Get Identity by Anima ID (1:1 relationship)."""
        stmt = select(Identity).where(Identity.anima_id == anima_id)
        if not include_deleted:
            stmt = stmt.where(Identity.is_deleted == False)
        return session.exec(stmt).first()

    @staticmethod
    def update(
        session: Session,
        identity_id: UUID,
        data: IdentityUpdate
    ) -> Identity:
        """Update Identity entry."""
        import logging
        logger = logging.getLogger(__name__)

        identity = IdentityOperations.get_by_id(session, identity_id)
        if not identity:
            raise ValueError(f"Identity {identity_id} not found")

        update_data = data.model_dump(exclude_unset=True, by_alias=False)
        logger.info(f"[IdentityOperations.update] update_data={update_data}")

        for key, value in update_data.items():
            logger.info(f"[IdentityOperations.update] setting {key}={value}")
            setattr(identity, key, value)

        logger.info(f"[IdentityOperations.update] identity.self_={identity.self_}")

        identity.updated_at = datetime.now(timezone.utc)
        session.add(identity)
        session.flush()
        session.refresh(identity)

        logger.info(f"[IdentityOperations.update] after refresh identity.self_={identity.self_}")
        return identity

    @staticmethod
    def soft_delete(session: Session, identity_id: UUID) -> Identity:
        """Soft delete Identity."""
        identity = IdentityOperations.get_by_id(session, identity_id)
        if not identity:
            raise ValueError(f"Identity {identity_id} not found")

        identity.is_deleted = True
        identity.updated_at = datetime.now(timezone.utc)
        session.add(identity)
        session.flush()
        session.refresh(identity)
        return identity

    @staticmethod
    def restore(session: Session, identity_id: UUID) -> Identity:
        """Restore soft-deleted Identity."""
        identity = IdentityOperations.get_by_id(session, identity_id, include_deleted=True)
        if not identity:
            raise ValueError(f"Identity {identity_id} not found")

        identity.is_deleted = False
        identity.updated_at = datetime.now(timezone.utc)
        session.add(identity)
        session.flush()
        session.refresh(identity)
        return identity

    @staticmethod
    def exists_for_anima(session: Session, anima_id: UUID) -> bool:
        """Check if Identity exists for an Anima."""
        stmt = select(Identity.id).where(
            Identity.anima_id == anima_id,
            Identity.is_deleted == False
        )
        return session.exec(stmt).first() is not None
