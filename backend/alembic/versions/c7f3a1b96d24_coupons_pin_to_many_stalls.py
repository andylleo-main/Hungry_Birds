"""A coupon works at a set of stalls, not at one

Revision ID: c7f3a1b96d24
Revises: b4e9d1c73a06
Create Date: 2026-10-07

`coupons.vendor_id` could say "this stall" or, as NULL, "all of them". It could
not say "these three", which is what an admin running a deal across a few
kitchens actually has.

So it becomes `coupon_vendors`, a row per stall, plus an `all_stalls` flag. The
existing pinning is copied over before the column goes, which is the only part of
this with data at stake, and a coupon that had a `vendor_id` gets `all_stalls`
false while a NULL one keeps true - so nothing about how an existing coupon
behaves changes across this migration.

**The flag is not redundant with "no rows".** A stall can be deleted, and
`remove_demo_stalls.py` does exactly that; CASCADE then takes its pinning rows
with it. If an empty set meant "every stall", removing one demo stall would turn
its coupon loose on the whole campus. With the flag such a coupon works nowhere,
which is the direction a money bug should fail in - and is what the nullable
`vendor_id` did by accident, since CASCADE deleted the coupon outright.

**Not additive**, unlike every migration before it in this feature: the column is
dropped. The release still serving during Railway's pre-deploy window reads
`coupons.vendor_id` in its stall check, so for the length of that window pinned
coupons would raise rather than quietly widening - the failure lands on a coupon
check, which already answers in words, rather than on an order. Worth saying
plainly because it is the first drop here that an in-flight request could notice.

The downgrade is lossy and cannot not be: a coupon pinned to three stalls has no
single `vendor_id` to go back to. It keeps the alphabetically first, which is
arbitrary but at least deterministic, and leaves the rest behind.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c7f3a1b96d24'
down_revision: Union[str, None] = 'b4e9d1c73a06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'coupon_vendors',
        sa.Column('coupon_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['coupon_id'], ['coupons.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('coupon_id', 'vendor_id'),
    )
    op.create_index('ix_coupon_vendors_vendor', 'coupon_vendors', ['vendor_id'])

    op.add_column(
        'coupons',
        sa.Column(
            'all_stalls', sa.Boolean(), nullable=False, server_default=sa.text('true')
        ),
    )

    # Before the column goes. A pinned coupon keeps working at the stall it was
    # pinned to and nowhere else; a NULL one was already good everywhere and
    # stays that way on the default.
    op.execute(
        """
        INSERT INTO coupon_vendors (coupon_id, vendor_id)
        SELECT id, vendor_id FROM coupons WHERE vendor_id IS NOT NULL
        """
    )
    op.execute("UPDATE coupons SET all_stalls = false WHERE vendor_id IS NOT NULL")

    op.drop_column('coupons', 'vendor_id')


def downgrade() -> None:
    op.add_column(
        'coupons',
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Lossy, as the docstring says. One stall survives per coupon and it is the
    # alphabetically first, so running this twice gives the same answer rather
    # than whichever row the planner happened to reach.
    #
    # Guarded on the flag, so a coupon narrowed to stalls that have all since
    # been deleted goes back as NULL - which the old schema reads as "every
    # stall". That is the one place this downgrade widens a coupon, and it is
    # unavoidable: the old column had nowhere to record "nowhere".
    op.execute(
        """
        UPDATE coupons SET vendor_id = (
            SELECT cv.vendor_id
            FROM coupon_vendors cv
            JOIN vendors v ON v.id = cv.vendor_id
            WHERE cv.coupon_id = coupons.id
            ORDER BY v.stall_name, cv.vendor_id
            LIMIT 1
        )
        WHERE all_stalls = false
        """
    )
    op.create_foreign_key(
        'coupons_vendor_id_fkey', 'coupons', 'vendors', ['vendor_id'], ['id'],
        ondelete='CASCADE',
    )

    op.drop_index('ix_coupon_vendors_vendor', table_name='coupon_vendors')
    op.drop_table('coupon_vendors')
    op.drop_column('coupons', 'all_stalls')
