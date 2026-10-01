"""Add the handover code a customer gives a rider on delivery

Revision ID: e5c13d8a4b02
Revises: d2a84b7f0c15
Create Date: 2026-10-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5c13d8a4b02'
down_revision: Union[str, None] = 'd2a84b7f0c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, and no backfill. Dine-in orders never have one, and a delivery
    # already in flight when this deploys has nobody holding a code - giving it
    # one retroactively would mean a rider being asked for something the customer
    # was never told. Those complete without a code, which is what the handler
    # does when the column is null.
    op.add_column('orders', sa.Column('delivery_code', sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'delivery_code')
