"""HTTP 路由：对话主入口、会话列表、健康检查（Dify 兼容）。

主要接口对齐 Dify：
- POST /v1/chat-messages   对话主入口（streaming / blocking）
- GET  /v1/conversations   会话列表
"""

import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
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
async def chat_messages(req: ChatRequest, request: Request):
    """对话主入口，支持 streaming（SSE）与 blocking 两种模式。"""
    # 兼容部署在 /api 前缀下的客户端（ASGI root_path 或反向代理均可）。
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
async def conversations(user: str = "", last_id: str = "", limit: int = 20, sort_by: str = "-updated_at"):
    """Dify 兼容的会话历史列表。"""
    store = _get_memory_store()
    records = store.list_conversations(user_id=user, limit=max(1, min(limit, 100)))
    data = []
    for item in records:
        conversation_id = item.get("conversation_id", item.get("id", ""))
        context = store.load_context(conversation_id, limit=2)
        first_query = next((m.content for m in context.messages if m.role == "user"), "")
        data.append({
            "id": conversation_id,
            # 历史列表只显示用户首条问题的短标题，避免把完整回答/HTML 表格挤进侧栏。
            "name": (first_query[:24] + ("…" if len(first_query) > 24 else "")) or "未命名会话",
            "inputs": {},
            "status": "normal",
            "introduction": None,
            "created_at": int(item.get("created_at", 0) * 1000),
            "updated_at": int(item.get("updated_at", 0) * 1000),
        })
    return {"data": data, "has_more": False, "limit": len(data)}


@router.get("/messages")
async def messages(conversation_id: str, user: str = "", first_id: str = "", limit: int = 20):
    """Dify 兼容的会话消息历史，按时间正序返回供前端恢复。"""
    store = _get_memory_store()
    conversations = store.list_conversations(user_id=user) if user else store.list_conversations()
    record = next((item for item in conversations if item.get("conversation_id") == conversation_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    context = store.load_context(conversation_id, limit=None)
    data = []
    for index, message in enumerate(context.messages[-max(1, min(limit, 100)):], start=1):
        if message.role != "user":
            continue
        answer = ""
        following = context.messages[index:index + 1]
        if following and following[0].role == "assistant":
            answer = following[0].content
        data.append({
            "id": f"{conversation_id}-{index}",
            "conversation_id": conversation_id,
            "inputs": {},
            "query": message.content,
            "message_files": [],
            "answer": answer,
            "created_at": int(message.created_at * 1000),
            "feedback": None,
            "retriever_resources": [],
        })
    return {"data": data, "has_more": False, "limit": len(data)}


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
        src = next((e.data for e in events if e.event == "message_start"), {})
        return ChatResponse(
            task_id=src.get("task_id", ""),
            id=src.get("message_id", ""),
            message_id=src.get("message_id", ""),
            conversation_id=src.get("conversation_id", ""),
            answer="暂无法完成评分查询，请稍后重试。",
            metadata={
                "finish_reason": "error",
                "error_code": error.data.get("code", "INTERNAL"),
                "error_status": int(error.data.get("status", 500)),
            },
            created_at=int(src.get("created_at", time.time())),
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
