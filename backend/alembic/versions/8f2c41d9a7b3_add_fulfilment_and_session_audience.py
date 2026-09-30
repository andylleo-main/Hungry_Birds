"""Add fulfilment modes, delivery locations and session audience

Revision ID: 8f2c41d9a7b3
Revises: 26b72d73b4b5
Create Date: 2026-09-30

Creating the fulfilment_type enum and using it in the same revision is safe
because the type is *created* here. Postgres only refuses to use a value that
was added to a pre-existing type in the same transaction; a type born in the
transaction has no such restriction.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '8f2c41d9a7b3'
down_revision: Union[str, None] = '26b72d73b4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

fulfilment_type = postgresql.ENUM('dine_in', 'delivery', name='fulfilment_type')


def upgrade() -> None:
    fulfilment_type.create(op.get_bind(), checkfirst=True)

    # Both default to true so that every stall which already exists keeps
    # working: it could always be eaten at, and delivery is a capability being
    # offered rather than one a vendor must opt into before reappearing.
    op.add_column(
        'vendors',
        sa.Column('dine_in_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'vendors',
        sa.Column('delivery_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Existing orders become dine-in, which is exactly what they were - there was
    # no other kind - and leaves delivery_location NULL, satisfying the check
    # constraint below without a backfill.
    op.add_column(
        'orders',
        sa.Column(
            'fulfilment_type',
            postgresql.ENUM('dine_in', 'delivery', name='fulfilment_type', create_type=False),
            nullable=False,
            server_default='dine_in',
        ),
    )
    op.add_column('orders', sa.Column('delivery_location', sa.String(length=32), nullable=True))
    op.create_check_constraint(
        'ck_orders_delivery_location_matches_type',
        'orders',
        "(fulfilment_type = 'delivery' AND delivery_location IS NOT NULL)"
        " OR (fulfilment_type = 'dine_in' AND delivery_location IS NULL)",
    )

    # Only the locations a stall has switched OFF are stored, so "every location
    # on by default" needs no seeding here and no backfill for existing stalls.
    op.create_table(
        'vendor_disabled_locations',
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('vendor_id', 'code'),
    )

    # Nullable: sessions created before audiences existed have none, and
    # backfilling would mean guessing which app they came from.
    op.add_column('user_sessions', sa.Column('audience', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('user_sessions', 'audience')
    op.drop_table('vendor_disabled_locations')
    op.drop_constraint('ck_orders_delivery_location_matches_type', 'orders', type_='check')
    op.drop_column('orders', 'delivery_location')
    op.drop_column('orders', 'fulfilment_type')
    op.drop_column('vendors', 'delivery_enabled')
    op.drop_column('vendors', 'dine_in_enabled')
    fulfilment_type.drop(op.get_bind(), checkfirst=True)
