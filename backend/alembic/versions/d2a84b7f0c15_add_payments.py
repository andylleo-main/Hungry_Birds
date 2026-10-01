"""Add online payments: payment status, Cashfree orders, and a webhook ledger

Revision ID: d2a84b7f0c15
Revises: c91f0a3e6d47
Create Date: 2026-10-01

The ALTER TYPE adds a value to order_status, which already exists. Postgres
allows that inside a transaction but refuses to let the *same* transaction use
it, so nothing here writes the literal 'awaiting_payment' - the backfill below
only reads existing rows. alembic/env.py also commits per revision, so a later
migration needing the value is safe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd2a84b7f0c15'
down_revision: Union[str, None] = 'c91f0a3e6d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'awaiting_payment' BEFORE 'placed'")

    # Every order that already exists was cash collected at the counter, so it is
    # paid. Defaulting these to 'pending' instead would hide the entire order
    # history from every stall queue the moment this deploys, because an unpaid
    # order is filtered out of it.
    op.add_column(
        'orders',
        sa.Column('payment_status', sa.String(length=20), nullable=False, server_default='paid'),
    )
    # New rows get their value from the application, which starts them pending.
    # The default above exists only to backfill, so it is dropped immediately -
    # left in place it would quietly mark a future insert as paid.
    op.alter_column('orders', 'payment_status', server_default=None)

    op.create_table(
        'payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('cf_order_id', sa.String(length=64), nullable=False),
        sa.Column('cf_payment_id', sa.String(length=64), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('payment_session_id', sa.String(length=512), nullable=True),
        sa.Column('refund_id', sa.String(length=64), nullable=True),
        sa.Column('refund_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id'),
    )
    op.create_index('ix_payments_cf_order_id', 'payments', ['cf_order_id'], unique=True)

    op.create_table(
        'payment_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('raw', postgresql.JSONB(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    # The idempotency guard itself. Unique, so a replayed webhook collides on
    # insert rather than being detected by a check somebody could forget.
    op.create_index('ix_payment_events_event_id', 'payment_events', ['event_id'], unique=True)

    # The sweep's index. Partial, so it stays near-empty: the rows it covers are
    # checkouts in flight, which exist for minutes.
    op.execute(
        "CREATE INDEX ix_orders_awaiting_payment ON orders (created_at)"
        " WHERE payment_status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_awaiting_payment")
    op.drop_index('ix_payment_events_event_id', table_name='payment_events')
    op.drop_table('payment_events')
    op.drop_index('ix_payments_cf_order_id', table_name='payments')
    op.drop_table('payments')
    op.drop_column('orders', 'payment_status')
    # Postgres has no ALTER TYPE ... DROP VALUE, so 'awaiting_payment' stays in
    # the enum. Harmless once no column references it, and stated rather than
    # pretended away.
