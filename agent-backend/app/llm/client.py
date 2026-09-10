"""LLM 客户端抽象与实现。

消息统一使用 OpenAI 格式（dict 列表）：
  {"role": "user", "content": "..."}
  {"role": "assistant", "content": null, "tool_calls": [...]}
  {"role": "tool", "tool_call_id": "...", "content": "observation"}

- OpenAIChatClient：真实调用（LLM_MODE=openai），流式 + function calling。
- MockChatClient：本地模拟（默认 LLM_MODE=mock），支持自动工具循环剧本，
  用于无 API Key 时的联调与自动化测试。
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.config import LLMSettings


@dataclass
class ToolCallDelta:
    """流式 tool_call 增量片段。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class ChatChunk:
    """一次流式输出片断。"""

    content: str = ""
    tool_call_deltas: list[ToolCallDelta] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@dataclass
class ToolCall:
    """完整工具调用（增量累积后）。"""

    id: str
    name: str
    arguments: dict[str, Any]


class ChatClient(ABC):
    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatChunk]:
        """流式对话。messages 为 OpenAI 格式，tools 为 function calling 定义。"""
        raise NotImplementedError


def accumulate_tool_calls(deltas: list[ToolCallDelta]) -> list[ToolCall]:
    """把流式 tool_call 增量按 index 合并为完整 ToolCall（arguments 解析为 dict）。"""
    merged: dict[int, dict[str, str]] = {}
    for d in deltas:
        acc = merged.setdefault(d.index, {"id": "", "name": "", "arguments": ""})
        if d.id:
            acc["id"] = d.id
        if d.name:
            acc["name"] = d.name
        if d.arguments_delta:
            acc["arguments"] += d.arguments_delta
    calls: list[ToolCall] = []
    for idx in sorted(merged):
        acc = merged[idx]
        raw = acc["arguments"].strip()
        try:
            args: dict[str, Any] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = {"_raw": raw}
        calls.append(ToolCall(id=acc["id"], name=acc["name"], arguments=args))
    return calls


class OpenAIChatClient(ChatClient):
    """OpenAI 兼容接口客户端（base_url 可指向 DeepSeek/通义/Kimi 等）。"""

    def __init__(self, settings: LLMSettings, http_client: Any = None):
        from openai import AsyncOpenAI

        self.settings = settings
        # http_client 注入用于测试（httpx MockTransport）
        self._client = AsyncOpenAI(
            base_url=settings.base_url or None,
            api_key=settings.api_key or "sk-none",
            http_client=http_client,
        )
        self._model = settings.model

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatChunk]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            if not chunk.choices:
                if getattr(chunk, "usage", None) is not None:
                    yield ChatChunk(usage=chunk.usage.model_dump())
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            tcds: list[ToolCallDelta] | None = None
            if delta.tool_calls:
                tcds = []
                for tc in delta.tool_calls:
                    fn = tc.function
                    tcds.append(
                        ToolCallDelta(
                            index=tc.index,
                            id=tc.id,
                            name=fn.name if fn else None,
                            arguments_delta=(fn.arguments or "") if fn else "",
                        )
                    )
            yield ChatChunk(
                content=delta.content or "",
                tool_call_deltas=tcds,
                finish_reason=choice.finish_reason,
            )


class MockChatClient(ChatClient):
    """本地模拟 LLM（默认模式，无网络请求）。

    无 script 时的自动行为（按消息内容推断）：
      - messages 含 role=tool -> 用最近一个工具结果生成自然语言回答（流式分片）；
      - 无工具结果且提供了 tools -> 发出一个 tool_call（优先 query_user_order）；
      - 其他 -> 直接流式回答（复述用户输入）。

    script（可选）精确控制每次 stream_chat 的输出：
      [{"type": "text", "text": "..."},
       {"type": "tool_call", "name": "...", "arguments": {...}}]
    """

    def __init__(
        self,
        settings: LLMSettings | None = None,
        chunk_size: int = 8,
        script: list[dict] | None = None,
    ):
        self.settings = settings
        self.chunk_size = chunk_size
        self.script = script or []
        self._script_pos = 0

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatChunk]:
        if self._script_pos < len(self.script):
            step = self.script[self._script_pos]
            self._script_pos += 1
            if step["type"] == "tool_call":
                async for chunk in self._emit_tool_call(
                    step.get("name", ""), step.get("arguments", {})
                ):
                    yield chunk
            else:
                async for chunk in self._emit_text(step.get("text", "")):
                    yield chunk
            return

        tool_results = [m for m in messages if m.get("role") == "tool"]
        if tool_results:
            observation = tool_results[-1]["content"]
            # 扩展评估的关键指标通常位于响应中后段；本地 mock 也应保留足够内容供前端摘要提取。
            limit = 8000 if any(
                key in observation
                for key in (
                    "coverageRate",
                    "associatedTicketCount",
                    "associationMode",
                    "【特殊作业",
                )
            ) else 200
            text = f"根据查询结果：{observation[:limit]}"
            async for chunk in self._emit_text(text):
                yield chunk
        elif tools:
            last_user = [m for m in messages if m.get("role") == "user"][-1]["content"]
            name, schema = self._select_mock_tool(last_user, tools)
            arguments = self._guess_arguments(schema, last_user)
            async for chunk in self._emit_tool_call(name, arguments):
                yield chunk
        else:
            last_user = [m for m in messages if m.get("role") == "user"][-1]["content"]
            async for chunk in self._emit_text(f"（直答）{last_user}"):
                yield chunk

    def _emit_text(self, text: str) -> AsyncIterator[ChatChunk]:
        async def gen():
            for i in range(0, len(text), self.chunk_size):
                yield ChatChunk(content=text[i : i + self.chunk_size])
            yield ChatChunk(finish_reason="stop")

        return gen()

    def _emit_tool_call(self, name: str, arguments: dict) -> AsyncIterator[ChatChunk]:
        raw = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))

        async def gen():
            yield ChatChunk(
                tool_call_deltas=[ToolCallDelta(index=0, id="call_mock", name=name)]
            )
            step = max(1, len(raw) // 3)
            for i in range(0, len(raw), step):
                yield ChatChunk(tool_call_deltas=[ToolCallDelta(index=0, arguments_delta=raw[i : i + step])])
            yield ChatChunk(finish_reason="tool_calls")

        return gen()

    @staticmethod
    def _infer_special_item_no(query: str) -> str | None:
        """Infer an unambiguous special score item for local mock routing tests."""
        if any(token in query for token in ("报备有效性", "有报备无作业票")):
            return "3.1"
        if any(token in query for token in ("作业票有效性", "有作业票无报备")):
            return "3.2"
        if any(token in query for token in ("抽查功能应用活跃度", "抽查近N天有更新", "抽查近n天有更新", "抽查功能使用情况")):
            return "3.5"
        if any(token in query for token in ("报备功能应用活跃度", "报备近N天有更新", "报备近n天有更新")):
            return "3.4"
        if any(token in query for token in ("作业票功能应用活跃度", "作业票近N天有更新", "作业票近n天有更新")):
            return "3.3"
        if any(token in query for token in ("报备重复率", "作业票重复率", "电子票重复率", "数据冗余", "重复数据")):
            return "2.1"
        if "报备接入率" in query:
            return "2.2"
        if any(token in query for token in ("作业票接入率", "电子票接入率")):
            return "2.3"
        match = re.search(r"(?<!\d)([123]\.\d+(?:\.\d+)?)(?!\d)", query)
        return match.group(1) if match else None

    @staticmethod
    def _guess_arguments(function: dict, query: str = "") -> dict:
        """按工具 schema 猜测参数（测试用）：required 字段优先。"""
        params = (function.get("parameters") or {}).get("properties", {})
        required = (function.get("parameters") or {}).get("required", [])
        args: dict[str, Any] = {}
        for name in required:
            spec = params.get(name, {})
            t = spec.get("type", "string")
            if t == "integer":
                args[name] = 1
            elif t == "boolean":
                args[name] = True
            elif name.lower() in ("userid", "user_id", "operator"):
                args[name] = "u_10001"
            elif name.lower() == "parkid":
                # 本地联调时从自然语言中提取 UUID，避免扩展评估请求使用占位园区。
                match = re.search(
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                    query,
                )
                args[name] = match.group(0) if match else "test"
            else:
                args[name] = "test"
        if "itemNo" in params and "itemNo" not in args:
            item_no = MockChatClient._infer_special_item_no(query)
            if item_no:
                args["itemNo"] = item_no
        return args

    @staticmethod
    def _select_mock_tool(query: str, tools: list[dict]) -> tuple[str, dict]:
        """Give local mock mode deterministic intent routing for the special module."""
        lowered = query.lower()
        names = {tool["function"]["name"]: tool["function"] for tool in tools}
        # 先处理应用成效和数据质量的明确单项，避免“抽查功能/报备功能”等词被
        # 误路由到 1.x 功能建设技能。
        item_no = MockChatClient._infer_special_item_no(query)
        if item_no and item_no.startswith("3.") and "special_application_effect_evaluation" in names:
            return "special_application_effect_evaluation", names["special_application_effect_evaluation"]
        if item_no and item_no.startswith("2.") and "special_data_quality_evaluation" in names:
            return "special_data_quality_evaluation", names["special_data_quality_evaluation"]
        if (
            any(token in query for token in ("报备功能建设", "特殊作业报备功能建设", "近n月有报备", "近N月有报备", "有报备数据"))
            or ("1.1" in query and any(token in query for token in ("特殊作业", "报备", "功能建设")))
        ):
            target = "special_report_function_build"
            if target in names:
                return target, names[target]
        if (
            any(token in query for token in ("作业票管理功能建设", "特殊作业票管理功能建设", "近n月有作业票", "近N月有作业票", "有作业票数据"))
            or ("1.2" in query and any(token in query for token in ("特殊作业", "作业票", "功能建设")))
        ):
            target = "special_ticket_function_build"
            if target in names:
                return target, names[target]
        if (
            any(token in query for token in ("抽查功能建设", "特殊作业抽查功能建设", "近n月有抽查", "近N月有抽查", "有抽查数据"))
            or ("1.3" in query and any(token in query for token in ("特殊作业", "抽查", "功能建设")))
        ):
            target = "special_inspection_function_build"
            if target in names:
                return target, names[target]
        if (
            any(token in query for token in ("数据质量", "数据完整性", "接入率", "重复率"))
            or ("2." in query and "特殊作业" in query)
        ):
            target = "special_data_quality_evaluation"
            if target in names:
                return target, names[target]
        if (
            any(token in query for token in ("应用成效", "应用效果", "实际使用", "关联作业"))
            or ("3." in query and "特殊作业" in query)
        ):
            target = "special_application_effect_evaluation"
            if target in names:
                return target, names[target]
        if any(token in query for token in ("覆盖率", "抽检关联", "关联作业", "扩展评估", "安全措施落实")):
            target = "special_extended_evaluation"
            if target in names:
                return target, names[target]
        if any(token in query for token in ("扣分", "哪些项", "为什么扣")):
            target = "special_score_drilldown"
            if target in names:
                return target, names[target]
        if any(token in query for token in ("哪张票", "问题票", "问题作业票", "哪些作业票", "有问题作业票", "票据明细")):
            target = "special_ticket_issue"
            if target in names:
                return target, names[target]
        target = "special_score_overview"
        if any(token in query for token in ("特殊作业", "作业票", "作业报备")) and target in names:
            return target, names[target]
        first = tools[0]["function"]
        return first["name"], first


def create_chat_client(settings: LLMSettings, http_client: Any = None) -> ChatClient:
    """按配置创建 LLM 客户端。LLM_MODE=openai 用真实接口，否则用 Mock。"""
    if settings.mode == "openai":
        return OpenAIChatClient(settings, http_client=http_client)
    return MockChatClient(settings)
