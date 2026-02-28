"""rename_spirits_to_animas

Revision ID: 5d828e895a4c
Revises: 4faf087cf25d
Create Date: 2025-10-26 13:38:40.310434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5d828e895a4c'
down_revision: Union[str, None] = '4faf087cf25d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Manually edited to preserve data via renames ###

    # Step 1: Rename the spirits table to animas
    op.rename_table('spirits', 'animas')

    # Step 2: Rename spirit_id column to anima_id in events table
    # Drop the foreign key first
    op.drop_constraint('events_spirit_id_fkey', 'events', type_='foreignkey')
    # Drop the index
    op.drop_index('ix_events_spirit_id', table_name='events')
    # Rename the column
    op.alter_column('events', 'spirit_id', new_column_name='anima_id')
    # Recreate the index with new name
    op.create_index(op.f('ix_events_anima_id'), 'events', ['anima_id'], unique=False)
    # Recreate the foreign key with new reference
    op.create_foreign_key('events_anima_id_fkey', 'events', 'animas', ['anima_id'], ['id'])

    # Step 3: Rename spirit_id column to anima_id in memories table
    # Drop the foreign key first
    op.drop_constraint('memories_spirit_id_fkey', 'memories', type_='foreignkey')
    # Drop the index
    op.drop_index('ix_memories_spirit_id', table_name='memories')
    # Rename the column
    op.alter_column('memories', 'spirit_id', new_column_name='anima_id')
    # Recreate the index with new name
    op.create_index(op.f('ix_memories_anima_id'), 'memories', ['anima_id'], unique=False)
    # Recreate the foreign key with new reference
    op.create_foreign_key('memories_anima_id_fkey', 'memories', 'animas', ['anima_id'], ['id'])
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### Manually edited to reverse renames ###

    # Step 1: Rename anima_id column back to spirit_id in memories table
    # Drop the foreign key first
    op.drop_constraint('memories_anima_id_fkey', 'memories', type_='foreignkey')
    # Drop the index
    op.drop_index(op.f('ix_memories_anima_id'), table_name='memories')
    # Rename the column
    op.alter_column('memories', 'anima_id', new_column_name='spirit_id')
    # Recreate the index with old name
    op.create_index('ix_memories_spirit_id', 'memories', ['spirit_id'], unique=False)
    # Recreate the foreign key with old reference
    op.create_foreign_key('memories_spirit_id_fkey', 'memories', 'spirits', ['spirit_id'], ['id'])

    # Step 2: Rename anima_id column back to spirit_id in events table
    # Drop the foreign key first
    op.drop_constraint('events_anima_id_fkey', 'events', type_='foreignkey')
    # Drop the index
    op.drop_index(op.f('ix_events_anima_id'), table_name='events')
    # Rename the column
    op.alter_column('events', 'anima_id', new_column_name='spirit_id')
    # Recreate the index with old name
    op.create_index('ix_events_spirit_id', 'events', ['spirit_id'], unique=False)
    # Recreate the foreign key with old reference
    op.create_foreign_key('events_spirit_id_fkey', 'events', 'spirits', ['spirit_id'], ['id'])

    # Step 3: Rename the animas table back to spirits
    op.rename_table('animas', 'spirits')
    # ### end Alembic commands ###
