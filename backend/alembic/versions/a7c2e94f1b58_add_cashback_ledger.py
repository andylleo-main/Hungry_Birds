"""Promotional cashback, as a ledger

Revision ID: a7c2e94f1b58
Revises: f1d6c4a82b39
Create Date: 2026-10-07

Two things: the ledger itself, and one column on orders.

`cashback_entries` is append-only. Nothing updates a row - a redemption that has
to be given back is another row with reason 'returned' - so the whole history of
a student's promotional credit is reconstructible, which matters because this is
the first feature in the project that *creates* money rather than moving money
somebody already owed.

The partial unique index is the idempotence. Earning fires on COMPLETED, which
both the stall's route and the rider's can reach, and returning fires when a
stall refuses - both re-enterable. The service checks in Python first for a good
answer; this is what makes it true under a race. Partial so it does not also
constrain redemptions, which one order has exactly one of today but which
nothing in the scheme says must stay that way.

`orders.cashback_applied` is **additive and defaulted**, like f1d6c4a82b39's
column, so the release still serving during Railway's pre-deploy window keeps
working: it writes none of this, and an order with 0 behaves exactly as orders
do now. Nothing is backfilled.

Note what this migration does **not** do: it does not touch `orders.total_amount`.
That stays the gross value of the food, which is what the stall is owed and what
nine analytics queries sum. What the customer actually pays is `total_amount -
cashback_applied`, exposed as `Order.amount_due`, because Hungry Birds funds the
discount rather than the stall.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7c2e94f1b58'
down_revision: Union[str, None] = 'f1d6c4a82b39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cashback_entries',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'user_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        # VARCHAR rather than Postgres enums, matching payments.status: adding a
        # kind or a reason later should be a code change, not an ALTER TYPE the
        # same transaction then cannot use.
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('reason', sa.String(16), nullable=False),
        # Signed: credits positive, redemptions negative.
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        # SET NULL, matching order_items.menu_item_id: deleting an order must not
        # delete the record of money a student holds.
        sa.Column(
            'order_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('orders.id', ondelete='SET NULL'),
            nullable=True,
        ),
        # Credits only. Frozen at the moment of earning from CASHBACK_EXPIRY_DAYS,
        # so changing that setting cannot retroactively kill or revive a balance
        # a student was already shown a date for.
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'uq_cashback_once_per_order_reason',
        'cashback_entries',
        ['order_id', 'reason'],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL AND reason IN ('earned', 'returned')"),
    )
    # The balance walk asks for one user's rows in order, on every checkout.
    op.create_index(
        'ix_cashback_user_created', 'cashback_entries', ['user_id', 'created_at']
    )

    op.add_column(
        'orders',
        sa.Column(
            'cashback_applied',
            sa.Numeric(10, 2),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade() -> None:
    op.drop_column('orders', 'cashback_applied')
    op.drop_index('ix_cashback_user_created', table_name='cashback_entries')
    op.drop_index('uq_cashback_once_per_order_reason', table_name='cashback_entries')
    op.drop_table('cashback_entries')
