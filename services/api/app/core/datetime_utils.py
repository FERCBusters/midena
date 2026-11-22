"""UTC values for MIDENA's timestamp-without-time-zone columns.

Obtain an aware UTC value first, then deliberately remove tzinfo at the naive-UTC
storage boundary. This preserves comparisons, defaults and API output; it is not
a database timezone conversion. (KEEN's helper.)
"""

from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
