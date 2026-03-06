from contextlib import asynccontextmanager
import os
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import settings
from app.domain.exceptions import (
    EntityNotFoundError,
    EntityDeletedError,
    DuplicateEntityError,
    DomainValidationError,
)
from app.core.logging_config import configure_logging
from app.services.scheduler import get_scheduler_orchestrator, get_memory_synthesis_scheduler, get_dreamer_scheduler
from app.middleware.rate_limit import get_rate_limiter, rate_limit_exceeded_handler
from app.middleware.host_restriction import HostRestrictionMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler.

    Manages scheduler infrastructure and workflow registration.
    """
    # Configure logging (reduce noise from polling endpoints)
    configure_logging()

    # Startup: Register workflows and start scheduler
    logger.info("FastAPI application starting up...")

    # Configure LangSmith tracing environment variables
    # LangChain/LangGraph SDK requires these to be set in os.environ
    if settings.LANGSMITH_TRACING:
        os.environ['LANGSMITH_TRACING'] = 'true'
        os.environ['LANGSMITH_API_KEY'] = settings.LANGSMITH_API_KEY
        os.environ['LANGSMITH_PROJECT'] = settings.LANGSMITH_PROJECT
        os.environ['LANGSMITH_ENDPOINT'] = settings.LANGSMITH_ENDPOINT
        logger.info(f"LangSmith tracing enabled (project: {settings.LANGSMITH_PROJECT})")
    else:
        # Ensure tracing is explicitly disabled
        os.environ['LANGSMITH_TRACING'] = 'false'
        logger.info("LangSmith tracing disabled")

    # Start background job schedulers (unless disabled via ENABLE_BACKGROUND_JOBS=false)
    scheduler = None
    if settings.ENABLE_BACKGROUND_JOBS:
        scheduler = get_scheduler_orchestrator()

        memory_synthesis = get_memory_synthesis_scheduler()
        await memory_synthesis.register()
        logger.info("Memory synthesis scheduler registered")

        dreamer = get_dreamer_scheduler()
        await dreamer.register()
        logger.info("Dreamer scheduler registered (12h interval)")

        await scheduler.start()
        logger.info("Scheduler started (all background jobs enabled)")
    else:
        logger.info("Background jobs DISABLED (ENABLE_BACKGROUND_JOBS=false)")

    yield  # Application runs

    # Shutdown: Stop scheduler if it was started
    logger.info("FastAPI application shutting down...")
    if scheduler:
        await scheduler.stop()
        logger.info("Scheduler orchestrator stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# Set up rate limiter
limiter = get_rate_limiter()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# Domain exception → HTTP response mapping
@app.exception_handler(EntityNotFoundError)
async def entity_not_found_handler(request: Request, exc: EntityNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(EntityDeletedError)
async def entity_deleted_handler(request: Request, exc: EntityDeletedError):
    return JSONResponse(status_code=410, content={"detail": str(exc)})


@app.exception_handler(DuplicateEntityError)
async def duplicate_entity_handler(request: Request, exc: DuplicateEntityError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(DomainValidationError)
async def domain_validation_handler(request: Request, exc: DomainValidationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Uppercase enum name -> dot-notation value (for enriching 422 hints)
_EVENT_TYPE_ALIASES = {
    "MESSAGE_IN": "message.in",
    "MESSAGE_OUT": "message.out",
    "TOOL_CALL": "tool.call",
    "TOOL_RESULT": "tool.result",
    "SYSTEM": "system",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Enrich enum validation errors with SDK-friendly hints."""
    errors = []
    for error in exc.errors():
        enriched = dict(error)

        # Enrich event_type enum errors with SDK-specific hints
        if (
            error.get("type") == "enum"
            and len(error.get("loc", [])) >= 1
            and error["loc"][-1] == "event_type"
        ):
            input_val = str(error.get("input", ""))
            alias = _EVENT_TYPE_ALIASES.get(input_val.upper())
            if alias:
                enriched["msg"] = (
                    f"Invalid event_type '{input_val}'. "
                    f"Expected dot-notation: '{alias}'. "
                    f"If using the Python SDK, pass EventType.{input_val.upper()} "
                    f"instead of the string \"{input_val}\"."
                )
            else:
                enriched["msg"] = (
                    f"Invalid event_type '{input_val}'. "
                    f"Expected one of: 'message.in', 'message.out', 'tool.call', "
                    f"'tool.result', 'system'."
                )

        errors.append(enriched)

    return JSONResponse(status_code=422, content={"detail": errors})


# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Host-based path restriction (SDK surface on api.elephantasm.com)
app.add_middleware(HostRestrictionMiddleware)

# Include API router
app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Elephantasm LTAM API",
        "version": settings.VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    # Custom log config to work with our filter
    # Must disable uvicorn's default config and let our lifespan event handle it
    log_config = uvicorn.config.LOGGING_CONFIG.copy()
    # Remove the access logger handler - we'll add our filtered one in lifespan
    log_config["loggers"]["uvicorn.access"] = {
        "handlers": [],  # Empty - handlers added by our filter in lifespan
        "level": "INFO",
        "propagate": False
    }

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config=log_config
    )
