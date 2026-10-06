"""Tell students how long their food will take

Revision ID: e5b71c93f8a2
Revises: d4a92b5e7c13
Create Date: 2026-10-06

Three nullable columns, no backfill.

menu_items.prep_minutes is the merchant's own estimate for one dish. Null means
nobody has said, not "instant" - a dish with no time is ignored when an order is
estimated, and an order whose dishes all lack one gets no estimate at all. That
is deliberate: showing nothing is honest, and inventing a number for a stall that
never filled this in is not. Which is also why nothing is backfilled here.

orders.prep_minutes and orders.ready_by snapshot what a customer was told, for
the same reason prices are snapshotted on order_items: a merchant editing a dish
tomorrow must not retroactively change what somebody was promised today.

Purely additive and all nullable, so the release still running during Railway's
pre-deploy window is unaffected - it writes none of them, and an order with all
three null behaves exactly as it does now.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5b71c93f8a2'
down_revision: Union[str, None] = 'd4a92b5e7c13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('menu_items', sa.Column('prep_minutes', sa.Integer(), nullable=True))
    op.add_column('orders', sa.Column('prep_minutes', sa.Integer(), nullable=True))
    op.add_column('orders', sa.Column('ready_by', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'ready_by')
    op.drop_column('orders', 'prep_minutes')
    op.drop_column('menu_items', 'prep_minutes')
