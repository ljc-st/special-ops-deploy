"""Agent 编排入口：ChatRequest -> SSE 事件流（Dify chat-messages 协议）。

流程：
  LangGraph function calling 循环（app/graph/builder.py），节点内通过
  get_stream_writer() 推送 llm_token 自定义事件，本模块消费并映射为 Dify SSE：
    message* -> message_end（或 error）
"""

import asyncio
import html
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path

from app.api.schemas import ChatRequest
from app.config import BASE_DIR, get_settings
from app.graph.builder import build_graph
from app.llm.client import create_chat_client
from app.sse.event import (
    EVENT_AGENT_THOUGHT,
    EVENT_MESSAGE,
    EVENT_MESSAGE_END,
    EVENT_MESSAGE_START,
    SSEEvent,
    error_event,
)
from app.tools.loader import build_registry
from app.tools.registry import ToolRegistry
from app.tools.score_format import _score_sequence
from app.memory import MemoryContext, MySQLMemoryStore, SQLiteMemoryStore
from app.log_client import LogClient, generate_visible_thought


def _markdown_cells(line: str) -> list[str]:
    source = str(line or "").strip()
    if source.startswith("|"):
        source = source[1:]
    if source.endswith("|"):
        source = source[:-1]
    return [part.strip().replace("\\|", "|") for part in source.split("|")]


def _is_table_line(line: str) -> bool:
    return str(line or "").strip().startswith("|") and str(line or "").strip().endswith("|")


def _is_table_separator(line: str) -> bool:
    return _is_table_line(line) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in _markdown_cells(line))


def _normalize_score_cell(value: object) -> str:
    """将评分列统一为两位小数，便于用户直接阅读。"""
    # 数字 0 是有效得分，不能因真值判断被替换成短横线。
    text = "-" if value is None or str(value).strip() == "" else str(value).strip()
    if "/" not in text:
        return text
    left, right = (part.strip() for part in text.split("/", 1))
    if left in {"-", "—", "未返回"}:
        try:
            if float(re.sub(r"\s*分.*$", "", right)) == 0:
                return "数据不足"
        except (TypeError, ValueError):
            pass
    try:
        left_number = float(left)
        right_number = re.sub(r"\s*分.*$", "", right)
        right_value = float(right_number)
        left_text = "-0.00" if left_number == 0 and right_value == 0 else f"{left_number:.2f}"
        right_text = f"{right_value:.2f}"
        return f"{left_text} / {right_text} 分"
    except (TypeError, ValueError):
        return text


def _display_item_name(value: object) -> str:
    """清理模型表格中的正式评分编码，仅保留面向用户的名称。"""
    text = str(value or "-").strip()
    text = re.sub(r"\bspecial-[A-Za-z0-9_-]+\b", "", text)
    text = re.sub(r"\s*[（(]编码[:：]?\s*[^）)]*[）)]", "", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ：:，,") or "-"


def _compact_reason(value: object) -> str:
    """压缩模型重复列出的企业清单，保留数量和前三个名称。"""
    text = str(value or "-").strip()
    match = re.search(r"涉及(?:实体|企业)[:：]\s*(.+)$", text)
    if not match:
        return text
    prefix = text[: match.start()]
    names = [part.strip() for part in re.split(r"[、,，]", match.group(1)) if part.strip()]
    if len(names) <= 4:
        return text
    count_match = re.search(r"(?:等|共)\s*(\d+)\s*家", match.group(1))
    count = count_match.group(1) if count_match else str(len(names))
    return prefix + "涉及企业：" + "、".join(names[:3]) + f"等{count}家"


def _render_table_html(table_lines: list[str]) -> str:
    rows = [_markdown_cells(line) for line in table_lines if _is_table_line(line) and not _is_table_separator(line)]
    if len(rows) < 2:
        return "".join(table_lines)
    headers = rows[0]
    body = rows[1:]
    score_table = len(headers) >= 3 and headers[0] in {"评分项", "序号"} and ("得分" in headers or "状态" in headers)
    if score_table and len(headers) >= 5 and headers[0] == "评分项" and headers[1] == "项目名称":
        headers = ["序号", "评分项", *headers[2:]]
        normalized = []
        for row_index, row in enumerate(body, 1):
            row = row + ["-"] * (5 - len(row))
            item_no, item_name = row[0], _display_item_name(row[1])
            sequence = str(row_index)
            values = [sequence, item_name, *row[2:5]]
            if len(values) >= 5:
                values[4] = _compact_reason(values[4])
            if "得分" in headers:
                values[headers.index("得分")] = _normalize_score_cell(values[headers.index("得分")])
            if "状态" in headers and values[headers.index("状态")] == "数据不足":
                values[headers.index("状态")] = "—"
            if "原因" in headers:
                values[headers.index("原因")] = values[headers.index("原因")].replace("无法完成计算", "无法完成评估")
            normalized.append(values)
        body = normalized
    elif score_table and len(headers) >= 5 and headers[0] == "序号":
        normalized = []
        for row_index, row in enumerate(body, 1):
            row = row + ["-"] * (5 - len(row))
            item_name = _display_item_name(row[1])
            sequence = str(row_index)
            values = [sequence, item_name, *row[2:5]]
            if len(values) >= 5:
                values[4] = _compact_reason(values[4])
            if "得分" in headers:
                values[headers.index("得分")] = _normalize_score_cell(values[headers.index("得分")])
            if "状态" in headers and values[headers.index("状态")] == "数据不足":
                values[headers.index("状态")] = "—"
            if "原因" in headers:
                values[headers.index("原因")] = values[headers.index("原因")].replace("无法完成计算", "无法完成评估")
            normalized.append(values)
        body = normalized
    width_by_header = {
        "序号": "72px",
        "得分": "140px",
        "状态": "120px",
        "数量": "100px",
        "评分项": "280px",
        "项目名称": "280px",
        "票号/票据": "280px",
        "企业": "280px",
        "原因": "560px",
        "问题原因": "600px",
    }
    widths = [width_by_header.get(str(label), "220px") for label in headers]
    centered = {"序号", "评分项", "得分", "状态", "数量"}
    for reason_header in ("原因", "问题原因"):
        if reason_header not in headers:
            continue
        reason_index = headers.index(reason_header)
        reason_lengths = [
            len(str(row[reason_index]).strip())
            for row in body
            if len(row) > reason_index and str(row[reason_index]).strip()
        ]
        if reason_lengths and len(set(reason_lengths)) == 1 and max(reason_lengths) <= 30:
            centered.add(reason_header)
    head_border = "border:0;border-top:1px solid #6baee2;border-bottom:1px solid #6baee2;"
    cell = "padding:8px 12px;vertical-align:top;font-family:inherit;font-size:16px;line-height:1.6;white-space:nowrap;word-break:normal;overflow-wrap:normal;writing-mode:horizontal-tb;"
    head_html = "".join(
        f'<th style="{head_border}{cell}min-width:{widths[index]};text-align:{"center" if label in centered else "left"};color:#eef7ff;font-weight:700;">{html.escape(str(label))}</th>'
        for index, label in enumerate(headers)
    )
    body_html = []
    for row_index, row in enumerate(body):
        values = row + ["-"] * (len(headers) - len(row))
        row_border = "border:0;border-bottom:1px solid rgba(142,193,230,.35);"
        cells = "".join(
            f'<td style="{row_border}{cell}text-align:{"center" if headers[index] in centered else "left"};color:#d9eaff;">{html.escape("-" if value is None or value == "" else str(value))}</td>'
            for index, value in enumerate(values[: len(headers)])
        )
        body_html.append(f"<tr>{cells}</tr>")
    return (
        '<div style="width:100%;max-width:100%;overflow-x:auto;overflow-y:visible;margin:12px 0;scrollbar-width:thin;">'
        '<table style="width:max-content;min-width:100%;border-collapse:collapse;table-layout:auto;">'
        f"<thead><tr>{head_html}</tr></thead><tbody>{''.join(body_html)}</tbody></table></div>"
    )


class _TableStream:
    """流式识别 Markdown 表格，只延迟少量行以便在输出前转换为 HTML。"""

    def __init__(self) -> None:
        self.current = ""
        self.lookbehind: list[str] = []
        self.table_lines: list[str] = []
        self.in_table = False

    def push(self, text: str) -> list[str]:
        output: list[str] = []
        for character in str(text or ""):
            self.current += character
            if character == "\n":
                output.extend(self._line(self.current))
                self.current = ""
        return output

    def _line(self, line: str) -> list[str]:
        if self.in_table:
            if _is_table_line(line) or not line.strip():
                self.table_lines.append(line)
                return []
            rendered = _render_table_html(self.table_lines)
            self.table_lines = []
            self.in_table = False
            return [rendered, *self._line(line)]
        self.lookbehind.append(line)
        if len(self.lookbehind) >= 2 and _is_table_line(self.lookbehind[-2]) and _is_table_separator(self.lookbehind[-1]):
            self.table_lines = self.lookbehind[-2:]
            self.lookbehind = []
            self.in_table = True
            return []
        if len(self.lookbehind) > 2:
            return [self.lookbehind.pop(0)]
        return []

    def finish(self) -> list[str]:
        output: list[str] = []
        if self.current:
            output.extend(self._line(self.current + "\n"))
            self.current = ""
        if self.in_table:
            output.append(_render_table_html(self.table_lines))
            self.table_lines = []
            self.in_table = False
        output.extend(self.lookbehind)
        self.lookbehind = []
        return output


def _normalize_answer_markup(text: str) -> str:
    """服务器页面未必启用 Markdown 加粗，避免把双星号原样展示给用户。"""
    value = str(text or "")
    # 这是内部联调信息，不能出现在面向用户的评分结果中。
    value = re.sub(r"本轮\s*Java\s*接口返回评分项\s*[：:]\s*\d+\s*项\s*[。．.]?", "", value)
    value = value.replace("无法完成计算", "无法完成评估")
    value = value.replace("情况总结：", "评估总结：")
    value = value.replace("功能建设板块", "功能建设模块").replace("功能建设维度", "功能建设模块")
    value = value.replace("数据质量板块", "数据质量模块").replace("数据质量维度", "数据质量模块")
    value = value.replace("应用成效板块", "应用成效模块").replace("应用成效维度", "应用成效模块")
    value = re.sub(
        r"状态\s*(?:为|[:：])\s*数据不足\s*[（(]\s*[—-]\s*[）)]",
        "状态为数据不足",
        value,
    )
    # 总结建议必须单独成段，每条建议各占一行；修复模型压成同一行的情况。
    value = re.sub(
        r"[ \t]*(特殊作业(?:功能建设|数据质量|应用成效)模块总结建议：)[ \t]*",
        r"\n\n\1\n",
        value,
    )
    value = re.sub(r"[ \t]*[-•][ \t]*(?=建议)", "\n- ", value)
    value = re.sub(
        r"(特殊作业(?:功能建设|数据质量|应用成效)模块总结建议：)\n{2,}(?=- )",
        r"\1\n",
        value,
    )
    value = re.sub(r"\n{3,}", "\n\n", value)
    # 单项查询不向用户展示内部评分序号（例如 1.1、2.3）。
    value = re.sub(r"(?m)^\s*\d+(?:\.\d+)+[ \t]+", "", value)
    return re.sub(r"\*\*([^*\n]+)\*\*", r"\1", value)


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
    if req.conversation_id and hasattr(memory, "belongs_to") and not memory.belongs_to(conversation_id, req.user):
        # 不允许通过任意 conversation_id 读取其他用户会话；不存在时创建自己的会话。
        existing = memory.load_context(conversation_id, limit=None)
        if existing.messages or existing.summary:
            yield error_event("CONVERSATION_NOT_FOUND", "会话不存在或无权访问", 404)
            return
    memory.create_or_get(conversation_id, user_id=req.user)
    prior = memory.load_context(conversation_id, limit=get_settings().memory.window_turns * 2)
    # 历史消息已经直接放入 graph messages；memory_context 只传摘要，避免重复注入。
    memory_context = f"历史会话摘要：{prior.summary}" if prior.summary else ""
    message_id = _new_id("m")
    task_id = _new_id("t")
    created_at = int(time.time())
    # 前端 traceId 作为日志关联 ID；缺省时生成内部请求 ID。
    request_id = req.traceId or f"req_{uuid.uuid4().hex[:12]}"
    log_client = LogClient(settings.log_endpoint, settings.log_timeout_seconds)
    visible_thought = await generate_visible_thought(llm, req.query)
    await log_client.write(request_id, visible_thought)

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
        "log_client": log_client,
        "iteration": 0,
        "max_iterations": settings.max_iterations,
        "tool_calls": [],
        "last_tool_signature": None,
        "thought_position": 0,
    }

    answer_parts: list[str] = []
    table_stream = _TableStream()
    thought_parts: list[str] = []
    base = {
        "task_id": task_id,
        "id": message_id,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "created_at": created_at,
    }
    yield SSEEvent(EVENT_MESSAGE_START, {**base, "answer": ""})
    yield SSEEvent(EVENT_MESSAGE, {**base, "answer": f"<thought>{visible_thought}</thought>"})
    try:
        async for mode, payload in graph.astream(
            initial_state, stream_mode=["custom", "updates"]
        ):
            if mode != "custom":
                continue
            if payload.get("type") == "llm_token":
                content = str(payload.get("content") or "")
                if not content:
                    continue
                # 将模型 chunk 拆成字符级 SSE，前端无需额外打字机逻辑也能逐字展示。
                # thought 事件不经过此分支，仍以完整闭合标签发送。
                for character in content:
                    for output in table_stream.push(character):
                        output = _normalize_answer_markup(output)
                        answer_parts.append(output)
                        for output_character in output:
                            yield SSEEvent(EVENT_MESSAGE, {**base, "answer": output_character})
                            await asyncio.sleep(0)
            elif payload.get("type") == "agent_thought":
                # 工具执行事件只进入外部日志，不再作为 thought 返回前端。
                continue
    except Exception as e:  # 编排异常：以 error 事件结束流
        yield error_event("INTERNAL", f"Agent 编排异常：{e}", 500)
        return

    for output in table_stream.finish():
        output = _normalize_answer_markup(output)
        answer_parts.append(output)
        for output_character in output:
            yield SSEEvent(EVENT_MESSAGE, {**base, "answer": output_character})
            await asyncio.sleep(0)

    answer = "".join(answer_parts)
    memory.append_message(conversation_id, "user", req.query)
    memory.append_message(conversation_id, "assistant", answer)
    _compact_memory(memory, conversation_id)

    yield SSEEvent(
        EVENT_MESSAGE_END,
        {
            **base,
            "answer": answer,
            "metadata": {
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "retriever_resources": [],
                "finish_reason": "stop",
            },
        },
    )
