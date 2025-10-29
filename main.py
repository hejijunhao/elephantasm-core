from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.services.scheduler import get_scheduler_orchestrator, get_memory_synthesis_scheduler

import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler.

    Manages scheduler infrastructure and workflow registration.
    """
    # Startup: Register workflows and start scheduler
    logger.info("FastAPI application starting up...")

    # Get shared scheduler orchestrator
    scheduler = get_scheduler_orchestrator()

    # Register all workflow schedulers
    memory_synthesis = get_memory_synthesis_scheduler()
    await memory_synthesis.register()
    logger.info("Memory synthesis scheduler registered")

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
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
