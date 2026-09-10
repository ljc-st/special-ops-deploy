"""LangGraph 图构建：agent（LLM 决策/润色）↔ tools（执行 Java 接口）双节点循环。

流程（docs/agent-design.md §4）：
  START -> agent --(有 tool_calls 且 iteration<上限)--> tools -> agent
                └--(无 tool_calls 或达上限)--> END

流式输出：节点内用 get_stream_writer() 推送自定义事件
  - {"type": "llm_token", "content": 增量文本}
  - {"type": "agent_thought", position, tool, tool_input, observation, tool_status}
外层 runner 通过 graph.astream(stream_mode=["custom", "updates"]) 消费并转 SSE。
"""

import json
from typing import Callable

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.graph.prompts import get_system_prompt
from app.graph.state import AgentState
from app.llm.client import (
    ChatClient,
    ToolCall,
    ToolCallDelta,
    accumulate_tool_calls,
)
from app.tools.protocol import ExecContext, ToolResult, dump_json
from app.tools.registry import ToolRegistry


async def _stream_llm(
    llm: ChatClient,
    messages: list[dict],
    tools: list[dict] | None,
    writer,
    emit_content: bool = True,
) -> tuple[str, list[ToolCallDelta]]:
    """调用 LLM 流式生成，把 token 增量推给外层（llm_token 事件）。"""
    content_parts: list[str] = []
    tool_deltas: list[ToolCallDelta] = []
    async for chunk in llm.stream_chat(messages, tools=tools):
        if chunk.content:
            content_parts.append(chunk.content)
            if emit_content:
                writer({"type": "llm_token", "content": chunk.content})
        if chunk.tool_call_deltas:
            tool_deltas.extend(chunk.tool_call_deltas)
    return "".join(content_parts), tool_deltas


def _structured_observation(messages: list[dict]) -> str:
    """查找技能已经生成的多项评分表，作为格式契约的事实来源。"""
    table_markers = {
        "| 评分项 | 项目名称 | 得分 | 状态 | 原因 |": 3,
        "| 评分项 | 票号/票据 | 企业 | 问题原因 |": 2,
        "| 园区 | 得分 | 结论 |": 1,
    }
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        observation = message.get("content")
        if not isinstance(observation, str):
            continue
        for marker, minimum_rows in table_markers.items():
            if marker not in observation:
                continue
            rows = [
                line
                for line in observation.splitlines()
                if line.strip().startswith("|")
                and line.strip() != marker.strip()
                and line.strip().replace("|", "").replace("-", "").replace(":", "").strip()
            ]
            if len(rows) >= minimum_rows:
                return observation
    return ""


def _preserve_score_table(content: str, messages: list[dict]) -> str:
    """模型把多项表格改写成列表时，恢复工具返回的完整表格。"""
    observation = _structured_observation(messages)
    table_markers = (
        "| 评分项 | 项目名称 | 得分 | 状态 | 原因 |",
        "| 评分项 | 票号/票据 | 企业 | 问题原因 |",
        "| 园区 | 得分 | 结论 |",
    )
    if not observation or any(marker in content for marker in table_markers):
        return content
    return observation


def _split_pipe_row(line: str) -> list[str]:
    """拆分 Markdown 表格行，同时还原原因中的转义竖线。"""
    source = line.strip()
    if source.startswith("|"):
        source = source[1:]
    if source.endswith("|") and not source.endswith("\\|"):
        source = source[:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(source):
        character = source[index]
        if character == "\\" and index + 1 < len(source) and source[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _normalize_score_item_table(content: str) -> str:
    """评分项少于三条时，把模型误生成的表格恢复为逐项列表。"""
    marker = "| 评分项 | 项目名称 | 得分 | 状态 | 原因 |"
    lines = content.splitlines()
    for start, line in enumerate(lines):
        if line.strip() != marker or start + 1 >= len(lines):
            continue
        separator = _split_pipe_row(lines[start + 1])
        if not separator or not all(cell and set(cell) <= {"-", ":"} for cell in separator):
            continue
        end = start + 2
        rows: list[list[str]] = []
        while end < len(lines) and lines[end].strip().startswith("|") and lines[end].strip().endswith("|"):
            rows.append(_split_pipe_row(lines[end]))
            end += 1
        if not rows or len(rows) >= 3:
            continue
        rendered: list[str] = []
        for row in rows:
            normalized = [*row, "-", "-", "-", "-"][:5]
            rendered.append(
                f"- {normalized[0]} {normalized[1]}：{normalized[2]}，"
                f"{normalized[3]}；原因：{normalized[4]}"
            )
        return "\n".join(lines[:start] + rendered + lines[end:])
    return content


def _with_system_prompt(messages: list[dict], memory_context: str = "") -> list[dict]:
    """在消息最前面注入系统提示词（仅当尚无 system 消息时，多轮不重复）。"""
    if any(m.get("role") == "system" for m in messages):
        return messages
    result = [{"role": "system", "content": get_system_prompt()}]
    if memory_context:
        result.append({"role": "system", "content": memory_context})
    return result + messages


def _fallback_tool_answer(messages: list[dict]) -> str:
    """模型没有生成文本时，至少返回最近一次接口事实，避免空的成功响应。"""
    for message in reversed(messages):
        if message.get("role") == "tool" and str(message.get("content") or "").strip():
            return f"根据本轮评分接口结果：\n{message['content']}"
    return ""


def _make_agent_node(
    llm: ChatClient, registry: ToolRegistry
) -> Callable[[AgentState], dict]:
    async def agent_node(state: AgentState) -> dict:
        writer = get_stream_writer()
        messages = _with_system_prompt(state["messages"], state.get("memory_context", ""))
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        content, tool_deltas = await _stream_llm(
            llm,
            messages,
            registry.llm_schemas(),
            writer,
            emit_content=True,
        )
        tool_calls = accumulate_tool_calls(tool_deltas)
        if has_tool_result:
            if not content.strip() and not tool_calls:
                content = _fallback_tool_answer(messages)
                if content:
                    writer({"type": "llm_token", "content": content})
            content = _normalize_score_item_table(content)
            content = _preserve_score_table(content, messages)

        assistant: dict = {"role": "assistant", "content": content or None}
        if tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": dump_json(c.arguments)},
                }
                for c in tool_calls
            ]
        return {
            "messages": messages + [assistant],
            "tool_calls": tool_calls,
            "iteration": state["iteration"],
        }

    return agent_node


def _make_finalize_node(llm: ChatClient) -> Callable[[AgentState], dict]:
    """达到迭代上限时强制收尾：不带工具参数，让 LLM 基于已有 observation 作答。"""

    async def finalize_node(state: AgentState) -> dict:
        writer = get_stream_writer()
        messages = _with_system_prompt(state["messages"], state.get("memory_context", ""))
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        content, _ = await _stream_llm(
            llm, messages, None, writer, emit_content=True
        )
        if has_tool_result:
            if not content.strip():
                content = _fallback_tool_answer(messages)
                if content:
                    writer({"type": "llm_token", "content": content})
            content = _normalize_score_item_table(content)
            content = _preserve_score_table(content, messages)
        if not content:
            content = "抱歉，暂时无法获取答案，请稍后再试。"
            writer({"type": "llm_token", "content": content})
        return {
            "messages": messages + [{"role": "assistant", "content": content}]
        }

    return finalize_node


def safe_tool_observation(result: ToolResult) -> str:
    if result.ok:
        return result.observation
    return "\u8bc4\u5206\u6570\u636e\u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"


def _make_tools_node(registry: ToolRegistry) -> Callable[[AgentState], dict]:
    async def tools_node(state: AgentState) -> dict:
        writer = get_stream_writer()
        ctx = ExecContext(
            user_id=state["user_id"],
            request_id=state["request_id"],
            user_token=state["user_token"],
            inputs=state["inputs"],
        )
        tool_msgs: list[dict] = []
        position = state["thought_position"]

        # 震荡检测：与上一轮相同的 (tool, args) 签名 → 中断循环
        current_sig = dump_json([(c.name, c.arguments) for c in state["tool_calls"]])
        oscillating = state.get("last_tool_signature") == current_sig

        for call in state["tool_calls"]:
            writer(
                {
                    "type": "agent_thought",
                    "position": position,
                    "thought": "",
                    "tool": call.name,
                    "tool_input": call.arguments,
                    "observation": "",
                    "tool_status": "started",
                }
            )
            if oscillating:
                result = ToolResult(
                    False,
                    f"检测到工具 [{call.name}] 调用重复（同一参数），已停止继续调用，请基于已有信息回答",
                    error_code="TOOL_LOOP",
                )
            else:
                result = await registry.execute(call, ctx)
            writer(
                {
                    "type": "agent_thought",
                    "position": position,
                    "thought": "",
                    "tool": call.name,
                    "tool_input": {},
                    "observation": result.observation[:500],
                    "tool_status": "succeeded" if result.ok else "failed",
                }
            )
            tool_msgs.append({"role": "tool", "tool_call_id": call.id, "content": safe_tool_observation(result)})
            position += 1

        next_iteration = state["iteration"] + 1
        if oscillating:
            next_iteration = state["max_iterations"]  # 强制下一轮收尾回答
        return {
            "messages": state["messages"] + tool_msgs,
            "tool_calls": [],
            "iteration": next_iteration,
            "thought_position": position,
            "last_tool_signature": current_sig,
        }

    return tools_node


def _route(state: AgentState) -> str:
    if state["tool_calls"]:
        if state["iteration"] < state["max_iterations"]:
            return "tools"
        return "finalize"  # 达上限：强制收尾回答
    return "end"


def build_graph(
    llm: ChatClient, registry: ToolRegistry, max_iterations: int = 5
):
    """构建编译后的 LangGraph（max_iterations 同时写入 state 供节点读取）。"""

    def entry(state: AgentState) -> AgentState:
        state["max_iterations"] = max_iterations
        return state

    g = StateGraph(AgentState)
    g.add_node("entry", entry)
    g.add_node("agent", _make_agent_node(llm, registry))
    g.add_node("tools", _make_tools_node(registry))
    g.add_node("finalize", _make_finalize_node(llm))
    g.add_edge(START, "entry")
    g.add_edge("entry", "agent")
    g.add_conditional_edges(
        "agent", _route, {"tools": "tools", "finalize": "finalize", "end": END}
    )
    g.add_edge("tools", "agent")
    g.add_edge("finalize", END)
    return g.compile()
