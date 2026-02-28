"""
Dreamer Service - Memory Curation System

The Dreamer is Elephantasm's memory curation service — analogous to human sleep/dreaming.
It reviews, consolidates, and refines an Anima's memories through a self-governed process.

Main Components:
    DreamerService - Main orchestrator
    DreamerConfig - Configuration with sensible defaults
    run_dream_background - Entry point for FastAPI BackgroundTasks

Phases:
    1. Gather - Collect context (memories, identity, knowledge)
    2. Light Sleep - Algorithmic operations (decay, transitions, flagging)
    3. Deep Sleep - LLM-powered curation (merge, split, refine)
"""

from app.services.dreamer.config import DreamerConfig
from app.services.dreamer.deep_sleep import DeepSleepResults, run_deep_sleep
from app.services.dreamer.dreamer_service import DreamerService, run_dream_background
from app.services.dreamer.gather import DreamContext, gather_dream_context
from app.services.dreamer.light_sleep import LightSleepResults, run_light_sleep

__all__ = [
    # Main service
    "DreamerService",
    "run_dream_background",
    # Configuration
    "DreamerConfig",
    # Gather phase
    "DreamContext",
    "gather_dream_context",
    # Light Sleep phase
    "LightSleepResults",
    "run_light_sleep",
    # Deep Sleep phase
    "DeepSleepResults",
    "run_deep_sleep",
]
