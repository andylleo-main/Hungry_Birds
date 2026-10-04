"""Add the order number a customer quotes and the token a stall calls out

Revision ID: a1c4e7b20d93
Revises: f3b92e5c1a67
Create Date: 2026-10-04

Two numbers, because they answer different questions. order_number is unique
across the platform forever and is what gets quoted on a support call or against
a refund. token_number is small, per stall, per day, and is what gets shouted
across a counter.

order_number is backfilled in creation order, so the oldest order is 000001.
Uniqueness comes from the sequence, not from the four random digits - which is
why the backfill can use plain random() for the tail without caring about
collisions, and why there is no retry loop in the application code either.

token_number and service_date are deliberately NOT backfilled. A historical
order has no token that anybody ever called out, and inventing one would print a
number on a reprint that was never said aloud. Same reasoning as
e5c13d8a4b02_add_delivery_code.

Note on the temporary server default: Railway runs this as a pre-deploy command
and only then swaps the application, so the previous release serves traffic
against this schema for a few seconds. A NOT NULL column with no default would
make every insert from that release fail. The default covers the window; it is
dropped in a later revision once the new code is the only thing writing orders.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c4e7b20d93'
down_revision: Union[str, None] = 'f3b92e5c1a67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS order_number_seq START 1")

    # Added nullable, backfilled, then tightened - the pattern d2a84b7f0c15 uses.
    # All three steps share this transaction, so a concurrent insert cannot land
    # in the gap between the backfill and the NOT NULL.
    op.add_column('orders', sa.Column('order_number', sa.String(length=16), nullable=True))

    op.execute(
        """
        WITH ordered AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn FROM orders
        )
        UPDATE orders o
           SET order_number = lpad(ordered.rn::text, 6, '0') || '-' ||
                              lpad((floor(random() * 10000))::int::text, 4, '0')
          FROM ordered
         WHERE ordered.id = o.id
        """
    )
    op.execute("SELECT setval('order_number_seq', GREATEST((SELECT count(*) FROM orders), 1))")

    op.alter_column(
        'orders',
        'order_number',
        nullable=False,
        # Temporary, for the pre-deploy window described in the docstring. The
        # shape matches generate_order_number so a row written by the old release
        # is indistinguishable from one written by the new one.
        server_default=sa.text(
            "lpad(nextval('order_number_seq')::text, 6, '0') || '-' ||"
            " lpad((floor(random() * 10000))::int::text, 4, '0')"
        ),
    )
    op.create_unique_constraint('uq_orders_order_number', 'orders', ['order_number'])

    op.add_column('orders', sa.Column('token_number', sa.Integer(), nullable=True))
    op.add_column('orders', sa.Column('service_date', sa.Date(), nullable=True))

    # Partial: historical orders and anything still awaiting payment are null,
    # and null is not a token anybody called out twice.
    op.execute(
        "CREATE UNIQUE INDEX uq_orders_vendor_day_token"
        " ON orders (vendor_id, service_date, token_number)"
        " WHERE token_number IS NOT NULL"
    )

    op.create_table(
        'vendor_token_counters',
        sa.Column('vendor_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service_date', sa.Date(), nullable=False),
        sa.Column('last_token', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('vendor_id', 'service_date'),
    )


def downgrade() -> None:
    # Dropping order_number destroys the numbers printed on every receipt handed
    # out so far. Re-running the upgrade afterwards renumbers from scratch, so a
    # customer quoting a slip from before the downgrade will quote a number that
    # now belongs to a different order. Irreversible in the way that matters.
    op.drop_table('vendor_token_counters')
    op.execute("DROP INDEX IF EXISTS uq_orders_vendor_day_token")
    op.drop_column('orders', 'service_date')
    op.drop_column('orders', 'token_number')
    op.drop_constraint('uq_orders_order_number', 'orders', type_='unique')
    op.drop_column('orders', 'order_number')
    op.execute("DROP SEQUENCE IF EXISTS order_number_seq")
