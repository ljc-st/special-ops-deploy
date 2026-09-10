"""HTTP 路由：对话主入口、会话列表、健康检查（Dify 兼容）。

主要接口对齐 Dify：
- POST /v1/chat-messages   对话主入口（streaming / blocking）
- GET  /v1/conversations   会话列表
"""

import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.schemas import ChatRequest, ChatResponse, ErrorResponse
from app.graph.runner import chat_event_stream
from app.graph.runner import _get_memory_store
from app.sse.event import EVENT_ERROR, EVENT_MESSAGE, EVENT_MESSAGE_END, SSEEvent
from app.sse.stream import with_ping

router = APIRouter(prefix="/v1")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post(
    "/chat-messages",
    response_model=ChatResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def chat_messages(req: ChatRequest):
    """对话主入口，支持 streaming（SSE）与 blocking 两种模式。"""
    if req.response_mode == "blocking":
        events: list[SSEEvent] = [ev async for ev in chat_event_stream(req)]
        return _to_blocking_response(events)

    # streaming：SSE 事件流（心跳由 with_ping 注入）
    async def event_gen() -> AsyncIterator[SSEEvent]:
        async for ev in chat_event_stream(req):
            yield ev

    heartbeat = with_ping(event_gen(), interval=20.0)

    async def serialized_events() -> AsyncIterator[str]:
        async for ev in heartbeat:
            yield ev.serialize()

    return StreamingResponse(
        serialized_events(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/conversations")
async def conversations(user: str = ""):
    """返回持久化会话列表，可按用户筛选。"""
    return {"data": _get_memory_store().list_conversations(user_id=user)}


@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str, user: str = ""):
    """返回指定会话的摘要和消息，供本地控制台恢复历史上下文。"""
    store = _get_memory_store()
    context = store.load_context(conversation_id, limit=None)
    conversations = store.list_conversations(user_id=user) if user else store.list_conversations()
    record = next(
        (item for item in conversations if item["conversation_id"] == conversation_id),
        None,
    )
    if record is None or (user and record.get("user_id") != user):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {
        "conversation_id": conversation_id,
        "summary": context.summary,
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in context.messages
        ],
    }


def _to_blocking_response(events: list[SSEEvent]) -> ChatResponse:
    """把事件流聚合为 Dify blocking 响应。"""
    msg_events = [e for e in events if e.event == EVENT_MESSAGE]
    end = next((e for e in events if e.event == EVENT_MESSAGE_END), None)
    error = next((e for e in events if e.event == EVENT_ERROR), None)

    if error:
        return JSONResponse(
            status_code=int(error.data.get("status", 500)),
            content={
                "code": error.data.get("code", "INTERNAL"),
                "message": error.data.get("message", ""),
                "status": error.data.get("status", 500),
            },
        )

    src = msg_events[0].data if msg_events else (end.data if end else {})
    if not src:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL",
                "message": "agent 未产出完整事件序列",
                "status": 500,
            },
        )

    answer = "".join(e.data.get("answer", "") for e in msg_events)
    metadata = end.data.get("metadata", {}) if end else {}
    return ChatResponse(
        task_id=src.get("task_id", ""),
        id=src.get("message_id", ""),
        message_id=src.get("message_id", ""),
        conversation_id=src.get("conversation_id", ""),
        answer=answer,
        metadata=metadata,
        created_at=int(src.get("created_at", time.time())),
    )
