"""SSE 事件模型与序列化（对齐 Dify chat-messages 流式协议）。

Dify 的流式响应为 `data: {json}\n\n`，其中 JSON 内带 `event` 字段；
本模块据此序列化，便于接入按 Dify 协议开发的前端。
"""

import json
from dataclasses import dataclass, field
from typing import Any

# Dify 事件类型
EVENT_MESSAGE = "message"
EVENT_MESSAGE_END = "message_end"
EVENT_ERROR = "error"
EVENT_PING = "ping"


@dataclass
class SSEEvent:
    """一条 SSE 事件：data 行 JSON，内含 event 字段（与 Dify 一致）。"""

    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> str:
        payload = {"event": self.event, **self.data}
        return (
            "data: "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n\n"
        )


def error_event(code: str, message: str, status: int = 500) -> SSEEvent:
    """构造 error 事件。"""
    return SSEEvent(EVENT_ERROR, {"code": code, "message": message, "status": status})
