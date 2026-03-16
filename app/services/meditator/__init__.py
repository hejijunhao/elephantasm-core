"""
Meditator Service - Knowledge Curation System

The Meditator is Elephantasm's knowledge curation service — analogous to the Dreamer
but for the Knowledge layer instead of Memories.
It reviews, consolidates, and refines an Anima's knowledge through a self-governed process.

Main Components:
    MeditatorService - Main orchestrator
    MeditatorConfig - Configuration with sensible defaults
    run_meditation_background - Entry point for FastAPI BackgroundTasks

Phases:
    1. Gather - Collect context (knowledge primary, memories context, identity)
    2. Reflection - Algorithmic operations (clustering + flagging only, no decay)
    3. Contemplation - LLM-powered curation (merge, split, update, reclassify, delete)
"""

from app.services.meditator.config import MeditatorConfig
from app.services.meditator.contemplation import ContemplationResults, run_contemplation
from app.services.meditator.gather import MeditationContext, gather_meditation_context
from app.services.meditator.meditator_service import MeditatorService, run_meditation_background
from app.services.meditator.reflection import ReflectionResults, run_reflection

__all__ = [
    # Main service
    "MeditatorService",
    "run_meditation_background",
    # Configuration
    "MeditatorConfig",
    # Gather phase
    "MeditationContext",
    "gather_meditation_context",
    # Reflection phase
    "ReflectionResults",
    "run_reflection",
    # Contemplation phase
    "ContemplationResults",
    "run_contemplation",
]
