"""前端纯函数测试：用 Node.js 运行 tests/js/*.test.mjs；机器上没有 Node.js 时跳过。"""
import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = sorted((Path(__file__).parent / "js").glob("*.test.mjs"))
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="未安装 Node.js")
@pytest.mark.parametrize("script", JS_TESTS, ids=lambda p: p.name)
def test_js(script):
    result = subprocess.run([NODE, str(script)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
