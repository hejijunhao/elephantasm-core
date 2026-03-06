"""add api_keys table for SDK auth

Revision ID: 3d785f1392f2
Revises: 2e820e44ef7d
Create Date: 2026-01-11 22:53:13.385309

API Keys enable programmatic SDK access alongside JWT auth.
Key format: sk_live_<32-char-hex>
Only bcrypt hash stored; full key returned once at creation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision: str = '3d785f1392f2'
down_revision: Union[str, None] = '2e820e44ef7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create api_keys table
    op.create_table('api_keys',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('key_hash', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('key_prefix', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('request_count', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)

    # Enable RLS and create isolation policy
    op.execute("""
        ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

        -- Policy: Users can only access their own API keys
        CREATE POLICY api_keys_user_isolation ON api_keys
            FOR ALL
            USING (user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());

        COMMENT ON POLICY api_keys_user_isolation ON api_keys IS
        'Users can only access API keys where user_id matches current user';
    """)


def downgrade() -> None:
    # Drop RLS policy first
    op.execute("DROP POLICY IF EXISTS api_keys_user_isolation ON api_keys;")
    op.execute("ALTER TABLE api_keys DISABLE ROW LEVEL SECURITY;")

    # Drop table
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_table('api_keys')
