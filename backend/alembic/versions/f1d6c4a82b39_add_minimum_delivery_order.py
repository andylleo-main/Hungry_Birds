"""Let a stall set the smallest delivery it will cook for

Revision ID: f1d6c4a82b39
Revises: e5b71c93f8a2
Create Date: 2026-10-06

One column, with a server default, like 8f2c41d9a7b3 did for the two fulfilment
booleans. The default is what makes this safe to run while the previous release
is still serving: rows written by that release get Rs.100 without it knowing the
column exists, and nothing has to be backfilled afterwards.

**The default is not inert.** Every existing stall starts refusing deliveries
under Rs.100 the moment this is applied. That is what was asked for, and a stall
that wants none sets the figure to 0 from its own settings screen.

Delivery only. Dine-in has no minimum because there is nobody to send: a single
samosa eaten at the counter costs the stall nothing it was not already set up
for. So there is no second column, and nothing here touches dine-in.

Numeric(10, 2), matching orders.total_amount. A float minimum compared against a
Decimal basket is how a Rs.100 order gets refused for being Rs.99.999999.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f1d6c4a82b39'
down_revision: Union[str, None] = 'e5b71c93f8a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'vendors',
        sa.Column(
            'min_delivery_order',
            sa.Numeric(10, 2),
            nullable=False,
            server_default='100',
        ),
    )


def downgrade() -> None:
    op.drop_column('vendors', 'min_delivery_order')
