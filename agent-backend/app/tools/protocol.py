"""工具统一调用协议：ToolConfig / ToolResult / ExecContext / ToolExecutor。

设计要点（docs/agent-design.md §5）：Java 接口以"工具"为单位配置化注册，
执行器按 executor_type 分发（http | mock，未来可扩展 rpc），LLM 侧零感知。
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm.client import ToolCall

AuthMode = Literal["inherit", "token", "sign", "none"]


class ToolParameter(BaseModel):
    """工具参数定义（与 OpenAI function schema 的 properties 对应）。"""

    type: str = "string"
    required: bool = False
    description: str = ""
    enum: list[str] | None = None


class RetryConfig(BaseModel):
    max_attempts: int = 1
    backoff: Literal["fixed", "exponential"] = "fixed"
    interval_ms: int = 200


class HttpConfig(BaseModel):
    """HTTP 执行配置（executor_type=http 时使用）。"""

    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str | None = None
    timeout_seconds: float = 10.0
    retry: RetryConfig = Field(default_factory=RetryConfig)
    success_codes: list[int] = Field(default_factory=lambda: [200])
    response_path: str | None = None
    observation_template: str | None = None
    truncate_chars: int = 2000


class ToolConfig(BaseModel):
    """一个工具 = 一份配置（给 LLM 的 schema + 执行细节）。"""

    name: str
    description: str
    parameters: dict[str, ToolParameter] = Field(default_factory=dict)
    executor_type: Literal["http", "mock", "skill"] = "http"
    http: HttpConfig | None = None
    auth_mode: AuthMode = "inherit"
    # executor_type=skill 时的技能名（缺省用 name）
    skill_name: str | None = None
    # executor_type=mock 时的预置返回（str 直接作为 observation，否则 JSON 序列化）
    mock_response: Any = None

    def to_llm_schema(self) -> dict:
        """转换为 OpenAI function calling 的 tools 定义。"""
        properties = {
            name: {
                "type": p.type,
                "description": p.description,
                **({"enum": p.enum} if p.enum else {}),
            }
            for name, p in self.parameters.items()
        }
        required = [n for n, p in self.parameters.items() if p.required]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass
class ToolResult:
    """工具执行结果：observation 为喂给 LLM 的归一化文本。"""

    ok: bool
    observation: str
    raw: Any | None = None
    error_code: str | None = None


@dataclass
class ExecContext:
    """执行上下文：模板系统变量与鉴权透传。"""

    user_id: str = ""
    request_id: str = ""
    user_token: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    log_client: Any = None
    data_query_service: Any = None


class ToolExecutor(ABC):
    """执行器抽象：新增协议（rpc 等）只需实现本接口。"""

    @abstractmethod
    async def execute(
        self, call: ToolCall, config: ToolConfig, ctx: ExecContext
    ) -> ToolResult:
        raise NotImplementedError


def validate_arguments(
    config: ToolConfig, arguments: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """按工具 schema 校验参数。

    返回 (过滤后的参数, 错误信息)。缺 required 或类型不匹配时返回错误，
    多余参数被丢弃（避免透传给后端接口）。
    """
    errors: list[str] = []
    cleaned: dict[str, Any] = {}
    for name, spec in config.parameters.items():
        if name not in arguments:
            if spec.required:
                errors.append(f"缺少必填参数 [{name}]")
            continue
        value = arguments[name]
        if spec.type == "string" and not isinstance(value, str):
            errors.append(f"参数 [{name}] 应为 string")
            continue
        if spec.type == "integer" and not isinstance(value, int):
            errors.append(f"参数 [{name}] 应为 integer")
            continue
        if spec.type == "boolean" and not isinstance(value, bool):
            errors.append(f"参数 [{name}] 应为 boolean")
            continue
        if spec.enum and value not in spec.enum:
            errors.append(f"参数 [{name}] 取值不在允许范围 {spec.enum}")
            continue
        cleaned[name] = value
    if errors:
        return {}, "；".join(errors)
    return cleaned, None


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（已截断，共 {len(text)} 字符）"


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
