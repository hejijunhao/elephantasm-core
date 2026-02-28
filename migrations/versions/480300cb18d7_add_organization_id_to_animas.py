"""add_organization_id_to_animas

Revision ID: 480300cb18d7
Revises: 2fee1061c5be
Create Date: 2026-02-24 17:12:24.231430

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '480300cb18d7'
down_revision: Union[str, None] = '2fee1061c5be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable organization_id column with FK and index
    op.add_column('animas', sa.Column('organization_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_animas_organization_id'), 'animas', ['organization_id'], unique=False)
    op.create_foreign_key(
        'fk_animas_organization_id',
        'animas', 'organizations',
        ['organization_id'], ['id']
    )

    # 2. Backfill: set organization_id from user's owner-role org membership
    op.execute("""
        UPDATE animas a
        SET organization_id = (
            SELECT om.organization_id
            FROM organization_members om
            WHERE om.user_id = a.user_id
              AND om.role = 'owner'
            LIMIT 1
        )
        WHERE a.organization_id IS NULL
    """)

    # 3. Safety check: log any orphans that couldn't be backfilled
    #    (user has no owner-role membership — shouldn't happen with auto-provisioning)
    conn = op.get_bind()
    orphan_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM animas WHERE organization_id IS NULL")
    ).scalar()
    if orphan_count > 0:
        # Fallback: assign orphans to ANY org their user belongs to
        op.execute("""
            UPDATE animas a
            SET organization_id = (
                SELECT om.organization_id
                FROM organization_members om
                WHERE om.user_id = a.user_id
                LIMIT 1
            )
            WHERE a.organization_id IS NULL
        """)
        # Re-check after fallback
        remaining = conn.execute(
            sa.text("SELECT COUNT(*) FROM animas WHERE organization_id IS NULL")
        ).scalar()
        if remaining > 0:
            raise RuntimeError(
                f"{remaining} animas still have NULL organization_id after backfill. "
                "Manual intervention required before enforcing NOT NULL."
            )

    # 4. Enforce NOT NULL now that all rows are backfilled
    op.alter_column('animas', 'organization_id', nullable=False)


def downgrade() -> None:
    op.alter_column('animas', 'organization_id', nullable=True)
    op.drop_constraint('fk_animas_organization_id', 'animas', type_='foreignkey')
    op.drop_index(op.f('ix_animas_organization_id'), table_name='animas')
    op.drop_column('animas', 'organization_id')
