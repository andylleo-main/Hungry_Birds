"""Let stall owners sign in with a password

Revision ID: d4a92b5e7c13
Revises: c3e81a9f4d27
Create Date: 2026-10-05

A separate table rather than a column on `users`, which is the design decision
worth recording here rather than only in the model.

`users` has deliberately never held a password. The admin's hash lives in an
environment variable so that credentials stay out of the table, and riders were
given their own table rather than reverse that for every account in the system.
Adding `password_hash` to `users` now would reverse it for customers and admins
too, who will never have one. A separate table also fails closed: an account with
no row here cannot sign in with a password at all, which is a property of the
schema rather than of remembering to check a flag.

Purely additive, so the release still running during Railway's pre-deploy window
is unaffected - it writes no rows here and knows nothing about the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd4a92b5e7c13'
down_revision: Union[str, None] = 'c3e81a9f4d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'merchant_credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Unique rather than merely indexed: one password per account, enforced by
    # the database rather than by whichever code path happens to write it.
    op.create_index(
        'ix_merchant_credentials_user_id', 'merchant_credentials', ['user_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_merchant_credentials_user_id', table_name='merchant_credentials')
    op.drop_table('merchant_credentials')
