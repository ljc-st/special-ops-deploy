"""API 请求/响应模型（对齐 Dify chat-messages 协议）。"""

from typing import Any, Literal

from pydantic import BaseModel, Field

ResponseMode = Literal["streaming", "blocking"]


class ChatRequest(BaseModel):
    """POST /v1/chat-messages 请求体（Dify 格式）。"""

    query: str = Field(..., min_length=1, max_length=8000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    response_mode: ResponseMode = "streaming"
    user: str = ""
    conversation_id: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    auto_generate_name: bool = False


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
