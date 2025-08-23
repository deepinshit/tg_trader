from datetime import datetime, timezone

def utc_now(timezone_aware: bool = False):
    now = datetime.now(tz=timezone.utc)
    if timezone_aware:
        return now
    return now.replace(tzinfo=None)
