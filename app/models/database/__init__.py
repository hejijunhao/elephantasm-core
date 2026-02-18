"""Database models (OSS version) — import all models to ensure proper registration."""

from app.models.database.user import User
from app.models.database.animas import Anima
from app.models.database.events import Event
from app.models.database.memories import Memory
from app.models.database.memories_events import MemoryEvent
from app.models.database.synthesis_config import SynthesisConfig
from app.models.database.knowledge import Knowledge
from app.models.database.knowledge_audit_log import KnowledgeAuditLog
from app.models.database.identity import Identity
from app.models.database.identity_audit_log import IdentityAuditLog
from app.models.database.io_config import IOConfig
from app.models.database.memory_pack import MemoryPack
from app.models.database.dreams import DreamSession, DreamAction
from app.models.database.api_key import APIKey
from app.models.database.byok_keys import BYOKKey, BYOKProvider

__all__ = [
    "User",
    "Anima",
    "Event",
    "Memory",
    "MemoryEvent",
    "SynthesisConfig",
    "Knowledge",
    "KnowledgeAuditLog",
    "Identity",
    "IdentityAuditLog",
    "IOConfig",
    "MemoryPack",
    "DreamSession",
    "DreamAction",
    "APIKey",
    "BYOKKey",
    "BYOKProvider",
]
