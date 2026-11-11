from datetime import datetime
from zoneinfo import ZoneInfo


def now():
    return datetime.now(ZoneInfo("Asia/Manila")).replace(tzinfo=None)
