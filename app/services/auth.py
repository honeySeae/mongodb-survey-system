"""注册与登录的业务逻辑。

规则（2026-10-19 开发者确认，见 AI_LOG 第 13 条）：
- 用户名：去掉首尾空格后 3~20 个字符，只允许字母、数字、下划线；不区分大小写，统一转小写后保存和比较
- 密码：至少 8 个字符，最多 72 个字节（bcrypt 上限）；不要求字符种类，不去除空格
- 登录失败统一提示“用户名或密码错误”，不区分用户名不存在还是密码错误
"""
import re

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app import security
from app.errors import Conflict, Unauthorized, ValidationFailed
from app.repositories import users as users_repo

USERNAME_MIN, USERNAME_MAX = 3, 20
PASSWORD_MIN_CHARS = 8
_USERNAME_RE = re.compile(r"[A-Za-z0-9_]+")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def check_username(username: str) -> list[str]:
    """返回用户名的问题列表，合法时为空列表。传入的是规范化之前的原始输入。"""
    name = username.strip()
    problems = []
    if not USERNAME_MIN <= len(name) <= USERNAME_MAX:
        problems.append(f"用户名长度应为 {USERNAME_MIN}~{USERNAME_MAX} 个字符")
    if name and not _USERNAME_RE.fullmatch(name):
        problems.append("用户名只能包含字母、数字和下划线")
    return problems


def check_password(password: str) -> list[str]:
    problems = []
    if len(password) < PASSWORD_MIN_CHARS:
        problems.append(f"密码至少 {PASSWORD_MIN_CHARS} 个字符")
    if len(password.encode("utf-8")) > security.BCRYPT_MAX_BYTES:
        problems.append(f"密码过长（最多 {security.BCRYPT_MAX_BYTES} 个字节，一个汉字占 3 个字节）")
    return problems


def register(db: Database, username: str, password: str) -> dict:
    """注册新用户，返回用户文档。"""
    errors = [{"field": "username", "message": m} for m in check_username(username)]
    errors += [{"field": "password", "message": m} for m in check_password(password)]
    if errors:
        raise ValidationFailed(errors)

    name = normalize_username(username)
    try:
        # 不先查询再插入：并发注册同名时由唯一索引保证只有一个成功
        return users_repo.create(db, name, security.hash_password(password))
    except DuplicateKeyError:
        raise Conflict("USERNAME_TAKEN", "用户名已被注册")


def login(db: Database, username: str, password: str) -> tuple[dict, str, int]:
    """校验用户名和密码，返回 (用户文档, token, 有效期秒数)。"""
    user = users_repo.find_by_username(db, normalize_username(username))
    if user is None:
        security.verify_password_dummy(password)
        raise Unauthorized("INVALID_CREDENTIALS", "用户名或密码错误")
    if not security.verify_password(password, user["passwordHash"]):
        raise Unauthorized("INVALID_CREDENTIALS", "用户名或密码错误")
    token, expires_in = security.create_access_token(user["_id"], user["username"])
    return user, token, expires_in
