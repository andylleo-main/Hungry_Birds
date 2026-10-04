"""Add dish variants and hold price changes for an admin

Revision ID: b7f0d2e51a48
Revises: a1c4e7b20d93
Create Date: 2026-10-04

One revision rather than two, because order_items.variant_id carries a foreign
key to a table created here - they cannot be split without the second half
referring to something that does not exist yet.

Everything is additive and nullable, so the release running during Railway's
pre-deploy window is unaffected: it writes no variants and no pending prices,
and an item with neither behaves exactly as it did.

Nothing is backfilled. In particular there is deliberately no synthetic
"Regular" variant for every existing dish: it would be a whole-table write in a
migration, it would put "Butter Paneer - Regular" in front of customers, and it
would leave menu_items.price dead everywhere so every future read needed a join.
The two shapes are kept, and resolve_line_price in the orders module is the only
code allowed to know which is which.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b7f0d2e51a48'
down_revision: Union[str, None] = 'a1c4e7b20d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'menu_item_variants',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('pending_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('pending_price_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_menu_item_variants_item_id', 'menu_item_variants', ['item_id'])
    # Case-insensitive, so a stall cannot end up with "Full" and "full" and no
    # way to tell which one an order meant.
    op.execute(
        "CREATE UNIQUE INDEX uq_menu_item_variants_item_name"
        " ON menu_item_variants (item_id, lower(name))"
    )

    op.add_column('menu_items', sa.Column('pending_price', sa.Numeric(10, 2), nullable=True))
    op.add_column(
        'menu_items', sa.Column('pending_price_at', sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column(
        'order_items', sa.Column('variant_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'order_items_variant_id_fkey',
        'order_items',
        'menu_item_variants',
        ['variant_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.add_column(
        'order_items', sa.Column('variant_name_snapshot', sa.String(length=255), nullable=True)
    )

    op.create_table(
        'menu_price_changes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('variant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name_snapshot', sa.String(length=255), nullable=False),
        sa.Column('old_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('new_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('decided_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['menu_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['variant_id'], ['menu_item_variants.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_menu_price_changes_vendor', 'menu_price_changes', ['vendor_id', 'created_at']
    )


def downgrade() -> None:
    # Dropping menu_item_variants discards every size a stall has configured and
    # nulls the variant on historical order lines, so a reprint of an old order
    # loses which size it was. The prices themselves survive in price_snapshot.
    op.drop_index('ix_menu_price_changes_vendor', table_name='menu_price_changes')
    op.drop_table('menu_price_changes')

    op.drop_column('order_items', 'variant_name_snapshot')
    op.drop_constraint('order_items_variant_id_fkey', 'order_items', type_='foreignkey')
    op.drop_column('order_items', 'variant_id')

    op.drop_column('menu_items', 'pending_price_at')
    op.drop_column('menu_items', 'pending_price')

    op.execute('DROP INDEX IF EXISTS uq_menu_item_variants_item_name')
    op.drop_index('ix_menu_item_variants_item_id', table_name='menu_item_variants')
    op.drop_table('menu_item_variants')
