"""Organization API endpoints.

Endpoints for managing organizations and viewing membership.
Multi-tenant billing entities in Elephantasm.

Pattern: Async routes + Sync domain operations + RLS filtering.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session
from pydantic import BaseModel

from app.core.rls_dependencies import get_db_with_rls
from app.core.auth import require_current_user_id
from app.domain.organization_operations import (
    OrganizationOperations,
    OrganizationMemberOperations,
)
from app.models.database.organization import (
    Organization,
    OrganizationRead,
    OrganizationUpdate,
    OrganizationMember,
    MemberRole,
)


router = APIRouter(prefix="/organizations", tags=["organizations"])


# Extended response with user's role
class OrganizationWithRoleRead(OrganizationRead):
    """Organization data with user's membership role."""
    user_role: str | None = None  # owner, admin, member


@router.get(
    "/me",
    response_model=OrganizationWithRoleRead,
    summary="Get my primary organization"
)
async def get_my_organization(
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> OrganizationWithRoleRead:
    """
    Get current user's primary organization.

    Returns the first org where user is owner, or first membership if no owned orgs.
    Includes user's role in the organization.
    """
    org = OrganizationOperations.get_primary_org_for_user(db, user_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization found. Contact support."
        )

    # Get user's role
    membership = OrganizationMemberOperations.get_membership(db, org.id, user_id)
    role = membership.role if membership else None

    return OrganizationWithRoleRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        meta=org.meta,
        is_deleted=org.is_deleted,
        created_at=org.created_at,
        updated_at=org.updated_at,
        user_role=role,
    )


@router.get(
    "",
    response_model=List[OrganizationWithRoleRead],
    summary="List my organizations"
)
async def list_my_organizations(
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> List[OrganizationWithRoleRead]:
    """
    List all organizations user is a member of.

    Returns organizations sorted by creation date (newest first).
    Includes user's role in each organization.
    """
    orgs = OrganizationOperations.get_by_user(db, user_id)

    result = []
    for org in orgs:
        membership = OrganizationMemberOperations.get_membership(db, org.id, user_id)
        role = membership.role if membership else None

        result.append(OrganizationWithRoleRead(
            id=org.id,
            name=org.name,
            slug=org.slug,
            meta=org.meta,
            is_deleted=org.is_deleted,
            created_at=org.created_at,
            updated_at=org.updated_at,
            user_role=role,
        ))

    return result


@router.patch(
    "/{org_id}",
    response_model=OrganizationWithRoleRead,
    summary="Update organization"
)
async def update_organization(
    org_id: UUID,
    data: OrganizationUpdate,
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> OrganizationWithRoleRead:
    """
    Update organization (name, meta).

    Requires owner or admin role.
    Slug cannot be changed (URL stability).
    """
    # Check membership and role
    if not OrganizationMemberOperations.is_owner_or_admin(db, org_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and admins can update organization settings."
        )

    # Prevent changing is_deleted via this endpoint
    if data.is_deleted is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use dedicated delete/restore endpoints for deletion."
        )

    org = OrganizationOperations.update(db, org_id, data)

    # Get user's role
    membership = OrganizationMemberOperations.get_membership(db, org_id, user_id)
    role = membership.role if membership else None

    return OrganizationWithRoleRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        meta=org.meta,
        is_deleted=org.is_deleted,
        created_at=org.created_at,
        updated_at=org.updated_at,
        user_role=role,
    )


@router.get(
    "/{org_id}",
    response_model=OrganizationWithRoleRead,
    summary="Get organization by ID"
)
async def get_organization(
    org_id: UUID,
    user_id: UUID = Depends(require_current_user_id),
    db: Session = Depends(get_db_with_rls)
) -> OrganizationWithRoleRead:
    """
    Get organization by ID.

    User must be a member of the organization.
    """
    # Check membership
    if not OrganizationMemberOperations.is_member(db, org_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization."
        )

    org = OrganizationOperations.get_by_id(db, org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found."
        )

    # Get user's role
    membership = OrganizationMemberOperations.get_membership(db, org_id, user_id)
    role = membership.role if membership else None

    return OrganizationWithRoleRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        meta=org.meta,
        is_deleted=org.is_deleted,
        created_at=org.created_at,
        updated_at=org.updated_at,
        user_role=role,
    )
