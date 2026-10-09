"""A coupon's value is credited as cashback, once per order

Revision ID: d2a8c5e7f013
Revises: c7f3a1b96d24
"""

import sqlalchemy as sa
from alembic import op

revision = "d2a8c5e7f013"
down_revision = "c7f3a1b96d24"
branch_labels = None
depends_on = None


def _recreate(reasons: str) -> None:
    op.drop_index("uq_cashback_once_per_order_reason", table_name="cashback_entries")
    op.create_index(
        "uq_cashback_once_per_order_reason",
        "cashback_entries",
        ["order_id", "reason"],
        unique=True,
        postgresql_where=sa.text(f"order_id IS NOT NULL AND reason IN ({reasons})"),
    )


def upgrade() -> None:
    _recreate("'earned', 'returned', 'coupon'")


def downgrade() -> None:
    _recreate("'earned', 'returned'")
