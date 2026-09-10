"""Agent 编排入口：ChatRequest -> SSE 事件流（Dify chat-messages 协议）。

流程：
  LangGraph function calling 循环（app/graph/builder.py），节点内通过
  get_stream_writer() 推送 llm_token 自定义事件，本模块消费并映射为 Dify SSE：
    message* -> message_end（或 error）
"""

import time
import uuid
from functools import lru_cache
from pathlib import Path

from app.api.schemas import ChatRequest
from app.config import BASE_DIR, get_settings
from app.graph.builder import build_graph
from app.llm.client import create_chat_client
from app.sse.event import (
    EVENT_MESSAGE,
    EVENT_MESSAGE_END,
    SSEEvent,
    error_event,
)
from app.tools.loader import build_registry
from app.tools.registry import ToolRegistry
from app.memory import MemoryContext, MySQLMemoryStore, SQLiteMemoryStore


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@lru_cache(maxsize=1)
def _get_registry() -> ToolRegistry:
    """单例注册中心（无状态，可跨请求复用；修改 tools.yaml 后需重启生效）。"""
    settings = get_settings()
    return build_registry(settings.tools_config_abspath)


@lru_cache(maxsize=1)
def _get_memory_store() -> SQLiteMemoryStore:
    settings = get_settings()
    if settings.memory.backend.lower() == "mysql":
        return MySQLMemoryStore(
            host=settings.memory.host,
            port=settings.memory.port,
            user=settings.memory.user,
            password=settings.memory.password,
            database=settings.memory.database,
        )
    configured = Path(settings.memory.sqlite_path)
    path = configured if configured.is_absolute() else BASE_DIR / configured
    return SQLiteMemoryStore(path)


def _context_prompt(context: MemoryContext) -> str:
    parts: list[str] = []
    if context.summary:
        parts.append(f"历史会话摘要：{context.summary}")
    if context.messages:
        recent = "\n".join(f"{message.role}: {message.content}" for message in context.messages)
        parts.append(f"最近对话：\n{recent}")
    return "\n\n".join(parts)


def _compact_memory(store: SQLiteMemoryStore, conversation_id: str) -> None:
    settings = get_settings().memory
    context = store.load_context(conversation_id, limit=None)
    max_messages = max(2, settings.window_turns * 2)
    keep = context.messages[-max_messages:]
    while len(keep) > 2 and sum(len(message.content) for message in keep) > settings.window_chars:
        keep.pop(0)
    older = context.messages[: len(context.messages) - len(keep)]
    if not older:
        return
    lines = "\n".join(f"{message.role}: {message.content}" for message in older)
    summary = "\n".join(part for part in (context.summary, lines) if part)
    store.save_summary(conversation_id, summary[-4000:])
    store.trim_messages(conversation_id, len(keep))


async def chat_event_stream(req: ChatRequest):
    """生成 ChatRequest 对应的 Dify SSE 事件流。"""
    settings = get_settings()
    llm = create_chat_client(settings.llm)
    registry = _get_registry()
    graph = build_graph(llm, registry, max_iterations=settings.max_iterations)

    conversation_id = req.conversation_id or _new_id("c")
    memory = _get_memory_store()
    memory.create_or_get(conversation_id, user_id=req.user)
    prior = memory.load_context(conversation_id, limit=get_settings().memory.window_turns * 2)
    memory_context = _context_prompt(prior)
    message_id = _new_id("m")
    task_id = _new_id("t")
    created_at = int(time.time())
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    initial_state = {
        "messages": [
            *({"role": message.role, "content": message.content} for message in prior.messages),
            {"role": "user", "content": req.query},
        ],
        "memory_context": memory_context,
        "user_id": req.user,
        "request_id": request_id,
        "user_token": "",
        "inputs": req.inputs,
        "iteration": 0,
        "max_iterations": settings.max_iterations,
        "tool_calls": [],
        "last_tool_signature": None,
        "thought_position": 0,
    }

    answer_parts: list[str] = []
    try:
        async for mode, payload in graph.astream(
            initial_state, stream_mode=["custom", "updates"]
        ):
            if mode != "custom":
                continue
            if payload.get("type") == "llm_token":
                content = payload.get("content", "")
                answer_parts.append(content)
                yield SSEEvent(
                    EVENT_MESSAGE,
                    {
                        "task_id": task_id,
                        "id": message_id,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                        "answer": content,
                        "created_at": created_at,
                    },
                )
    except Exception as e:  # 编排异常：以 error 事件结束流
        yield error_event("INTERNAL", f"Agent 编排异常：{e}", 500)
        return

    answer = "".join(answer_parts)
    memory.append_message(conversation_id, "user", req.query)
    memory.append_message(conversation_id, "assistant", answer)
    _compact_memory(memory, conversation_id)

    yield SSEEvent(
        EVENT_MESSAGE_END,
        {
            "task_id": task_id,
            "id": message_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "metadata": {
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "retriever_resources": [],
            },
        },
    )
