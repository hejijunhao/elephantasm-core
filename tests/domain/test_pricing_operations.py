"""Tests for pricing domain operations.

Tests for OrganizationOperations, SubscriptionOperations, UsageOperations,
LimitOperations, and BillingEventOperations.

These tests use mocking to avoid database dependencies.
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.config.plans import get_plan, PLANS
from app.config.overages import calculate_overage_cost, OVERAGE_RATES
from app.domain.limit_operations import LimitOperations, LimitStatus, PlanLimitsSummary


class TestPlanConfig:
    """Tests for plan configuration."""

    def test_get_plan_free(self):
        """Test getting free plan."""
        plan = get_plan("free")
        assert plan.tier == "free"
        assert plan.price_monthly_cents == 0
        assert plan.active_anima_limit == 1
        assert plan.allows_overages is False

    def test_get_plan_pro(self):
        """Test getting pro plan."""
        plan = get_plan("pro")
        assert plan.tier == "pro"
        assert plan.price_monthly_cents == 3900
        assert plan.active_anima_limit == 10
        assert plan.allows_overages is True
        assert plan.dreamer_enabled is True

    def test_get_plan_team(self):
        """Test getting team plan."""
        plan = get_plan("team")
        assert plan.tier == "team"
        assert plan.price_monthly_cents == 24900
        assert plan.active_anima_limit == 50
        assert plan.audit_logs_enabled is True

    def test_get_plan_enterprise(self):
        """Test getting enterprise plan."""
        plan = get_plan("enterprise")
        assert plan.tier == "enterprise"
        assert plan.active_anima_limit == -1  # Unlimited
        assert plan.events_per_month == -1

    def test_get_plan_invalid(self):
        """Test getting invalid plan defaults to free."""
        plan = get_plan("invalid_tier")
        assert plan.tier == "free"

    def test_all_plans_exist(self):
        """Test all expected plans exist."""
        assert "free" in PLANS
        assert "pro" in PLANS
        assert "team" in PLANS
        assert "enterprise" in PLANS


class TestOverageCalculation:
    """Tests for overage cost calculation."""

    def test_calculate_overage_within_limit(self):
        """Test no overage when within limit."""
        cost = calculate_overage_cost(
            resource="events",
            usage=5000,
            limit=10000,
            plan_tier="pro"
        )
        assert cost == 0

    def test_calculate_overage_unlimited(self):
        """Test no overage for unlimited (-1)."""
        cost = calculate_overage_cost(
            resource="events",
            usage=1000000,
            limit=-1,
            plan_tier="pro"
        )
        assert cost == 0

    def test_calculate_overage_pro_tier(self):
        """Test overage calculation for pro tier."""
        # 15000 events over 10000 limit = 5000 overage
        # Event rate: $1.00 per 10000 = 100 cents
        # 5000 / 10000 = 0.5, ceiling = 1 unit
        cost = calculate_overage_cost(
            resource="events",
            usage=15000,
            limit=10000,
            plan_tier="pro"
        )
        # 1 unit * 100 cents = 100 cents
        assert cost == 100

    def test_calculate_overage_team_tier(self):
        """Test overage calculation for team tier (lower rates)."""
        cost = calculate_overage_cost(
            resource="events",
            usage=15000,
            limit=10000,
            plan_tier="team"
        )
        # 1 unit * 50 cents = 50 cents
        assert cost == 50

    def test_calculate_overage_free_tier(self):
        """Test free tier has no overages."""
        cost = calculate_overage_cost(
            resource="events",
            usage=15000,
            limit=10000,
            plan_tier="free"
        )
        assert cost == 0

    def test_calculate_overage_memories(self):
        """Test memory overage calculation."""
        # 1500 memories over 1000 limit = 500 overage
        # Memory rate: $2.00 per 1000 = 200 cents
        cost = calculate_overage_cost(
            resource="memories",
            usage=1500,
            limit=1000,
            plan_tier="pro"
        )
        # 1 unit * 200 cents = 200 cents
        assert cost == 200

    def test_calculate_overage_invalid_resource(self):
        """Test invalid resource returns 0."""
        cost = calculate_overage_cost(
            resource="invalid_resource",
            usage=15000,
            limit=10000,
            plan_tier="pro"
        )
        assert cost == 0


class TestLimitStatus:
    """Tests for LimitStatus dataclass."""

    def test_limit_status_within_limit(self):
        """Test limit status when within limit."""
        status = LimitOperations.check_limit(
            current=50,
            limit=100,
            resource="events",
            allows_overages=True,
            plan_tier="pro"
        )
        assert status.current == 50
        assert status.limit == 100
        assert status.is_exceeded is False
        assert status.overage_amount == 0
        assert status.overage_cost_cents == 0

    def test_limit_status_exceeded_with_overages(self):
        """Test limit status when exceeded with overages allowed."""
        status = LimitOperations.check_limit(
            current=150,
            limit=100,
            resource="events",
            allows_overages=True,
            plan_tier="pro"
        )
        assert status.is_exceeded is True
        assert status.overage_amount == 50
        assert status.overage_cost_cents > 0

    def test_limit_status_exceeded_no_overages(self):
        """Test limit status when exceeded without overages."""
        status = LimitOperations.check_limit(
            current=150,
            limit=100,
            resource="events",
            allows_overages=False,
            plan_tier="free"
        )
        assert status.is_exceeded is True
        assert status.allows_overages is False
        assert status.overage_cost_cents == 0

    def test_limit_status_unlimited(self):
        """Test limit status for unlimited (-1)."""
        status = LimitOperations.check_limit(
            current=1000000,
            limit=-1,
            resource="events",
            allows_overages=True,
            plan_tier="enterprise"
        )
        assert status.is_exceeded is False
        assert status.overage_amount == 0


class TestOverageRates:
    """Tests for overage rate configuration."""

    def test_all_resource_rates_exist(self):
        """Test all expected resource rates are configured."""
        assert "events" in OVERAGE_RATES
        assert "memories" in OVERAGE_RATES
        assert "knowledge" in OVERAGE_RATES
        assert "pack_builds" in OVERAGE_RATES
        assert "synthesis" in OVERAGE_RATES
        assert "vector_storage_gb" in OVERAGE_RATES

    def test_pro_rates_higher_than_team(self):
        """Test pro rates are higher than team rates."""
        for rate in OVERAGE_RATES.values():
            assert rate.pro_cents >= rate.team_cents

    def test_event_rate_structure(self):
        """Test event rate structure."""
        event_rate = OVERAGE_RATES["events"]
        assert event_rate.resource == "events"
        assert event_rate.unit_size == 10_000
        assert event_rate.pro_cents == 100  # $1.00 per 10K
        assert event_rate.team_cents == 50  # $0.50 per 10K


class TestLimitOperationsIntegration:
    """Integration-style tests for LimitOperations using mocks."""

    @patch('app.domain.subscription_operations.SubscriptionOperations.get_by_org')
    @patch('app.domain.usage_operations.UsageOperations.get_or_create_counter')
    def test_check_anima_limit(self, mock_get_counter, mock_get_sub):
        """Test checking anima limit."""
        session = MagicMock()
        org_id = uuid4()

        # Mock subscription
        mock_subscription = MagicMock()
        mock_subscription.plan_tier = "pro"
        mock_get_sub.return_value = mock_subscription

        # Mock usage counter
        mock_counter = MagicMock()
        mock_counter.active_anima_count = 5
        mock_get_counter.return_value = mock_counter

        status = LimitOperations.check_anima_limit(session, org_id)

        assert status.current == 5
        assert status.limit == 10  # Pro plan limit
        assert status.is_exceeded is False

    @patch('app.domain.subscription_operations.SubscriptionOperations.get_by_org')
    @patch('app.domain.usage_operations.UsageOperations.get_or_create_counter')
    def test_is_action_allowed_within_limit(self, mock_get_counter, mock_get_sub):
        """Test action is allowed when within limits."""
        session = MagicMock()
        org_id = uuid4()

        # Mock subscription
        mock_subscription = MagicMock()
        mock_subscription.plan_tier = "pro"
        mock_subscription.spending_cap_cents = -1  # No cap
        mock_get_sub.return_value = mock_subscription

        # Mock usage counter with low usage
        mock_counter = MagicMock()
        mock_counter.events_created = 1000
        mock_counter.active_anima_count = 1
        mock_counter.dormant_anima_count = 0
        mock_counter.memories_stored = 100
        mock_counter.knowledge_items = 10
        mock_counter.pack_builds = 50
        mock_counter.synthesis_runs = 10
        mock_get_counter.return_value = mock_counter

        allowed, error = LimitOperations.is_action_allowed(session, org_id, "create_event")

        assert allowed is True
        assert error is None

    @patch('app.domain.subscription_operations.SubscriptionOperations.get_by_org')
    @patch('app.domain.usage_operations.UsageOperations.get_or_create_counter')
    def test_is_action_blocked_free_tier_exceeded(self, mock_get_counter, mock_get_sub):
        """Test action is blocked when free tier limit exceeded."""
        session = MagicMock()
        org_id = uuid4()

        # Mock free tier subscription
        mock_subscription = MagicMock()
        mock_subscription.plan_tier = "free"
        mock_subscription.spending_cap_cents = -1
        mock_get_sub.return_value = mock_subscription

        # Mock usage counter with exceeded limit
        mock_counter = MagicMock()
        mock_counter.events_created = 2000  # Over 1000 limit
        mock_counter.active_anima_count = 0
        mock_counter.dormant_anima_count = 0
        mock_counter.memories_stored = 0
        mock_counter.knowledge_items = 0
        mock_counter.pack_builds = 0
        mock_counter.synthesis_runs = 0
        mock_get_counter.return_value = mock_counter

        allowed, error = LimitOperations.is_action_allowed(session, org_id, "create_event")

        assert allowed is False
        assert "limit" in error.lower()


class TestPlanLimitsSummary:
    """Tests for PlanLimitsSummary calculations."""

    def test_summary_no_overages(self):
        """Test summary with no overages."""
        limits = {
            "events": LimitStatus(
                resource="events",
                current=500,
                limit=1000,
                is_exceeded=False,
                allows_overages=False,
                overage_amount=0,
                overage_cost_cents=0
            )
        }
        summary = PlanLimitsSummary(
            plan_tier="free",
            limits=limits,
            total_overage_cents=0,
            spending_cap_cents=-1,
            spending_cap_remaining_cents=-1,
            is_hard_capped=False
        )
        assert summary.total_overage_cents == 0
        assert summary.is_hard_capped is False

    def test_summary_with_overages(self):
        """Test summary with overages."""
        limits = {
            "events": LimitStatus(
                resource="events",
                current=1500,
                limit=1000,
                is_exceeded=True,
                allows_overages=True,
                overage_amount=500,
                overage_cost_cents=100
            ),
            "memories": LimitStatus(
                resource="memories",
                current=200,
                limit=100,
                is_exceeded=True,
                allows_overages=True,
                overage_amount=100,
                overage_cost_cents=200
            )
        }
        summary = PlanLimitsSummary(
            plan_tier="pro",
            limits=limits,
            total_overage_cents=300,
            spending_cap_cents=500,
            spending_cap_remaining_cents=200,
            is_hard_capped=False
        )
        assert summary.total_overage_cents == 300
        assert summary.spending_cap_remaining_cents == 200

    def test_summary_hard_capped(self):
        """Test summary when hard capped (free tier exceeded)."""
        limits = {
            "events": LimitStatus(
                resource="events",
                current=1500,
                limit=1000,
                is_exceeded=True,
                allows_overages=False,
                overage_amount=500,
                overage_cost_cents=0
            )
        }
        summary = PlanLimitsSummary(
            plan_tier="free",
            limits=limits,
            total_overage_cents=0,
            spending_cap_cents=-1,
            spending_cap_remaining_cents=-1,
            is_hard_capped=True
        )
        assert summary.is_hard_capped is True
