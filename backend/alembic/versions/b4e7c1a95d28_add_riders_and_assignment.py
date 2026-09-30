"""Add riders, order assignment, and the out-for-delivery status

Revision ID: b4e7c1a95d28
Revises: 8f2c41d9a7b3
Create Date: 2026-09-30

The ALTER TYPE below adds a value to order_status, which already exists. Postgres
allows that inside a transaction but forbids *using* the new value in the same
one, so nothing here references the literal 'out_for_delivery' in any DDL or
backfill - the application uses it at runtime, which is a different transaction.
alembic/env.py also runs one transaction per revision now, so a later revision
that does need the value is safe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b4e7c1a95d28'
down_revision: Union[str, None] = '8f2c41d9a7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'out_for_delivery'")

    op.create_table(
        'riders',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        # Unique across every stall, so signing in needs no "which stall?" step.
        sa.Column('login_id', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('credential_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_riders_vendor_id', 'riders', ['vendor_id'])
    op.create_index('ix_riders_login_id', 'riders', ['login_id'], unique=True)

    # SET NULL, not CASCADE: a rider leaving must not delete the history of every
    # order they carried.
    op.add_column(
        'orders',
        sa.Column('rider_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_orders_rider_id', 'orders', 'riders', ['rider_id'], ['id'], ondelete='SET NULL'
    )
    op.add_column(
        'orders',
        sa.Column('self_delivery', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        'ck_orders_one_courier',
        'orders',
        'NOT (rider_id IS NOT NULL AND self_delivery)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_orders_one_courier', 'orders', type_='check')
    op.drop_column('orders', 'self_delivery')
    op.drop_constraint('fk_orders_rider_id', 'orders', type_='foreignkey')
    op.drop_column('orders', 'rider_id')
    op.drop_index('ix_riders_login_id', table_name='riders')
    op.drop_index('ix_riders_vendor_id', table_name='riders')
    op.drop_table('riders')
    # Postgres has no ALTER TYPE ... DROP VALUE, so 'out_for_delivery' stays in
    # the enum. Harmless - nothing references it once the column is gone - and
    # stated rather than pretended away.
