"""Add vendor push-notification devices

Revision ID: c91f0a3e6d47
Revises: b4e7c1a95d28
Create Date: 2026-10-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c91f0a3e6d47'
down_revision: Union[str, None] = 'b4e7c1a95d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vendor_devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('fcm_token', sa.String(length=512), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=False, server_default='android'),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vendor_devices_vendor_id', 'vendor_devices', ['vendor_id'])
    # Unique across the table, not per vendor: Firebase issues one token per app
    # install, so a phone that signs into a different stall must move rather than
    # end up buzzing for both.
    op.create_index('ix_vendor_devices_fcm_token', 'vendor_devices', ['fcm_token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_vendor_devices_fcm_token', table_name='vendor_devices')
    op.drop_index('ix_vendor_devices_vendor_id', table_name='vendor_devices')
    op.drop_table('vendor_devices')
