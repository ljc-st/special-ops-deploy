"""工具执行器：HTTP 执行器（真实 Java 接口）+ Mock 执行器（本地联调/测试）。"""

import asyncio
import os
from typing import Any

import httpx
from jinja2 import ChainableUndefined, Environment, StrictUndefined
from jsonpath_ng import parse as jp_parse

from app.llm.client import ToolCall
from app.tools.protocol import (
    ExecContext,
    HttpConfig,
    ToolConfig,
    ToolExecutor,
    ToolResult,
    dump_json,
    truncate_text,
    validate_arguments,
)

# body/url 模板：严格模式，缺参即报错（避免把残缺请求发给 Java 接口）
_jinja = Environment(undefined=StrictUndefined, autoescape=False)
# observation 模板：宽松模式，接口返回字段缺失时渲染为空而非抛错
_jinja_observation = Environment(undefined=ChainableUndefined, autoescape=False)


class HttpToolExecutor(ToolExecutor):
    """HTTP 执行器：模板渲染 → 鉴权注入 → httpx 调用 → JSONPath 提取 → observation 归一化。

    重试仅针对 5xx / 超时 / 网络错误；4xx 与业务错误码不重试。
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client

    async def execute(
        self, call: ToolCall, config: ToolConfig, ctx: ExecContext
    ) -> ToolResult:
        http = config.http
        if http is None:
            return ToolResult(False, f"工具 [{config.name}] 缺少 http 配置")

        args, err = validate_arguments(config, call.arguments)
        if err:
            return ToolResult(False, f"工具参数校验失败：{err}", error_code="INVALID_ARGUMENT")

        # 渲染 URL（支持路径参数，如 /calculate/{module}/{dimension}/{itemNo}；
        # 同时支持 {{ java_backend_url }} 占位，由环境变量 JAVA_BACKEND_URL 覆盖，
        # 默认指向本机 127.0.0.1:18082，便于 Docker 下改成容器服务名）
        try:
            url = _jinja.from_string(http.url).render(
                **args,
                user_id=ctx.user_id,
                request_id=ctx.request_id,
                inputs=ctx.inputs,
                java_backend_url=os.environ.get("JAVA_BACKEND_URL", "http://127.0.0.1:18082"),
            )
        except Exception as e:
            return ToolResult(False, f"工具 URL 渲染失败：{e}", error_code="INVALID_ARGUMENT")

        # 渲染 body 模板（参数 + 系统变量），GET 无 body
        body: str | None = None
        if http.body_template and http.method.upper() != "GET":
            try:
                body = _jinja.from_string(http.body_template).render(
                    **args, user_id=ctx.user_id, request_id=ctx.request_id, inputs=ctx.inputs
                )
            except Exception as e:  # StrictUndefined 缺参等
                return ToolResult(False, f"工具请求体渲染失败：{e}", error_code="INVALID_ARGUMENT")

        headers = self._build_headers(http, config, ctx)
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=http.timeout_seconds)

        last_error = ""
        resp: httpx.Response | None = None
        try:
            for attempt in range(1, http.retry.max_attempts + 1):
                if attempt > 1:
                    await asyncio.sleep(http.retry.interval_ms / 1000)
                try:
                    resp = await client.request(
                        http.method,
                        url,
                        headers=headers,
                        content=body.encode("utf-8") if body is not None else None,
                    )
                    resp.raise_for_status()
                    break
                except (httpx.HTTPStatusError, httpx.HTTPError) as e:
                    last_error = str(e)
                    retryable = isinstance(e, (httpx.ConnectError, httpx.TimeoutException)) or (
                        isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500
                    )
                    if attempt == http.retry.max_attempts or not retryable:
                        return ToolResult(
                            False,
                            f"工具调用失败：{last_error}",
                            error_code="TOOL_ERROR",
                            raw=last_error,
                        )
                except Exception as e:  # 非 HTTP 异常
                    last_error = str(e)
                    if attempt == http.retry.max_attempts:
                        return ToolResult(False, f"工具调用失败：{last_error}", error_code="TOOL_ERROR")
        finally:
            if own_client:
                await client.aclose()
        assert resp is not None

        # 状态码二次校验（raise_for_status 已覆盖 4xx/5xx；此处兜底 success_codes）
        if resp.status_code not in http.success_codes:
            return ToolResult(
                False,
                f"工具调用失败：[HTTP {resp.status_code}] Java 接口返回非预期状态",
                error_code="TOOL_ERROR",
                raw=resp.text[:500],
            )

        # 响应解析：JSONPath 提取业务数据
        try:
            payload: Any = resp.json()
        except Exception:
            payload = resp.text
        data = payload
        if http.response_path:
            try:
                matches = jp_parse(http.response_path).find(payload)
                data = matches[0].value if matches else None
            except Exception:
                data = None

        if data is None:
            return ToolResult(
                False,
                f"工具调用完成但未提取到数据（response_path={http.response_path}）",
                error_code="TOOL_EMPTY",
            )

        observation = self._render_observation(http, data)
        return ToolResult(True, observation, raw=data)

    @staticmethod
    def _build_headers(http: HttpConfig, config: ToolConfig, ctx: ExecContext) -> dict[str, str]:
        headers = {
            # 环境变量展开（如 ${INTERNAL_TOKEN}），避免密钥进配置库
            k: os.path.expandvars(v)
            for k, v in http.headers.items()
        }
        if config.auth_mode == "none":
            return headers  # 无鉴权接口：仅保留显式配置的 headers
        if config.auth_mode == "inherit" and ctx.user_token:
            headers["Authorization"] = f"Bearer {ctx.user_token}"
        elif config.auth_mode == "token" and "X-Internal-Token" not in headers:
            internal_token = os.environ.get("INTERNAL_TOKEN", "")
            if internal_token:
                headers["X-Internal-Token"] = internal_token
        # sign 模式：预留（时间戳+签名），当前先按 token 处理
        return headers

    @staticmethod
    def _render_observation(http: HttpConfig, data: Any) -> str:
        if http.observation_template:
            try:
                context = data if isinstance(data, dict) else {"data": data}
                # 宽松环境：接口返回中缺失的字段渲染为空字符串
                text = _jinja_observation.from_string(http.observation_template).render(**context)
            except Exception:
                text = dump_json(data)
        else:
            text = dump_json(data)
        return truncate_text(text, http.truncate_chars)


class MockToolExecutor(ToolExecutor):
    """Mock 执行器：不做真实调用，按配置返回预置 observation（本地联调/测试）。"""

    async def execute(
        self, call: ToolCall, config: ToolConfig, ctx: ExecContext
    ) -> ToolResult:
        args, err = validate_arguments(config, call.arguments)
        if err:
            return ToolResult(False, f"工具参数校验失败：{err}", error_code="INVALID_ARGUMENT")
        response = config.mock_response
        if response is None:
            response = f"（mock）工具 [{config.name}] 调用成功，参数 {dump_json(args)}"
        if not isinstance(response, str):
            response = dump_json(response)
        return ToolResult(True, response, raw=config.mock_response)
