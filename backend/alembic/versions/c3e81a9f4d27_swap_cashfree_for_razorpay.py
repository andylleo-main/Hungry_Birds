"""Swap Cashfree for Razorpay, and make room for pay on delivery

Revision ID: c3e81a9f4d27
Revises: b7f0d2e51a48
Create Date: 2026-10-05

The gateway changed because Cashfree's onboarding could not be completed in time
for launch. Nothing about the money model changes with it - one payment row per
order, the status on orders.payment_status and nowhere else - so this is renames
and three new nullable columns rather than a reshaping.

**The cf_ columns are renamed, not recreated.** A rename keeps every existing row
and the unique index that protects it; dropping and adding would discard the ids
of orders that really were taken through Cashfree, which is history, not clutter.
For the same reason orders.payment_method is *not* backfilled: rows saying
"cashfree" were paid through Cashfree, and rewriting them would be a lie that
survives in the analytics. Only the default for new rows moves, to "online",
which is also gateway-neutral so the next swap does not need a third value.

payment_session_id goes. It held Cashfree's opaque checkout session; Razorpay
Checkout opens on the gateway order id plus the publishable key, both of which
are known without storing anything.

The three new columns belong to pay on delivery and are added here rather than in
their own revision so there is one migration to run on launch day, not two. All
three are nullable, so the release still running during Railway's pre-deploy
window is unaffected - it writes none of them, and an order with all three null
behaves exactly as it did.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3e81a9f4d27'
down_revision: Union[str, None] = 'b7f0d2e51a48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('payments', 'cf_order_id', new_column_name='gateway_order_id')
    op.alter_column('payments', 'cf_payment_id', new_column_name='gateway_payment_id')
    # Renaming a column does not rename the index over it, and the name is what
    # a later migration or a DBA reaches for.
    op.execute('ALTER INDEX ix_payments_cf_order_id RENAME TO ix_payments_gateway_order_id')

    op.drop_column('payments', 'payment_session_id')

    # New orders are "online" or "cod". Existing rows keep "cashfree".
    op.alter_column('orders', 'payment_method', server_default='online')

    # How a pay-on-delivery order was actually settled at the door: 'cash' or
    # 'upi'. Null for everything paid online, which is what tells the two apart
    # without a join.
    op.add_column('orders', sa.Column('collected_via', sa.String(length=8), nullable=True))

    # The Razorpay QR a rider is currently showing for this order. Indexed
    # because the qr_code.credited webhook arrives naming only the QR, and this
    # is the whole of the mapping back to an order.
    op.add_column('orders', sa.Column('cod_qr_id', sa.String(length=32), nullable=True))
    op.create_index('ix_orders_cod_qr_id', 'orders', ['cod_qr_id'])


def downgrade() -> None:
    op.drop_index('ix_orders_cod_qr_id', table_name='orders')
    op.drop_column('orders', 'cod_qr_id')
    op.drop_column('orders', 'collected_via')

    op.alter_column('orders', 'payment_method', server_default='cashfree')

    op.add_column('payments', sa.Column('payment_session_id', sa.String(length=512), nullable=True))

    op.execute('ALTER INDEX ix_payments_gateway_order_id RENAME TO ix_payments_cf_order_id')
    op.alter_column('payments', 'gateway_payment_id', new_column_name='cf_payment_id')
    op.alter_column('payments', 'gateway_order_id', new_column_name='cf_order_id')
