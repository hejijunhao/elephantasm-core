from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.core.database import get_db

router = APIRouter()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Full health check endpoint.

    Used by Fly.io load balancer for routing decisions.
    Verifies both application status and database connectivity.

    Returns:
        dict: Health status with timestamp and database connectivity check
    """
    try:
        # Test database connection with simple query
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": db_status
        }
    }


@router.get("/healthz")
async def healthz():
    """
    Simple liveness probe.

    Used for quick health checks without database load.
    Returns healthy if application is running.

    Returns:
        dict: Simple status indicator
    """
    return {"status": "healthy"}
