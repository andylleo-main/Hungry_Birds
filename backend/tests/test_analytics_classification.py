"""Every order status is deliberately classified, or the dashboard lies.

Both of these lists used to be derived or hand-written in a way that absorbed new
statuses silently: revenue was "every status except cancelled", which counted
rejected orders as income, and the active count was four statuses typed inline,
which stopped including deliveries the day riders shipped.

Neither failure is visible - the numbers are simply wrong - so the lists are
explicit and this test makes adding a status a decision somebody has to make.
"""

from app.db.models.order import OrderStatus
from app.modules.admin.analytics import ACTIVE_STATUSES, EARNING_STATUSES

# Statuses that are deliberately neither revenue nor in-flight, with the reason.
NOT_REVENUE = {
    OrderStatus.AWAITING_PAYMENT: "nobody has paid, and no stall has seen it",
    OrderStatus.REJECTED: "the stall refused; the money goes back",
    OrderStatus.CANCELLED: "never made, and refunded if it was paid",
}


def test_every_status_is_either_revenue_or_explicitly_not():
    unclassified = set(OrderStatus) - set(EARNING_STATUSES) - set(NOT_REVENUE)
    assert not unclassified, (
        f"{[s.value for s in unclassified]} is counted as neither revenue nor "
        "explicitly excluded - decide which, in analytics.py and here"
    )


def test_nothing_is_counted_as_revenue_and_excluded_at_once():
    assert not set(EARNING_STATUSES) & set(NOT_REVENUE)


def test_an_order_out_with_a_rider_is_still_in_flight():
    """The specific regression: it was in neither list after riders shipped."""
    assert OrderStatus.OUT_FOR_DELIVERY in ACTIVE_STATUSES
    assert OrderStatus.OUT_FOR_DELIVERY in EARNING_STATUSES


def test_an_unpaid_order_is_not_in_flight_and_not_revenue():
    assert OrderStatus.AWAITING_PAYMENT not in ACTIVE_STATUSES
    assert OrderStatus.AWAITING_PAYMENT not in EARNING_STATUSES


def test_active_statuses_are_a_subset_of_earning_ones():
    """An order being worked on has been paid for, so it is money taken."""
    assert set(ACTIVE_STATUSES) <= set(EARNING_STATUSES)
