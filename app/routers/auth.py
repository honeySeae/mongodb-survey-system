"""账号接口：注册、登录、当前用户。"""
from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.schemas.auth import Credentials, TokenOut, UserOut
from app.security import get_current_user, get_database
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(user: dict) -> UserOut:
    return UserOut(id=str(user["_id"]), username=user["username"], created_at=user["createdAt"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: Credentials, db: Database = Depends(get_database)):
    """注册。成功后不自动登录，需再调用登录接口。"""
    return user_out(auth_service.register(db, body.username, body.password))


@router.post("/login", response_model=TokenOut)
def login(body: Credentials, db: Database = Depends(get_database)):
    """登录，返回 JWT。之后的请求在请求头中携带 Authorization: Bearer <accessToken>。"""
    user, token, expires_in = auth_service.login(db, body.username, body.password)
    return TokenOut(access_token=token, expires_in=expires_in, user=user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    """当前登录用户。"""
    return user_out(user)
