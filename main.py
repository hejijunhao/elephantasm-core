from contextlib import asynccontextmanager
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.services.scheduler import get_scheduler_orchestrator, get_memory_synthesis_scheduler, get_dreamer_scheduler

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

    # Get shared scheduler orchestrator
    scheduler = get_scheduler_orchestrator()

    # Register all workflow schedulers
    memory_synthesis = get_memory_synthesis_scheduler()
    await memory_synthesis.register()
    logger.info("Memory synthesis scheduler registered")

    dreamer = get_dreamer_scheduler()
    await dreamer.register()
    logger.info("Dreamer scheduler registered (12h interval)")

    # Future workflow schedulers:
    # lesson_extraction = get_lesson_extraction_scheduler()
    # await lesson_extraction.register()
    # logger.info("Lesson extraction scheduler registered")

    # Start scheduler orchestrator (manages all workflows)
    await scheduler.start()
    logger.info("Scheduler orchestrator started (all workflow schedulers registered)")

    yield  # Application runs

    # Shutdown: Stop scheduler
    logger.info("FastAPI application shutting down...")
    await scheduler.stop()
    logger.info("Scheduler orchestrator stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
