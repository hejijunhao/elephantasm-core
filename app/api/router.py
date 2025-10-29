"""Main API router aggregation."""

from fastapi import APIRouter

from app.api.routes import events, health, memories, animas, memories_events, scheduler

api_router = APIRouter()

# Include route modules
api_router.include_router(health.router, tags=["health"])
api_router.include_router(events.router, tags=["events"])
api_router.include_router(animas.router, tags=["animas"])
api_router.include_router(memories.router, tags=["memories"])
api_router.include_router(memories_events.router, tags=["memories-events"])
api_router.include_router(scheduler.router, tags=["scheduler"])
