"""Integration tests for Organization, Subscription, Usage, and BYOK operations.

Tests organization API endpoints, subscription API endpoints, usage domain
operations, membership domain operations, and BYOK flag management.

Findings: T-5 (BYOKKey), T-6 (Organization/OrganizationMember), T-9 (Usage operations)
"""

import pytest
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.integration.conftest import get_admin_session
from app.domain.organization_operations import (
    OrganizationOperations,
    OrganizationMemberOperations,
)
from app.domain.usage_operations import UsageOperations
from app.domain.subscription_operations import SubscriptionOperations
from app.domain.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    EntityNotFoundError,
)
from app.models.database.organization import (
    OrganizationCreate,
    OrganizationMemberCreate,
    MemberRole,
)
from app.models.database.subscription import SubscriptionCreate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_org(test_context: dict):
    """
    Create a temporary organization for domain mutation tests.

    Includes owner membership for test user. Cleaned up after test.
    """
    admin = get_admin_session()
    try:
        org = OrganizationOperations.create(
            admin,
            OrganizationCreate(name="Phase5 Temp Org"),
            owner_user_id=test_context["user_id"],
        )
        # Create subscription + usage counter for the temp org
        sub = SubscriptionOperations.create(
            admin,
            SubscriptionCreate(organization_id=org.id, plan_tier="free"),
        )
        counter = UsageOperations.get_or_create_counter(admin, org.id)
        admin.commit()
        yield {
            "org_id": org.id,
            "org_name": org.name,
            "org_slug": org.slug,
            "subscription_id": sub.id,
            "counter_id": counter.id,
        }
    finally:
        admin.close()

    # Teardown: delete temp org data (FK-safe order)
    cleanup = get_admin_session()
    try:
        org_id = str(org.id)
        for table in [
            "billing_events",
            "usage_periods",
            "usage_counters",
            "byok_keys",
            "subscriptions",
            "organization_members",
            "organizations",
        ]:
            cleanup.execute(
                text(f"DELETE FROM {table} WHERE {'organization_id' if table != 'organizations' else 'id'} = :oid"),
                {"oid": org_id},
            )
        cleanup.commit()
    except Exception:
        cleanup.rollback()
    finally:
        cleanup.close()


# ===========================================================================
# API Tests: Organization Endpoints
# ===========================================================================

class TestGetMyOrganization:
    """Tests for GET /api/organizations/me."""

    def test_returns_org_data(self, client: TestClient):
        """Returns primary organization with standard fields."""
        response = client.get("/api/organizations/me")
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "name" in data
        assert "slug" in data

    def test_includes_user_role(self, client: TestClient):
        """Response includes user_role field."""
        response = client.get("/api/organizations/me")
        assert response.status_code == 200
        data = response.json()
        assert "user_role" in data
        assert data["user_role"] in ("owner", "admin", "member")


class TestListOrganizations:
    """Tests for GET /api/organizations."""

    def test_returns_list(self, client: TestClient):
        """Returns at least one organization."""
        response = client.get("/api/organizations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_each_includes_role(self, client: TestClient):
        """Each org in list includes user_role."""
        response = client.get("/api/organizations")
        assert response.status_code == 200
        for org in response.json():
            assert "user_role" in org


class TestGetOrganizationById:
    """Tests for GET /api/organizations/{org_id}."""

    def test_get_by_id_success(self, client: TestClient, test_context: dict):
        """Get org by ID returns data for member."""
        org_id = str(test_context["org_id"])
        response = client.get(f"/api/organizations/{org_id}")
        assert response.status_code == 200
        assert response.json()["id"] == org_id

    def test_get_nonmember_org_forbidden(self, client: TestClient):
        """Non-member gets 403."""
        fake_id = str(uuid4())
        response = client.get(f"/api/organizations/{fake_id}")
        assert response.status_code == 403


class TestUpdateOrganization:
    """Tests for PATCH /api/organizations/{org_id}."""

    def test_update_org_name(self, client: TestClient, test_context: dict):
        """Owner can update org name."""
        org_id = str(test_context["org_id"])
        # Read current name
        current = client.get(f"/api/organizations/{org_id}").json()
        original_name = current["name"]

        # Update
        response = client.patch(
            f"/api/organizations/{org_id}",
            json={"name": "Updated Phase5 Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Phase5 Name"

        # Restore original name
        client.patch(f"/api/organizations/{org_id}", json={"name": original_name})

    def test_update_rejects_is_deleted(self, client: TestClient, test_context: dict):
        """Passing is_deleted via PATCH returns 400."""
        org_id = str(test_context["org_id"])
        response = client.patch(
            f"/api/organizations/{org_id}",
            json={"is_deleted": True},
        )
        assert response.status_code == 400


# ===========================================================================
# API Tests: Subscription Endpoints
# ===========================================================================

class TestSubscriptionEndpoints:
    """Tests for /api/subscriptions/* endpoints."""

    def test_get_subscription_me(self, client: TestClient):
        """GET /subscriptions/me returns subscription data."""
        response = client.get("/api/subscriptions/me")
        assert response.status_code == 200
        data = response.json()
        assert "plan_tier" in data
        assert "status" in data
        assert "organization_id" in data

    def test_get_usage_summary(self, client: TestClient):
        """GET /subscriptions/usage returns usage with limits."""
        response = client.get("/api/subscriptions/usage")
        assert response.status_code == 200
        data = response.json()
        assert "plan_tier" in data
        assert "events_created" in data
        assert "events_limit" in data
        assert "active_anima_count" in data

    def test_get_limits_all_resources(self, client: TestClient):
        """GET /subscriptions/limits returns all resource limits."""
        response = client.get("/api/subscriptions/limits")
        assert response.status_code == 200
        data = response.json()
        assert "plan_tier" in data
        assert "limits" in data
        limits = data["limits"]
        expected_resources = [
            "active_animas", "dormant_animas", "events",
            "memories", "knowledge", "pack_builds", "synthesis",
        ]
        for resource in expected_resources:
            assert resource in limits, f"Missing resource: {resource}"
            assert "current" in limits[resource]
            assert "limit" in limits[resource]
            assert "is_exceeded" in limits[resource]


# ===========================================================================
# Domain Tests: Organization Operations
# ===========================================================================

class TestOrganizationDomain:
    """Tests for OrganizationOperations domain methods."""

    def test_create_with_owner(self, test_context: dict):
        """Create org with owner_user_id adds owner membership."""
        admin = get_admin_session()
        try:
            org = OrganizationOperations.create(
                admin,
                OrganizationCreate(name="Domain Test Org"),
                owner_user_id=test_context["user_id"],
            )
            admin.flush()
            assert org.id is not None
            assert org.slug is not None

            # Owner membership created
            member = OrganizationMemberOperations.get_membership(
                admin, org.id, test_context["user_id"]
            )
            assert member is not None
            assert member.role == MemberRole.OWNER
        finally:
            admin.rollback()
            admin.close()

    def test_slug_generation(self):
        """Slug auto-generated from name."""
        admin = get_admin_session()
        try:
            org = OrganizationOperations.create(
                admin,
                OrganizationCreate(name="My Cool Org!"),
            )
            admin.flush()
            assert org.slug == "my-cool-org"
        finally:
            admin.rollback()
            admin.close()

    def test_slug_collision_appends_suffix(self):
        """Duplicate slug gets random suffix."""
        admin = get_admin_session()
        try:
            org1 = OrganizationOperations.create(
                admin, OrganizationCreate(name="Collision Test")
            )
            admin.flush()
            org2 = OrganizationOperations.create(
                admin, OrganizationCreate(name="Collision Test")
            )
            admin.flush()
            assert org1.slug != org2.slug
            assert org2.slug.startswith("collision-test-")
        finally:
            admin.rollback()
            admin.close()

    def test_get_primary_org_for_user(self, test_context: dict):
        """Returns user's primary org (owner org first)."""
        admin = get_admin_session()
        try:
            org = OrganizationOperations.get_primary_org_for_user(
                admin, test_context["user_id"]
            )
            assert org is not None
            assert org.id == test_context["org_id"]
        finally:
            admin.close()

    def test_get_by_slug(self, test_context: dict):
        """Get org by slug returns correct org."""
        admin = get_admin_session()
        try:
            # Get the org to find its slug
            org = OrganizationOperations.get_by_id(admin, test_context["org_id"])
            assert org is not None
            found = OrganizationOperations.get_by_slug(admin, org.slug)
            assert found is not None
            assert found.id == org.id
        finally:
            admin.close()

    def test_count_all(self):
        """count_all returns positive count."""
        admin = get_admin_session()
        try:
            count = OrganizationOperations.count_all(admin)
            assert count >= 1
        finally:
            admin.close()


# ===========================================================================
# Domain Tests: Membership Operations
# ===========================================================================

class TestMembershipDomain:
    """Tests for OrganizationMemberOperations domain methods."""

    def test_is_member(self, test_context: dict):
        """is_member returns True for existing member."""
        admin = get_admin_session()
        try:
            assert OrganizationMemberOperations.is_member(
                admin, test_context["org_id"], test_context["user_id"]
            ) is True
            assert OrganizationMemberOperations.is_member(
                admin, test_context["org_id"], uuid4()
            ) is False
        finally:
            admin.close()

    def test_is_owner_or_admin(self, test_context: dict):
        """is_owner_or_admin returns True for owner."""
        admin = get_admin_session()
        try:
            assert OrganizationMemberOperations.is_owner_or_admin(
                admin, test_context["org_id"], test_context["user_id"]
            ) is True
        finally:
            admin.close()

    def test_get_members_and_count(self, test_context: dict):
        """get_members returns list, count_members returns int."""
        admin = get_admin_session()
        try:
            members = OrganizationMemberOperations.get_members(
                admin, test_context["org_id"]
            )
            assert len(members) >= 1
            count = OrganizationMemberOperations.count_members(
                admin, test_context["org_id"]
            )
            assert count == len(members)
        finally:
            admin.close()

    def test_remove_last_owner_blocked(self, temp_org: dict, test_context: dict):
        """Cannot remove the last owner."""
        admin = get_admin_session()
        try:
            with pytest.raises(DomainValidationError, match="last owner"):
                OrganizationMemberOperations.remove_member(
                    admin, temp_org["org_id"], test_context["user_id"]
                )
        finally:
            admin.rollback()
            admin.close()

    def test_duplicate_member_blocked(self, temp_org: dict, test_context: dict):
        """Adding same user twice raises DuplicateEntityError."""
        admin = get_admin_session()
        try:
            with pytest.raises(DuplicateEntityError):
                OrganizationMemberOperations.add_member(
                    admin,
                    temp_org["org_id"],
                    OrganizationMemberCreate(
                        user_id=test_context["user_id"], role=MemberRole.MEMBER
                    ),
                )
        finally:
            admin.rollback()
            admin.close()


# ===========================================================================
# Domain Tests: Usage Operations
# ===========================================================================

class TestUsageDomain:
    """Tests for UsageOperations domain methods."""

    def test_get_or_create_counter(self, temp_org: dict):
        """get_or_create_counter returns existing counter."""
        admin = get_admin_session()
        try:
            counter = UsageOperations.get_or_create_counter(admin, temp_org["org_id"])
            assert counter is not None
            assert counter.organization_id == temp_org["org_id"]
            assert counter.events_created == 0
        finally:
            admin.close()

    def test_increment_counter(self, temp_org: dict):
        """increment_counter atomically increments field."""
        admin = get_admin_session()
        try:
            counter = UsageOperations.increment_counter(
                admin, temp_org["org_id"], "events_created", amount=5
            )
            admin.commit()
            assert counter.events_created == 5

            counter = UsageOperations.increment_counter(
                admin, temp_org["org_id"], "events_created", amount=3
            )
            admin.commit()
            assert counter.events_created == 8
        finally:
            admin.close()

    def test_increment_invalid_field_raises(self, temp_org: dict):
        """increment_counter rejects invalid field names."""
        admin = get_admin_session()
        try:
            with pytest.raises(DomainValidationError, match="Invalid counter field"):
                UsageOperations.increment_counter(
                    admin, temp_org["org_id"], "invalid_field"
                )
        finally:
            admin.rollback()
            admin.close()

    def test_update_storage_counts(self, temp_org: dict):
        """update_storage_counts sets absolute values."""
        admin = get_admin_session()
        try:
            counter = UsageOperations.update_storage_counts(
                admin, temp_org["org_id"],
                memories=42,
                knowledge=7,
                vector_bytes=12288,
            )
            admin.commit()
            assert counter.memories_stored == 42
            assert counter.knowledge_items == 7
            assert counter.vector_storage_bytes == 12288
        finally:
            admin.close()

    def test_reset_counters(self, temp_org: dict):
        """reset_counters zeros cumulative fields, preserves storage."""
        admin = get_admin_session()
        try:
            # Set some values first
            UsageOperations.increment_counter(admin, temp_org["org_id"], "events_created", 100)
            UsageOperations.increment_counter(admin, temp_org["org_id"], "pack_builds", 10)
            UsageOperations.update_storage_counts(admin, temp_org["org_id"], memories=50)
            admin.commit()

            # Reset
            counter = UsageOperations.reset_counters(admin, temp_org["org_id"])
            admin.commit()

            assert counter.events_created == 0
            assert counter.pack_builds == 0
            assert counter.synthesis_runs == 0
            # Storage counts preserved
            assert counter.memories_stored == 50
        finally:
            admin.close()


# ===========================================================================
# Domain Tests: BYOK Flag Operations
# ===========================================================================

class TestBYOKFlags:
    """Tests for SubscriptionOperations.set_byok_flag()."""

    def test_set_openai_flag(self, temp_org: dict):
        """Setting openai BYOK flag updates subscription."""
        admin = get_admin_session()
        try:
            sub = SubscriptionOperations.set_byok_flag(
                admin, temp_org["org_id"], "openai", True
            )
            admin.commit()
            assert sub.byok_openai_key_set is True

            # Unset
            sub = SubscriptionOperations.set_byok_flag(
                admin, temp_org["org_id"], "openai", False
            )
            admin.commit()
            assert sub.byok_openai_key_set is False
        finally:
            admin.close()

    def test_set_anthropic_flag(self, temp_org: dict):
        """Setting anthropic BYOK flag updates subscription."""
        admin = get_admin_session()
        try:
            sub = SubscriptionOperations.set_byok_flag(
                admin, temp_org["org_id"], "anthropic", True
            )
            admin.commit()
            assert sub.byok_anthropic_key_set is True
        finally:
            admin.close()

    def test_invalid_provider_raises(self, temp_org: dict):
        """Invalid provider raises DomainValidationError."""
        admin = get_admin_session()
        try:
            with pytest.raises(DomainValidationError, match="Invalid BYOK provider"):
                SubscriptionOperations.set_byok_flag(
                    admin, temp_org["org_id"], "invalid_provider", True
                )
        finally:
            admin.rollback()
            admin.close()
