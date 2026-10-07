"""Discount codes, and the record of who spent one

Revision ID: b4e9d1c73a06
Revises: a7c2e94f1b58
Create Date: 2026-10-07

Three tables and one column.

`coupon_redemptions` is the interesting one. A use of a coupon is not a counter
going up: it is **held** when an order is placed, **consumed** when that order
completes, and **returned** when a stall refuses it or an admin hands it back.
Without the third state a refused order burns a one-use code on food nobody
received. It is deliberately the same shape as cashback_entries, so there is one
story about what a refusal undoes rather than two.

The number of uses a coupon has spent is **derived** from these rows and is not
stored anywhere. A stored counter drifts from the rows behind it the first time
anything goes wrong, and then needs a repair job that exists only because the
counter does.

There is deliberately **no unique index on (coupon_id, user_id)**. "One use per
customer" is a flag on the coupon, and a partial unique index cannot read another
table to find out whether it is set - so a coupon that allows repeat use would
have its second use rejected by the database with nothing able to explain why.
The row lock in hold_onto serialises every use of one code, which that rule needs
anyway, so it rides on a guarantee that already had to exist.

`orders.coupon_discount` is additive and defaulted, like the two money columns
before it, so the release still serving during Railway's pre-deploy window keeps
working - it writes none of this, and an order with 0 behaves as orders do now.
`total_amount` is untouched: it stays the gross the stall is owed, because Hungry
Birds funds the discount.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b4e9d1c73a06'
down_revision: Union[str, None] = 'a7c2e94f1b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'coupons',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(32), nullable=False, unique=True),
        # Null means every stall, which is the common case.
        sa.Column(
            'vendor_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('vendors.id', ondelete='CASCADE'),
            nullable=True,
        ),
        # VARCHAR rather than Postgres enums, matching payments.status: adding a
        # value later should be a code change, not an ALTER TYPE the same
        # transaction cannot then use.
        sa.Column('discount_type', sa.String(16), nullable=False),
        sa.Column('discount_value', sa.Numeric(10, 2), nullable=False),
        # Caps a percentage. Ignored on a flat coupon, where it would be a
        # contradiction rather than a qualifier.
        sa.Column('max_discount', sa.Numeric(10, 2), nullable=True),
        sa.Column('expiry_type', sa.String(16), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'min_order_value', sa.Numeric(10, 2), nullable=False, server_default='0'
        ),
        sa.Column('audience', sa.String(16), nullable=False, server_default='anyone'),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            'one_per_customer', sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            'show_in_offers', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_coupons_code', 'coupons', ['code'])

    # A row per allowed address rather than a column holding a list, so one
    # person can be removed without rewriting the set. Deliberately an address
    # and not a user_id: a code is handed to somebody who may not have signed in
    # yet, and requiring the account to exist first would make that impossible.
    op.create_table(
        'coupon_audience_members',
        sa.Column(
            'coupon_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('coupons.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column('email', sa.String(320), primary_key=True),
    )

    op.create_table(
        'coupon_redemptions',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'coupon_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('coupons.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        # SET NULL, matching cashback_entries and order_items: deleting an order
        # must not delete the record that somebody used a code.
        sa.Column(
            'order_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('orders.id', ondelete='SET NULL'),
            nullable=True,
        ),
        # What it was worth on that cart, kept rather than recomputed: the coupon
        # can be edited afterwards and what a student was given does not change.
        sa.Column('discount', sa.Numeric(10, 2), nullable=False),
        sa.Column('state', sa.String(16), nullable=False, server_default='held'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        # An order carries at most one code. Nulls do not collide in Postgres, so
        # redemptions whose order was deleted do not start conflicting.
        sa.UniqueConstraint('order_id', name='uq_coupon_one_per_order'),
    )
    op.create_index(
        'ix_coupon_redemptions_coupon', 'coupon_redemptions', ['coupon_id', 'state']
    )
    op.create_index('ix_coupon_redemptions_user', 'coupon_redemptions', ['user_id'])

    op.add_column(
        'orders',
        sa.Column(
            'coupon_discount', sa.Numeric(10, 2), nullable=False, server_default='0'
        ),
    )


def downgrade() -> None:
    op.drop_column('orders', 'coupon_discount')
    op.drop_index('ix_coupon_redemptions_user', table_name='coupon_redemptions')
    op.drop_index('ix_coupon_redemptions_coupon', table_name='coupon_redemptions')
    op.drop_table('coupon_redemptions')
    op.drop_table('coupon_audience_members')
    op.drop_index('ix_coupons_code', table_name='coupons')
    op.drop_table('coupons')
