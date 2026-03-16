"""add meditation_sessions meditation_actions and synthesis counter

Revision ID: 2a90299c4833
Revises: 3905e5ae481a
Create Date: 2026-03-16 10:49:00.892406

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2a90299c4833'
down_revision: Union[str, None] = '3905e5ae481a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- meditation_sessions table ---
    op.create_table('meditation_sessions',
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('anima_id', sa.Uuid(), nullable=False),
    sa.Column('trigger_type', sa.Enum('AUTO', 'MANUAL', name='meditationtriggertype'), nullable=False),
    sa.Column('triggered_by', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.Enum('RUNNING', 'COMPLETED', 'FAILED', name='meditationstatus'), nullable=False),
    sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('knowledge_reviewed', sa.Integer(), nullable=False),
    sa.Column('knowledge_modified', sa.Integer(), nullable=False),
    sa.Column('knowledge_created', sa.Integer(), nullable=False),
    sa.Column('knowledge_deleted', sa.Integer(), nullable=False),
    sa.Column('summary', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.ForeignKeyConstraint(['anima_id'], ['animas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meditation_sessions_anima_id'), 'meditation_sessions', ['anima_id'], unique=False)
    op.create_index('ix_meditation_sessions_started_at', 'meditation_sessions', [sa.text('started_at DESC')], unique=False)
    op.create_index(op.f('ix_meditation_sessions_status'), 'meditation_sessions', ['status'], unique=False)

    # --- meditation_actions table ---
    op.create_table('meditation_actions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('action_type', sa.Enum('MERGE', 'SPLIT', 'UPDATE', 'RECLASSIFY', 'DELETE', name='meditationactiontype'), nullable=False),
    sa.Column('phase', sa.Enum('REFLECTION', 'CONTEMPLATION', name='meditationphase'), nullable=False),
    sa.Column('source_knowledge_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
    sa.Column('result_knowledge_ids', postgresql.ARRAY(sa.UUID()), nullable=True),
    sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('after_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reasoning', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['meditation_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meditation_actions_action_type'), 'meditation_actions', ['action_type'], unique=False)
    op.create_index(op.f('ix_meditation_actions_session_id'), 'meditation_actions', ['session_id'], unique=False)

    # --- synthesis_configs: meditation counter + threshold ---
    op.add_column('synthesis_configs', sa.Column('knowledge_synth_count', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('synthesis_configs', sa.Column('meditation_threshold', sa.Integer(), nullable=False, server_default=sa.text('10')))

    # --- RLS policies (mirroring dream_sessions / dream_actions) ---
    op.execute("""
        ALTER TABLE meditation_sessions ENABLE ROW LEVEL SECURITY;

        CREATE POLICY meditation_sessions_via_anima_ownership ON meditation_sessions
            FOR ALL
            USING (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            )
            WITH CHECK (
                anima_id IN (
                    SELECT id FROM animas
                    WHERE user_id = app.current_user_id()
                    AND NOT is_deleted
                )
            );

        COMMENT ON POLICY meditation_sessions_via_anima_ownership ON meditation_sessions IS
        'Users can only access meditation sessions belonging to their animas';
    """)

    op.execute("""
        ALTER TABLE meditation_actions ENABLE ROW LEVEL SECURITY;

        CREATE POLICY meditation_actions_via_session_ownership ON meditation_actions
            FOR ALL
            USING (
                session_id IN (
                    SELECT ms.id FROM meditation_sessions ms
                    JOIN animas a ON ms.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            )
            WITH CHECK (
                session_id IN (
                    SELECT ms.id FROM meditation_sessions ms
                    JOIN animas a ON ms.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            );

        COMMENT ON POLICY meditation_actions_via_session_ownership ON meditation_actions IS
        'Users can only access meditation actions for their own meditation sessions';
    """)


def downgrade() -> None:
    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS meditation_actions_via_session_ownership ON meditation_actions;")
    op.execute("ALTER TABLE meditation_actions DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS meditation_sessions_via_anima_ownership ON meditation_sessions;")
    op.execute("ALTER TABLE meditation_sessions DISABLE ROW LEVEL SECURITY;")

    # Drop synthesis counter columns
    op.drop_column('synthesis_configs', 'meditation_threshold')
    op.drop_column('synthesis_configs', 'knowledge_synth_count')

    # Drop tables (actions first due to FK)
    op.drop_index(op.f('ix_meditation_actions_session_id'), table_name='meditation_actions')
    op.drop_index(op.f('ix_meditation_actions_action_type'), table_name='meditation_actions')
    op.drop_table('meditation_actions')
    op.drop_index(op.f('ix_meditation_sessions_status'), table_name='meditation_sessions')
    op.drop_index('ix_meditation_sessions_started_at', table_name='meditation_sessions')
    op.drop_index(op.f('ix_meditation_sessions_anima_id'), table_name='meditation_sessions')
    op.drop_table('meditation_sessions')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS meditationphase;")
    op.execute("DROP TYPE IF EXISTS meditationactiontype;")
    op.execute("DROP TYPE IF EXISTS meditationstatus;")
    op.execute("DROP TYPE IF EXISTS meditationtriggertype;")
