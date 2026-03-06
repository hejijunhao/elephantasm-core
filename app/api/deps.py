"""API dependencies (OSS version — no-op stubs for subscription/billing logic).

Core LTAM routes import RequireActionAllowed, FeatureGate, and SubscriptionContext.
This stub provides pass-through versions so those routes work without the
proprietary pricing/billing modules.
"""

from dataclasses import dataclass, field
from uuid import UUID

from fastapi import Depends
from sqlmodel import Session

from app.core.rls_dependencies import get_db_with_rls
from app.core.auth import require_current_user_id


@dataclass
class SubscriptionContext:
    """Minimal subscription context — OSS version (no billing)."""
    user_id: UUID
    org_id: UUID = field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000000"))


class FeatureGate:
    """No-op feature gate — all features enabled in OSS."""

    def __init__(self, feature: str):
        self.feature = feature

    async def __call__(self, **kwargs) -> bool:
        return True


class RequireActionAllowed:
    """No-op action limiter — all actions allowed in OSS.

    Returns a SubscriptionContext with the authenticated user_id.
    """

    def __init__(self, action: str):
        self.action = action

    async def __call__(
        self,
        user_id: UUID = Depends(require_current_user_id),
        db: Session = Depends(get_db_with_rls)
    ) -> SubscriptionContext:
        return SubscriptionContext(user_id=user_id)
