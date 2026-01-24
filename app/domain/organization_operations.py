"""Domain operations for Organizations - multi-tenant billing entities.

CRUD operations and business logic for Organizations and OrganizationMembers.
No transaction management - routes handle commits/rollbacks.

Pattern: Sync operations (FastAPI handles thread pool automatically).
"""

import re
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlmodel import Session
from fastapi import HTTPException

from app.models.database.organization import (
    Organization,
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
    MemberRole,
)
from app.models.database.user import User


class OrganizationOperations:
    """
    Organization business logic. Static methods, sync session-based, no commits.

    CRITICAL: All methods are SYNC (no async/await).
    FastAPI handles thread pool execution automatically.
    """

    @staticmethod
    def create(
        session: Session,
        data: OrganizationCreate,
        owner_user_id: UUID | None = None
    ) -> Organization:
        """
        Create organization with optional owner.

        If owner_user_id provided, auto-creates owner membership.

        Args:
            session: Database session
            data: Organization creation data
            owner_user_id: User to add as owner (optional)
        """
        # Generate slug if not provided
        slug = data.slug or OrganizationOperations._generate_slug(data.name)

        # Ensure slug uniqueness
        existing = OrganizationOperations.get_by_slug(session, slug)
        if existing:
            # Append random suffix
            import secrets
            slug = f"{slug}-{secrets.token_hex(3)}"

        org = Organization(
            name=data.name,
            slug=slug,
            meta=data.meta or {}
        )

        session.add(org)
        session.flush()

        # Add owner membership if user provided
        if owner_user_id:
            OrganizationMemberOperations.add_member(
                session,
                org.id,
                OrganizationMemberCreate(user_id=owner_user_id, role=MemberRole.OWNER)
            )

        return org

    @staticmethod
    def get_by_id(
        session: Session,
        org_id: UUID,
        include_deleted: bool = False
    ) -> Optional[Organization]:
        """Get organization by ID."""
        org = session.get(Organization, org_id)

        if org is None:
            return None

        if not include_deleted and org.is_deleted:
            return None

        return org

    @staticmethod
    def get_by_slug(
        session: Session,
        slug: str,
        include_deleted: bool = False
    ) -> Optional[Organization]:
        """Get organization by slug."""
        query = select(Organization).where(Organization.slug == slug)

        if not include_deleted:
            query = query.where(Organization.is_deleted.is_(False))

        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_by_user(
        session: Session,
        user_id: UUID,
        include_deleted: bool = False
    ) -> list[Organization]:
        """Get all organizations a user is a member of."""
        query = (
            select(Organization)
            .join(OrganizationMember)
            .where(OrganizationMember.user_id == user_id)
        )

        if not include_deleted:
            query = query.where(Organization.is_deleted.is_(False))

        query = query.order_by(Organization.created_at.desc())

        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def get_primary_org_for_user(
        session: Session,
        user_id: UUID
    ) -> Optional[Organization]:
        """Get user's primary organization (first org where they are owner).

        Falls back to first org they're a member of.
        """
        # First try to find org where user is owner
        query = (
            select(Organization)
            .join(OrganizationMember)
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.role == MemberRole.OWNER,
                Organization.is_deleted.is_(False)
            )
            .order_by(Organization.created_at.asc())
            .limit(1)
        )
        result = session.execute(query)
        org = result.scalar_one_or_none()

        if org:
            return org

        # Fall back to any membership
        orgs = OrganizationOperations.get_by_user(session, user_id)
        return orgs[0] if orgs else None

    @staticmethod
    def update(
        session: Session,
        org_id: UUID,
        data: OrganizationUpdate
    ) -> Organization:
        """Update organization (partial)."""
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(
                status_code=404,
                detail=f"Organization {org_id} not found"
            )

        update_dict = data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(org, key, value)

        session.add(org)
        session.flush()
        return org

    @staticmethod
    def soft_delete(session: Session, org_id: UUID) -> Organization:
        """Soft delete organization."""
        return OrganizationOperations.update(
            session, org_id, OrganizationUpdate(is_deleted=True)
        )

    @staticmethod
    def restore(session: Session, org_id: UUID) -> Organization:
        """Restore soft-deleted organization."""
        return OrganizationOperations.update(
            session, org_id, OrganizationUpdate(is_deleted=False)
        )

    @staticmethod
    def count_all(session: Session, include_deleted: bool = False) -> int:
        """Count total organizations."""
        query = select(func.count()).select_from(Organization)

        if not include_deleted:
            query = query.where(Organization.is_deleted.is_(False))

        result = session.execute(query)
        return result.scalar_one()

    @staticmethod
    def _generate_slug(name: str) -> str:
        """Generate URL-friendly slug from name."""
        # Lowercase and replace spaces/special chars with hyphens
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower())
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        # Truncate to max length
        return slug[:100] if slug else 'org'


class OrganizationMemberOperations:
    """
    OrganizationMember business logic.
    """

    @staticmethod
    def add_member(
        session: Session,
        org_id: UUID,
        data: OrganizationMemberCreate
    ) -> OrganizationMember:
        """Add a member to an organization."""
        # Check if already a member
        existing = OrganizationMemberOperations.get_membership(
            session, org_id, data.user_id
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"User {data.user_id} is already a member of organization {org_id}"
            )

        member = OrganizationMember(
            organization_id=org_id,
            user_id=data.user_id,
            role=data.role
        )

        session.add(member)
        session.flush()
        return member

    @staticmethod
    def get_membership(
        session: Session,
        org_id: UUID,
        user_id: UUID
    ) -> Optional[OrganizationMember]:
        """Get membership record for user in organization."""
        query = select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id
        )
        result = session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def get_members(
        session: Session,
        org_id: UUID
    ) -> list[OrganizationMember]:
        """Get all members of an organization."""
        query = (
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == org_id)
            .order_by(OrganizationMember.created_at.asc())
        )
        result = session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    def update_role(
        session: Session,
        org_id: UUID,
        user_id: UUID,
        new_role: str
    ) -> OrganizationMember:
        """Update member's role."""
        member = OrganizationMemberOperations.get_membership(session, org_id, user_id)
        if not member:
            raise HTTPException(
                status_code=404,
                detail=f"Membership not found for user {user_id} in org {org_id}"
            )

        member.role = new_role
        session.add(member)
        session.flush()
        return member

    @staticmethod
    def remove_member(
        session: Session,
        org_id: UUID,
        user_id: UUID
    ) -> bool:
        """Remove a member from organization. Returns True if removed."""
        member = OrganizationMemberOperations.get_membership(session, org_id, user_id)
        if not member:
            return False

        # Prevent removing last owner
        if member.role == MemberRole.OWNER:
            owners = OrganizationMemberOperations._count_owners(session, org_id)
            if owners <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last owner of an organization"
                )

        session.delete(member)
        session.flush()
        return True

    @staticmethod
    def is_member(
        session: Session,
        org_id: UUID,
        user_id: UUID
    ) -> bool:
        """Check if user is a member of organization."""
        return OrganizationMemberOperations.get_membership(session, org_id, user_id) is not None

    @staticmethod
    def is_owner_or_admin(
        session: Session,
        org_id: UUID,
        user_id: UUID
    ) -> bool:
        """Check if user is owner or admin of organization."""
        member = OrganizationMemberOperations.get_membership(session, org_id, user_id)
        if not member:
            return False
        return member.role in (MemberRole.OWNER, MemberRole.ADMIN)

    @staticmethod
    def _count_owners(session: Session, org_id: UUID) -> int:
        """Count owners in organization."""
        query = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == MemberRole.OWNER
            )
        )
        result = session.execute(query)
        return result.scalar_one()

    @staticmethod
    def count_members(session: Session, org_id: UUID) -> int:
        """Count total members in organization."""
        query = (
            select(func.count())
            .select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == org_id)
        )
        result = session.execute(query)
        return result.scalar_one()
