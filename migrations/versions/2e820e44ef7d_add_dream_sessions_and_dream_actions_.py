"""add dream_sessions and dream_actions tables

Revision ID: 2e820e44ef7d
Revises: 99550f0060a7
Create Date: 2026-01-08 13:02:13.567709

Dreamer Service Phase 1: Foundation tables with RLS policies.
- dream_sessions: Top-level dream cycle records
- dream_actions: Individual curation actions with audit trail
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2e820e44ef7d'
down_revision: Union[str, None] = '99550f0060a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. CREATE TABLES
    # ============================================================
    op.create_table('dream_sessions',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('anima_id', sa.Uuid(), nullable=False),
        sa.Column('trigger_type', sa.Enum('SCHEDULED', 'MANUAL', name='dreamtriggertype'), nullable=False),
        sa.Column('triggered_by', sa.Uuid(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.Enum('RUNNING', 'COMPLETED', 'FAILED', name='dreamstatus'), nullable=False),
        sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('memories_reviewed', sa.Integer(), nullable=False),
        sa.Column('memories_modified', sa.Integer(), nullable=False),
        sa.Column('memories_created', sa.Integer(), nullable=False),
        sa.Column('memories_archived', sa.Integer(), nullable=False),
        sa.Column('memories_deleted', sa.Integer(), nullable=False),
        sa.Column('summary', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('config_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(['anima_id'], ['animas.id'], ),
        sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dream_sessions_anima_id'), 'dream_sessions', ['anima_id'], unique=False)
    op.create_index(op.f('ix_dream_sessions_status'), 'dream_sessions', ['status'], unique=False)
    op.create_index('ix_dream_sessions_started_at', 'dream_sessions', [sa.text('started_at DESC')], unique=False)

    op.create_table('dream_actions',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('action_type', sa.Enum('MERGE', 'SPLIT', 'UPDATE', 'ARCHIVE', 'DELETE', name='dreamactiontype'), nullable=False),
        sa.Column('phase', sa.Enum('LIGHT_SLEEP', 'DEEP_SLEEP', name='dreamphase'), nullable=False),
        sa.Column('source_memory_ids', postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column('result_memory_ids', postgresql.ARRAY(sa.UUID()), nullable=True),
        sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('after_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('reasoning', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['dream_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dream_actions_action_type'), 'dream_actions', ['action_type'], unique=False)
    op.create_index(op.f('ix_dream_actions_session_id'), 'dream_actions', ['session_id'], unique=False)

    # ============================================================
    # 2. ENABLE RLS AND CREATE POLICIES
    # ============================================================
    op.execute("""
        -- Enable RLS on dream_sessions
        ALTER TABLE dream_sessions ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access dream sessions for their Animas
        CREATE POLICY dream_sessions_via_anima_ownership ON dream_sessions
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

        COMMENT ON POLICY dream_sessions_via_anima_ownership ON dream_sessions IS
        'Users can only access dream sessions belonging to their animas';
    """)

    op.execute("""
        -- Enable RLS on dream_actions
        ALTER TABLE dream_actions ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access dream actions via session ownership
        CREATE POLICY dream_actions_via_session_ownership ON dream_actions
            FOR ALL
            USING (
                session_id IN (
                    SELECT ds.id FROM dream_sessions ds
                    JOIN animas a ON ds.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            )
            WITH CHECK (
                session_id IN (
                    SELECT ds.id FROM dream_sessions ds
                    JOIN animas a ON ds.anima_id = a.id
                    WHERE a.user_id = app.current_user_id()
                    AND NOT a.is_deleted
                )
            );

        COMMENT ON POLICY dream_actions_via_session_ownership ON dream_actions IS
        'Users can only access dream actions for their own dream sessions';
    """)


def downgrade() -> None:
    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS dream_actions_via_session_ownership ON dream_actions;")
    op.execute("DROP POLICY IF EXISTS dream_sessions_via_anima_ownership ON dream_sessions;")

    # Disable RLS
    op.execute("ALTER TABLE dream_actions DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE dream_sessions DISABLE ROW LEVEL SECURITY;")

    # Drop indexes and tables
    op.drop_index(op.f('ix_dream_actions_session_id'), table_name='dream_actions')
    op.drop_index(op.f('ix_dream_actions_action_type'), table_name='dream_actions')
    op.drop_table('dream_actions')

    op.drop_index('ix_dream_sessions_started_at', table_name='dream_sessions')
    op.drop_index(op.f('ix_dream_sessions_status'), table_name='dream_sessions')
    op.drop_index(op.f('ix_dream_sessions_anima_id'), table_name='dream_sessions')
    op.drop_table('dream_sessions')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS dreamphase;")
    op.execute("DROP TYPE IF EXISTS dreamactiontype;")
    op.execute("DROP TYPE IF EXISTS dreamstatus;")
    op.execute("DROP TYPE IF EXISTS dreamtriggertype;")
