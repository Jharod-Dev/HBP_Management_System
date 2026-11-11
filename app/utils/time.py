from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now():
    try:
        manila_timezone = ZoneInfo("Asia/Manila")
    except ZoneInfoNotFoundError:
        manila_timezone = timezone(timedelta(hours=8))
    return datetime.now(manila_timezone).replace(tzinfo=None)
