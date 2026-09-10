"""LangGraph 状态定义（docs/agent-design.md §4.2）。"""

from typing import TypedDict

from app.llm.client import ToolCall


class AgentState(TypedDict):
    messages: list[dict]
    memory_context: str
    user_id: str
    request_id: str
    user_token: str
    inputs: dict
    iteration: int
    max_iterations: int
    tool_calls: list[ToolCall]
    last_tool_signature: str | None
    thought_position: int
