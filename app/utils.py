"""通用小工具。"""
from datetime import datetime, timezone


def now_utc() -> datetime:
    """当前 UTC 时间，截断到毫秒。

    MongoDB 的 Date 只精确到毫秒；提前截断可保证“写入时返回的时间”和“之后读出的时间”一致。
    """
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)
