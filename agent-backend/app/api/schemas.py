"""API 请求/响应模型（对齐 Dify chat-messages 协议）。"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ResponseMode = Literal["streaming", "blocking"]


class ChatRequest(BaseModel):
    """POST /v1/chat-messages 请求体（Dify 格式）。"""

    model_config = {"extra": "forbid"}

    query: str = Field(..., min_length=1, max_length=8000)
    # 前端固定业务参数；当前仅接收并校验，暂不参与 Agent 编排。
    user_choice: Literal["1", "2", "3"] | None = None
    traceId: str | int = Field(default="")
    upload_file: list[Any] = Field(default_factory=list)

    # 保留既有 Dify 兼容参数。
    inputs: dict[str, Any] = Field(default_factory=dict)
    response_mode: ResponseMode = "streaming"
    user: str = ""
    conversation_id: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    auto_generate_name: bool = False

    @model_validator(mode="after")
    def normalize_frontend_inputs(self):
        """Dify 约定：业务参数放在 inputs；同级字段仅作迁移兼容。"""
        merged = dict(self.inputs)
        if self.user_choice is not None:
            merged.setdefault("user_choice", self.user_choice)
        if self.traceId:
            merged.setdefault("traceId", self.traceId)
        if self.upload_file:
            merged.setdefault("upload_file", self.upload_file)
        self.inputs = merged
        self.user_choice = merged.get("user_choice")
        self.traceId = str(merged.get("traceId") or "")
        self.upload_file = merged.get("upload_file") or []
        if self.user_choice is not None and self.user_choice not in {"1", "2", "3"}:
            raise ValueError("inputs.user_choice 必须是字符串 1、2 或 3")
        return self


class ChatResponse(BaseModel):
    """blocking 模式的响应体（Dify 格式）。"""

    event: str = "message"
    task_id: str
    id: str
    message_id: str
    conversation_id: str
    mode: str = "chat"
    answer: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int


class ErrorResponse(BaseModel):
    code: str
    message: str
    status: int
