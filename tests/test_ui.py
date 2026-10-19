"""界面测试：用 Node.js 驱动无界面 Chrome，在真实页面中运行 tests/ui/*.test.mjs。

- 本机没有 Node.js（需 22 以上，自带 WebSocket）或 Chrome / Edge 时自动跳过，不影响其他测试；
  也可以用 `pytest -m "not ui"` 主动跳过。Chrome 不在默认位置时，用环境变量 CHROME_PATH 指定。
- 服务在空闲端口单独启动，使用独立数据库 survey_ui_test（与其他测试的 survey_test 分开），结束后删除。
- 每个场景的关键步骤截图保存在 tests/ui/screenshots/<场景>/（不提交到 git；整理文档时挑选复制到 docs/）。
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from pymongo import MongoClient

from app.config import get_settings

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent / "ui"
SCRIPTS = sorted(UI_DIR.glob("*.test.mjs"))
UI_DB = "survey_ui_test"

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _find_chrome() -> str | None:
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in _CHROME_CANDIDATES if Path(p).exists()), None)


def _node_supported(node: str | None) -> bool:
    if not node:
        return False
    out = subprocess.run([node, "-e", "process.stdout.write(typeof WebSocket)"], capture_output=True, text=True)
    return out.stdout.strip() == "function"


NODE = shutil.which("node")
CHROME = _find_chrome()

pytestmark = [
    pytest.mark.ui,
    pytest.mark.skipif(not _node_supported(NODE), reason="未安装 Node.js 22+（需要自带 WebSocket）"),
    pytest.mark.skipif(CHROME is None, reason="未找到 Chrome / Edge（可用环境变量 CHROME_PATH 指定）"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def ui_server(tmp_path_factory):
    """单独启动一个服务（独立端口、独立数据库），测试结束后只结束这个进程。"""
    port = _free_port()
    client = MongoClient(get_settings().mongo_uri)
    client.drop_database(UI_DB)
    env = {**os.environ, "MONGO_DB_NAME": UI_DB, "BCRYPT_ROUNDS": "4"}
    log = (tmp_path_factory.mktemp("ui") / "server.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("界面测试的服务没有启动")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()
        client.drop_database(UI_DB)
        client.close()


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name.replace(".test.mjs", ""))
def test_ui(ui_server, script, tmp_path):
    shots = UI_DIR / "screenshots" / script.name.replace(".test.mjs", "")
    shutil.rmtree(shots, ignore_errors=True)
    result = subprocess.run(
        [NODE, str(script), ui_server, CHROME, str(shots), str(tmp_path / "chrome-profile"), str(_free_port())],
        capture_output=True, text=True, encoding="utf-8", timeout=240)
    # 每一步的结果（“✓ 说明”）写入截图目录，作为整理测试用例的原始记录。
    # 不打印到控制台：Windows 控制台为 GBK 编码，无法输出“✓”等字符。
    shots.mkdir(parents=True, exist_ok=True)
    (shots / "steps.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
