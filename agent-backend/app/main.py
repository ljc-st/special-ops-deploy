"""FastAPI 应用入口。"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.middleware import AuthMiddleware


class UTF8JSONResponse(JSONResponse):
    """让 Windows PowerShell 等客户端按 UTF-8 解码 JSON 中文。"""

    media_type = "application/json; charset=utf-8"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="智能体问答服务：用户提问 → 调用后端 Java 接口 → 大模型润色 → Dify 风格 SSE 流式返回",
        default_response_class=UTF8JSONResponse,
    )
    # 本地控制台运行在独立端口时允许访问智能体 API；生产环境应改为明确的前端域名。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5500",
            "http://localhost:5500",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware, settings=settings)
    app.include_router(router)
    # 保留反向代理/现有前端使用的 /api/v1 兼容入口；/v1 仍是规范主入口。
    app.include_router(router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
