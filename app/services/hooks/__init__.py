"""
Service Hooks.

Integration hooks that bridge different services and workflows.
"""

from .auto_knowledge_synthesis import trigger_auto_knowledge_synthesis

__all__ = ["trigger_auto_knowledge_synthesis"]
