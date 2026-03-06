"""schema_drift_fixes

Revision ID: e05ed4ca8053
Revises: b26e975c489d
Create Date: 2026-01-13 19:02:48.575894

Fixes schema drift detected between SQLModel definitions and database:
- Creates missing ix_org_member_user index on organization_members.user_id

Model-only fixes (no DB changes needed - models aligned to match existing DB):
- usage.py: vector_storage_bytes now uses BigInteger (matches DB BIGINT)
- dreams.py: DreamSession now defines ix_dream_sessions_started_at index
- dreams.py: DreamAction.session_id FK now specifies ondelete="CASCADE"

Ignored (externally managed):
- LangGraph checkpoint tables (checkpoint_*, checkpoints)
- pgVector IVFFlat indexes (ix_knowledge_embedding, ix_memories_embedding)
- TEXT vs AutoString type differences (functionally equivalent)
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e05ed4ca8053'
down_revision: Union[str, None] = 'b26e975c489d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create missing index on organization_members.user_id
    op.create_index('ix_org_member_user', 'organization_members', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_org_member_user', table_name='organization_members')
