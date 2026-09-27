import logging
import re

# Anything credential-shaped that reaches a URL ends up in uvicorn's access
# log, which on a hosted platform is retained and readable. Socket handshakes
# now carry only a single-use ticket that dies in 30 seconds (see
# realtime/service.py), so this is no longer load-bearing - but it costs
# nothing, and it also covers an `access_token` that slips into a query string
# from some future client bug.
_SECRET_IN_QUERY = re.compile(r'((?:access_|refresh_)?token=|ticket=)[^\s&"\']+')


class RedactTokensFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(
                _SECRET_IN_QUERY.sub(r'\1[REDACTED]', a) if isinstance(a, str) else a
                for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _SECRET_IN_QUERY.sub(r'\1[REDACTED]', record.msg)
        return True


def install_log_redaction() -> None:
    """Strip credentials out of uvicorn's access and error logs."""
    for name in ('uvicorn.access', 'uvicorn.error'):
        logging.getLogger(name).addFilter(RedactTokensFilter())
