"""Add rider push-notification devices

Revision ID: f3b92e5c1a67
Revises: e5c13d8a4b02
Create Date: 2026-10-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f3b92e5c1a67'
down_revision: Union[str, None] = 'e5c13d8a4b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'rider_devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rider_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('fcm_token', sa.String(length=512), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=False, server_default='android'),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['rider_id'], ['riders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_rider_devices_rider_id', 'rider_devices', ['rider_id'])
    # Unique across the table for the same reason as vendor_devices: Firebase
    # issues one token per app install, so a phone passed between riders must
    # move with it rather than notify both.
    op.create_index('ix_rider_devices_fcm_token', 'rider_devices', ['fcm_token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_rider_devices_fcm_token', table_name='rider_devices')
    op.drop_index('ix_rider_devices_rider_id', table_name='rider_devices')
    op.drop_table('rider_devices')
