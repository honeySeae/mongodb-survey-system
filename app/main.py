"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload
后续步骤会在这里挂载各模块的路由（auth、surveys、fill、stats）和静态页面。
"""
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="在线问卷系统", version="0.1.0")

    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        """健康检查：服务是否在运行。"""
        return {"status": "ok"}

    return app


app = create_app()
