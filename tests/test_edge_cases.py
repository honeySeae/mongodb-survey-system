"""第十步：覆盖率检查后补充的边界情况。

pytest-cov 显示以下分支此前没有被确定地执行到（并发测试中能否走到取决于线程调度），这里用 monkeypatch 确定地触发。
"""
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app import db as app_db
from app.errors import AppError
from app.logic import operators as ops
from app.logic.survey_check import check_survey
from app.main import create_app
from app.repositories import responses as responses_repo
from app.repositories import surveys as surveys_repo
from app.security import create_access_token
from app.services import fill as fill_service
from app.services import surveys as survey_service
from app.utils import now_utc
from tests.builders import build_fruit_survey
from tests.conftest import auth_headers_for


# ---------- 系统 ----------
def test_health_reports_database_unavailable(client, monkeypatch):
    monkeypatch.setattr(app_db, "ping", lambda: False)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "database": "unavailable"}


def test_unexpected_error_returns_unified_500(db, monkeypatch):
    """未预料的异常返回统一格式的 500，不把内部错误细节暴露给客户端。"""
    def boom(*args, **kwargs):
        raise RuntimeError("数据库驱动内部错误：secret detail")
    monkeypatch.setattr(survey_service, "list_surveys", boom)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        headers = auth_headers_for(c, "erin")
        resp = c.get("/api/surveys", headers=headers)
    assert resp.status_code == 500
    assert resp.json() == {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}
    assert "secret" not in resp.text


def test_token_with_malformed_subject(client):
    token, _ = create_access_token("not-an-object-id", "alice")
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401 and resp.json()["code"] == "INVALID_TOKEN"


# ---------- 纯逻辑 ----------
def test_logic_must_be_object():
    q = {"id": "q1", "type": "single_choice", "title": "t", "options": [{"id": "o1", "text": "A"}],
         "validation": {"required": True}, "logic": "goto q3"}
    errors = check_survey([q]).errors
    assert [(e["field"], e["message"]) for e in errors] == [("logic", "第 1 题：跳转规则应为对象")]


def test_number_intervals_reject_non_number_operator():
    with pytest.raises(ValueError):
        ops.number_condition_intervals("contains", 1)


# ---------- once 策略：两次提交同时到达，唯一索引兜底（设计文档 6.2） ----------
def test_once_duplicate_key_fallback(client, bob, db, monkeypatch):
    """模拟“两次提交都通过了事先查询”：第二次插入时由部分唯一索引拦截，返回 409 且不留下答卷。"""
    built = build_fruit_survey(client, auth_headers_for(client, "owner1"), submissionPolicy="once")
    q = [x["id"] for x in built["q"]]
    o = built["o"]
    items = [{"questionId": q[0], "value": o["不喜欢"]}]
    uid = db["users"].find_one({"username": "bob"})["_id"]
    fill_service.submit(db, built["survey"]["shortCode"], uid, items)

    monkeypatch.setattr(responses_repo, "find_latest_of", lambda *a: None)   # 让事先查询“看不到”已有答卷
    with pytest.raises(AppError) as exc:
        fill_service.submit(db, built["survey"]["shortCode"], uid, items)
    assert exc.value.code == "ALREADY_SUBMITTED"
    assert db["responses"].count_documents({}) == 1


# ---------- 问卷状态：读取之后状态被其他请求改变（条件更新失败） ----------
@pytest.mark.parametrize("action", ["update", "delete", "publish", "close"])
def test_status_changed_between_read_and_write(client, alice, db, monkeypatch, action):
    s = client.post("/api/surveys", json={"title": "并发"}, headers=alice).json()
    db["surveys"].update_one({"_id": ObjectId(s["id"])}, {"$push": {"questions": {
        "id": "q_abc123", "type": "text", "title": "t", "validation": {"required": False}}}})
    if action == "close":
        client.post(f"/api/surveys/{s['id']}/publish", headers=alice)
    owner_id = db["surveys"].find_one({"_id": ObjectId(s["id"])})["ownerId"]
    # 条件更新“没有命中”：等价于读取之后状态被另一个请求改变
    monkeypatch.setattr(surveys_repo, "update_if_status", lambda *a, **k: None)
    monkeypatch.setattr(surveys_repo, "delete_if_status", lambda *a, **k: False)
    call = {
        "update": lambda: survey_service.update_survey(db, owner_id, s["id"], {"title": "新标题"}),
        "delete": lambda: survey_service.delete_survey(db, owner_id, s["id"]),
        "publish": lambda: survey_service.publish_survey(db, owner_id, s["id"]),
        "close": lambda: survey_service.close_survey(db, owner_id, s["id"]),
    }[action]
    with pytest.raises(AppError) as exc:
        call()
    assert exc.value.code == "INVALID_STATUS"
    assert exc.value.message == "问卷状态已变化，请刷新后重试"


# ---------- 脚本入口 ----------
def test_init_db_script(db, capsys):
    from scripts import init_db
    init_db.main()
    out = capsys.readouterr().out
    assert "初始化完成" in out and "surveyId_respondentId_latest_unique" in out


def test_seed_demo_command_line(db, capsys, monkeypatch):
    from scripts import seed_demo
    monkeypatch.setattr("sys.argv", ["seed_demo"])
    seed_demo.main()
    seed_demo.main()
    out = capsys.readouterr().out
    assert "已生成示例问卷" in out and "示例问卷已存在，未重复生成" in out
    assert "/survey/" in out and "demo_owner / demo123456" in out
    assert db["surveys"].count_documents({}) == 1


def test_duplicate_key_error_is_the_once_guard(db):
    """确认上面模拟的错误类型与真实的部分唯一索引冲突一致。"""
    doc = {"surveyId": ObjectId(), "surveyVersion": 1, "respondentId": ObjectId(), "isLatest": True,
           "submittedAt": now_utc(), "answers": []}
    responses_repo.insert(db, dict(doc))
    with pytest.raises(DuplicateKeyError):
        responses_repo.insert(db, dict(doc))
