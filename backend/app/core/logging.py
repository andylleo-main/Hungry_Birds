import logging
import re

# Browsers cannot set headers on a WebSocket handshake, so the access token is
# passed as a query parameter. Uvicorn then writes the whole URL to its access
# log, which on a hosted platform is retained and readable - meaning anyone
# with log access holds working tokens. Redact it on the way out.
_TOKEN_IN_QUERY = re.compile(r'(token=)[^\s&"\']+')


class RedactTokensFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            record.args = tuple(
                _TOKEN_IN_QUERY.sub(r'\1[REDACTED]', a) if isinstance(a, str) else a
                for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _TOKEN_IN_QUERY.sub(r'\1[REDACTED]', record.msg)
        return True


def install_log_redaction() -> None:
    """Strip tokens from uvicorn's access and error logs."""
    for name in ('uvicorn.access', 'uvicorn.error'):
        logging.getLogger(name).addFilter(RedactTokensFilter())
