"""鉴权中间件：Bearer API Key 校验（AUTH_ENABLED 开启后生效）。"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/api/health", "/api/docs", "/api/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings):
        super().__init__(app)
        self.enabled = settings.auth.enabled
        self.api_keys = set(settings.auth.api_keys)

    async def dispatch(self, request: Request, call_next):
        if self.enabled and request.url.path not in _PUBLIC_PATHS:
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={
                        "code": "UNAUTHORIZED",
                        "message": "缺少 Authorization: Bearer <API_KEY> 请求头",
                        "status": 401,
                    },
                )
            key = token.removeprefix("Bearer ").strip()
            if key not in self.api_keys:
                return JSONResponse(
                    status_code=401,
                    content={
                        "code": "UNAUTHORIZED",
                        "message": "API Key 无效",
                        "status": 401,
                    },
                )
        return await call_next(request)
