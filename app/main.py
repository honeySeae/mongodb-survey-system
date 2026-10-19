"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload
后续步骤会在这里挂载各模块的路由（auth、surveys、fill、stats）和静态页面。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import db
from app.db_schema import ensure_schema
from app.errors import register_error_handlers
from app.routers import auth, fill, questions, stats, surveys


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保集合、校验规则和索引就绪（幂等）；MongoDB 不可用时直接启动失败，便于发现问题
    ensure_schema(db.get_db())
    yield
    db.close_client()


def create_app() -> FastAPI:
    app = FastAPI(title="在线问卷系统", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(surveys.router)
    app.include_router(questions.router)
    app.include_router(fill.router)
    app.include_router(stats.router)

    @app.get("/api/health", tags=["system"])
    def health():
        """健康检查：服务是否在运行、数据库是否可连接。"""
        if db.ping():
            return {"status": "ok", "database": "ok"}
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})

    return app


app = create_app()
