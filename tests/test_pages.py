"""第九步：前端页面路由、静态资源、/api/meta。

前端交互本身没有自动测试（不引入前端框架，也没有可供操作的浏览器），
由开发者按每个小步给出的浏览器检查清单手动验证，结果记入 AI_LOG 与 TEST_CASES.md。
"""
import re
from pathlib import Path

import pytest

from app.logic import operators as ops
from app.logic import question_rules as qr

STATIC = Path(__file__).resolve().parent.parent / "static"


@pytest.mark.parametrize("path, marker", [
    ("/login", "login.js"),
    ("/surveys", "surveys.js"),
    ("/surveys/abc/edit", "<title>编辑问卷"),
    ("/surveys/abc/stats", "<title>统计结果"),
    ("/survey/a8Kx2p", "fill.js"),
])
def test_pages_served_as_html(client, path, marker):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-cache"
    assert marker in resp.text


def test_home_redirects_to_my_surveys(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/surveys"


def test_pages_do_not_require_server_side_login(client):
    """页面是静态的，登录状态由页面脚本判断（未登录时跳转 /login?next=...）。"""
    assert client.get("/survey/xyz").status_code == 200


@pytest.mark.parametrize("path", ["/static/css/style.css", "/static/js/api.js", "/static/js/layout.js"])
def test_static_assets(client, path):
    assert client.get(path).status_code == 200


def test_unknown_static_asset_404(client):
    assert client.get("/static/js/nope.js").status_code == 404


def test_pages_not_in_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/login" not in paths and "/survey/{short_code}" not in paths
    assert "/api/meta" in paths


def test_no_external_resources():
    """所有页面只引用本站资源（不用 CDN、不用 Google Fonts：部署在阿里云，国内访问外网资源不稳定）。"""
    for f in list(STATIC.glob("*.html")) + list(STATIC.glob("css/*.css")):
        text = f.read_text(encoding="utf-8")
        for url in re.findall(r'(?:src|href)=["\']([^"\']+)["\']|url\(([^)]+)\)', text):
            u = next(x for x in url if x)
            assert not re.match(r"^(https?:)?//", u), f"{f.name} 引用了外部资源 {u}"


def test_no_inner_html_with_data():
    """前端脚本不使用 innerHTML（用户内容一律用 textContent 显示，防止 XSS）。"""
    pattern = re.compile(r"\.innerHTML\b|\.outerHTML\s*=|insertAdjacentHTML|document\.write")
    for f in STATIC.glob("js/*.js"):
        found = pattern.search(f.read_text(encoding="utf-8"))
        assert found is None, f"{f.name} 使用了 {found.group(0)}"


# ---------- /api/meta ----------
def test_meta_matches_backend_definitions(client):
    """运算符表直接来自后端定义，前端不维护副本。"""
    meta = client.get("/api/meta").json()
    assert meta["operators"] == ops.OPERATORS
    assert meta["questionTypes"] == list(qr.QUESTION_TYPES)
    assert meta["end"] == "END"
    assert meta["validationFields"]["number"] == ["integerOnly", "max", "min", "required"]
    assert "text" not in meta["operators"]          # 文本题不支持跳转
    assert meta["limits"]["questionTitleMax"] == 200
    assert meta["limits"]["surveyTitleMax"] == 100


def test_meta_public(client):
    assert client.get("/api/meta").status_code == 200


@pytest.mark.parametrize("path, mime", [("/static/js/api.js", "text/javascript"),
                                        ("/static/css/style.css", "text/css")])
def test_static_mime_types(client, path, mime):
    """模块脚本必须以 JavaScript 类型返回，否则浏览器拒绝执行（Windows 注册表可能给出 text/plain）。"""
    assert client.get(path).headers["content-type"].startswith(mime)
