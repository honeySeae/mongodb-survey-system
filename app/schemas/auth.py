"""账号相关的请求/响应模型。

这里只约束类型；用户名、密码的具体规则在 app/services/auth.py 中检查，以便返回统一的中文错误。
"""
from datetime import datetime

from app.schemas.common import CamelModel


class Credentials(CamelModel):
    """注册和登录共用的请求体。"""
    username: str
    password: str


class UserOut(CamelModel):
    id: str
    username: str
    created_at: datetime


class TokenOut(CamelModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 有效期（秒）
    user: UserOut
