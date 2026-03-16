"""
Billing Scheduler

Daily job — processes ended billing periods and checks spending cap warnings.
Operates at org level (not per-anima like other schedulers).
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.core.database import get_cron_db_session
from app.domain.billing_job_operations import BillingJobOperations
from ..scheduler_base import SchedulerBase

logger = logging.getLogger(__name__)

# Run once daily
BILLING_JOB_INTERVAL_HOURS = 24


class BillingScheduler(SchedulerBase):
    """
    Billing workflow scheduler.

    Runs daily to:
    1. Process ended billing periods (snapshot + bill overages + reset counters)
    2. Check spending cap warnings for active subscriptions
    """

    @property
    def workflow_name(self) -> str:
        return "billing"

    @property
    def job_interval_hours(self) -> int:
        return BILLING_JOB_INTERVAL_HOURS

    async def execute_for_anima(self, anima_id: UUID) -> dict[str, Any]:
        """Not applicable — billing is org-scoped, not anima-scoped."""
        raise NotImplementedError("Billing operates at org level, not anima level")

    async def execute_for_all_animas(self) -> dict[str, Any]:
        """Process all ended billing periods and check spending caps."""
        # Cross-machine advisory lock (prevents double Stripe API calls)
        result = await self.execute_with_lock(self._execute_all_inner)
        if result is None:
            logger.info("Billing job skipped — another machine holds the lock")
            return {"skipped": True, "reason": "advisory_lock"}
        return result

    async def _execute_all_inner(self) -> dict[str, Any]:
        """Inner billing logic — runs under advisory lock."""
        run_start = datetime.now(timezone.utc)
        logger.info("Starting daily billing job")

        try:
            with get_cron_db_session() as session:
                # 1. Process ended periods (snapshot + bill + reset)
                results = BillingJobOperations.process_ended_periods(session)

                # 2. Check spending cap warnings
                warnings = BillingJobOperations.check_spending_cap_warnings(session)
                session.commit()

            self._last_run = run_start
            self._stats["total_runs"] += 1
            self._stats["successful_runs"] += 1

            summary = {
                "periods_processed": len(results),
                "periods_successful": sum(1 for r in results if r.get("success")),
                "periods_failed": sum(1 for r in results if not r.get("success")),
                "total_billed_cents": sum(
                    r.get("total_billed_cents", 0) for r in results if r.get("success")
                ),
                "warnings_issued": len(warnings),
                "run_time_seconds": (datetime.now(timezone.utc) - run_start).total_seconds(),
            }

            logger.info(
                f"Billing job complete: {summary['periods_processed']} periods, "
                f"${summary['total_billed_cents'] / 100:.2f} billed, "
                f"{summary['warnings_issued']} warnings"
            )

            return summary

        except Exception as e:
            self._stats["total_runs"] += 1
            self._stats["failed_runs"] += 1
            logger.error(f"Billing job failed: {e}", exc_info=True)
            return {
                "error": str(e),
                "periods_processed": 0,
                "run_time_seconds": (datetime.now(timezone.utc) - run_start).total_seconds(),
            }


# Singleton instance
_billing_scheduler: BillingScheduler | None = None


def get_billing_scheduler() -> BillingScheduler:
    """Get or create billing scheduler singleton."""
    global _billing_scheduler
    if _billing_scheduler is None:
        _billing_scheduler = BillingScheduler()
    return _billing_scheduler
