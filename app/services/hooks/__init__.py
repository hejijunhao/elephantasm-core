"""
Service Hooks.

Integration hooks that bridge different services and workflows.
"""

from .auto_knowledge_synthesis import trigger_auto_knowledge_synthesis
from .auto_meditation import trigger_auto_meditation_check

__all__ = ["trigger_auto_knowledge_synthesis", "trigger_auto_meditation_check"]
