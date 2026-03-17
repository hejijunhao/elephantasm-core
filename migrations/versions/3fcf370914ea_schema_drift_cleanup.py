"""schema_drift_cleanup

Drop orphan LangGraph checkpoint tables + fix animas.organization_id nullable.

1. Drop 4 orphan checkpoint tables from public schema — LangGraph's
   AsyncPostgresSaver created these with unqualified names. Migration
   3905e5ae481a only dropped the langgraph schema, not public.checkpoint*.
   No application code references these tables since v0.12.0.
2. Fix animas.organization_id to nullable=True — model declares UUID | None
   with ondelete="SET NULL", but DB column is NOT NULL (set by 480300cb18d7).
   The NOT NULL constraint is incompatible with the FK's ondelete="SET NULL".

Ignored drift (no-op, not worth migrating):
- TEXT vs AutoString on billing_events.description, byok_keys.encrypted_key,
  subscriptions.manual_assignment_note (PostgreSQL treats identically)
- VARCHAR(100) vs Enum on events.event_type (native_enum=False stores as
  VARCHAR anyway; changing risks breaking known name/value mismatch handling)

Revision ID: 3fcf370914ea
Revises: 3b1f4a5c6d7e
Create Date: 2026-03-17 09:05:12.963321

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3fcf370914ea'
down_revision: Union[str, None] = '3b1f4a5c6d7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop orphan LangGraph checkpoint tables from public schema
    op.drop_table('checkpoint_writes')
    op.drop_table('checkpoint_migrations')
    op.drop_table('checkpoints')
    op.drop_table('checkpoint_blobs')

    # 2. Fix animas.organization_id to match model (nullable=True)
    #    Required for ondelete="SET NULL" FK to function correctly
    op.alter_column('animas', 'organization_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('animas', 'organization_id',
               existing_type=sa.UUID(),
               nullable=False)
    # Checkpoint tables not recreated — LangGraph artifacts with no app code
