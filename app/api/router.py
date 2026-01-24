"""Main API router aggregation."""

from fastapi import APIRouter

from app.api.routes import events, health, memories, animas, memories_events, scheduler, synthesis_configs, knowledge, knowledge_synthesis, identities, packs, io_config, memory_packs, stats, users, dreams, api_keys, subscriptions, plans, organizations
from app.api.routes.admin import subscriptions as admin_subscriptions

api_router = APIRouter()

# Include route modules
api_router.include_router(health.router, tags=["health"])
api_router.include_router(events.router, tags=["events"])
api_router.include_router(animas.router, tags=["animas"])
api_router.include_router(memories.router, tags=["memories"])
api_router.include_router(memories_events.router, tags=["memories-events"])
api_router.include_router(knowledge.router, tags=["knowledge"])
api_router.include_router(knowledge_synthesis.router, tags=["knowledge-synthesis"])
api_router.include_router(synthesis_configs.router, tags=["synthesis-config"])
api_router.include_router(scheduler.router, tags=["scheduler"])
api_router.include_router(identities.router, tags=["identities"])
api_router.include_router(packs.router, prefix="/packs", tags=["packs"])
api_router.include_router(io_config.router, tags=["io-config"])
api_router.include_router(memory_packs.router, tags=["memory-packs"])
api_router.include_router(stats.router, tags=["stats"])
api_router.include_router(users.router, tags=["users"])
api_router.include_router(dreams.router, tags=["dreams"])
api_router.include_router(api_keys.router, tags=["api-keys"])

# Pricing & Subscription routes
api_router.include_router(subscriptions.router, tags=["subscriptions"])
api_router.include_router(plans.router, tags=["plans"])
api_router.include_router(admin_subscriptions.router, tags=["admin-subscriptions"])

# Organization routes
api_router.include_router(organizations.router, tags=["organizations"])
