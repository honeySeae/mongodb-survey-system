"""通用小工具。"""
from datetime import datetime, timezone

from bson import ObjectId


def to_mongo_time(dt: datetime) -> datetime:
    """转换为 UTC 并截断到毫秒。

    MongoDB 的 Date 只精确到毫秒；提前截断可保证“写入时的值”和“之后读出的值”一致，便于比较。
    """
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=dt.microsecond // 1000 * 1000)


def now_utc() -> datetime:
    """当前 UTC 时间，截断到毫秒。"""
    return to_mongo_time(datetime.now(timezone.utc))


def parse_object_id(value: str) -> ObjectId | None:
    """把字符串转换为 ObjectId，格式不对时返回 None。"""
    return ObjectId(value) if ObjectId.is_valid(value) else None
