"""Custom logging configuration to reduce noise from polling endpoints."""

import logging
import os
from typing import Optional, Set


class SuppressPollingEndpointsFilter(logging.Filter):
    """Filter that suppresses access logs for frequently-polled endpoints."""

    SUPPRESSED_PATTERNS: Set[str] = {
        "/synthesis-status",
        "GET /api/events",
        "GET /api/memories/stats",
        "GET /api/memories",
        "GET /api/animas",
        "GET /api/knowledge",
        "OPTIONS /api/",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to suppress, True to keep."""

        status_code = self._extract_status_code(record)
        message: Optional[str] = None

        if status_code is None:
            # AccessFormatter builds "200 OK" later, so fall back to raw string
            message = record.getMessage()
            if " 200" not in message:
                return True
        elif status_code != 200:
            return True

        if message is None:
            message = record.getMessage()

        # Suppress if matches pattern
        for pattern in self.SUPPRESSED_PATTERNS:
            if pattern in message:
                return False

        return True

    @staticmethod
    def _extract_status_code(record: logging.LogRecord) -> Optional[int]:
        """Extract numeric status code from uvicorn access log record."""
        args = getattr(record, "args", None)
        if not args:
            return None

        status_candidate = args[-1]

        try:
            return int(status_candidate)
        except (TypeError, ValueError):
            return None


def configure_logging():
    """Configure application logging with polling suppression."""
    logger = logging.getLogger(__name__)

    # Add filter to uvicorn.access logger handlers (suppress polling 200s)
    access_logger = logging.getLogger("uvicorn.access")
    filter_instance = SuppressPollingEndpointsFilter()

    for handler in access_logger.handlers:
        handler.addFilter(filter_instance)

    # Suppress external library INFO/DEBUG logs (keep WARNING+)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # Enable verbose workflow logging (includes errors, warnings, info)
    logging.getLogger("app.workflows").setLevel(logging.DEBUG)
    logging.getLogger("app.services.llm").setLevel(logging.DEBUG)

    # Keep uvicorn error logging verbose
    logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)

    logger.info(
        f"✅ Logging configured: {len(SuppressPollingEndpointsFilter.SUPPRESSED_PATTERNS)} "
        "polling patterns suppressed, workflow logging verbose"
    )
