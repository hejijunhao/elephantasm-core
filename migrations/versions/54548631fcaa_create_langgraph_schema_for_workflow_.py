"""create langgraph schema for workflow infrastructure

Revision ID: 54548631fcaa
Revises: f699f48a6e39
Create Date: 2025-10-28 14:30:20.434132

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54548631fcaa'
down_revision: Union[str, None] = 'f699f48a6e39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create langgraph schema for workflow infrastructure.

    Separates LangGraph checkpoint tables from application domain models.
    Uses service_role (Supabase best practice) for runtime operations.
    Schema owned by postgres for administrative control.

    Post-migration: Run once outside Alembic:
        ALTER ROLE service_role SET search_path = langgraph, public;
    """
    SCHEMA = "langgraph"
    APP_ROLE = "service_role"
    SCHEMA_OWNER = "postgres"

    # 1) Create schema with documentation
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    op.execute(f"""
        COMMENT ON SCHEMA "{SCHEMA}" IS
        'LangGraph workflow infrastructure. Tables are created/managed by LangGraph (Postgres saver).'
    """)

    # 2) Keep postgres as owner for administrative control
    op.execute(f'ALTER SCHEMA "{SCHEMA}" OWNER TO {SCHEMA_OWNER}')

    # 3) Grant service_role ability to use + create objects in this schema
    op.execute(f'GRANT USAGE, CREATE ON SCHEMA "{SCHEMA}" TO {APP_ROLE}')

    # 4) Baseline grants on existing objects (harmless if empty)
    op.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA "{SCHEMA}" TO {APP_ROLE}')
    op.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA "{SCHEMA}" TO {APP_ROLE}')

    # 5) Default privileges for future objects created BY service_role
    op.execute(f'ALTER DEFAULT PRIVILEGES FOR ROLE {APP_ROLE} IN SCHEMA "{SCHEMA}" GRANT ALL ON TABLES TO {APP_ROLE}')
    op.execute(f'ALTER DEFAULT PRIVILEGES FOR ROLE {APP_ROLE} IN SCHEMA "{SCHEMA}" GRANT ALL ON SEQUENCES TO {APP_ROLE}')

    # 6) Security hardening: prevent random roles from creating objects
    op.execute(f'REVOKE CREATE ON SCHEMA "{SCHEMA}" FROM PUBLIC')


def downgrade() -> None:
    """
    Drop langgraph schema and all contained tables.

    WARNING: This will delete all workflow checkpoint data.
    """
    SCHEMA = "langgraph"
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
