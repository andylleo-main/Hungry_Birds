"""Running side effects that must never fail the request that caused them.

Three things in this app talk to somebody else's server: Resend sends a login
code, Firebase pushes a notification to a stall, Cashfree takes money. The first
two are side effects - the request is already a success without them - and the
rule for those is that a third party having a bad afternoon must not turn our
endpoint into a 500.

That rule was not being followed. The Resend call sat unguarded in the middle of
request_otp, so a Resend outage did not merely fail to send one code, it made
*logging in* return 500 for everybody. It was also a synchronous HTTP call on the
event loop, which stalls every other request in flight for its duration.

Both mistakes are easy to repeat, so the fix is a shape to copy rather than a
one-off patch.
"""

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def fire_and_log(name: str, work: Callable[[], Awaitable[None]]) -> None:
    """Run a best-effort side effect, swallowing and logging any failure.

    Takes a callable rather than a coroutine so that nothing is created until
    this is actually run - a coroutine built at the call site and then never
    awaited (because the request failed first) emits a "never awaited" warning
    and silently does nothing.

    Deliberately catches BaseException's ordinary subclasses only: a bare
    `except Exception` leaves CancelledError alone, so a shutdown still cancels
    cleanly instead of being swallowed as a failed notification.
    """
    try:
        await work()
    except Exception:
        # Logged with a traceback rather than counted, because the useful
        # question when pushes stop arriving is always "what did the other end
        # actually say".
        logger.exception("background task %r failed", name)
