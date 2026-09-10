"""工具注册中心：名字 → 配置 + 执行器的分发。"""

from typing import Any

from app.llm.client import ToolCall
from app.tools.executor import HttpToolExecutor, MockToolExecutor
from app.tools.protocol import (
    ExecContext,
    ToolConfig,
    ToolExecutor,
    ToolResult,
)
from app.tools.skills import SkillExecutor


class ToolRegistry:
    """按 executor_type 分发到对应执行器；LLM 侧只见 llm_schemas。"""

    def __init__(
        self,
        configs: list[ToolConfig],
        executors: dict[str, ToolExecutor] | None = None,
    ):
        self._by_name: dict[str, ToolConfig] = {c.name: c for c in configs}
        self._executors: dict[str, ToolExecutor] = dict(
            executors
            or {
                "http": HttpToolExecutor(),
                "mock": MockToolExecutor(),
            }
        )
        # 技能执行器依赖底层工具 runner（registry.execute），后置注入
        if "skill" not in self._executors:
            self._executors["skill"] = SkillExecutor(self._run_tool)

    async def _run_tool(self, name: str, args: dict, ctx: ExecContext) -> ToolResult:
        """技能内部的底层工具调用入口。"""
        return await self.execute(ToolCall(id="skill_internal", name=name, arguments=args), ctx)

    @property
    def names(self) -> list[str]:
        return list(self._by_name)

    def get(self, name: str) -> ToolConfig | None:
        return self._by_name.get(name)

    def llm_schemas(self) -> list[dict]:
        """给 LLM 的 function calling 定义（白名单：仅注册过的工具）。"""
        return [c.to_llm_schema() for c in self._by_name.values()]

    async def execute(self, call: ToolCall, ctx: ExecContext | None = None) -> ToolResult:
        config = self._by_name.get(call.name)
        if config is None:
            return ToolResult(
                False,
                f"工具 [{call.name}] 未注册，无法调用",
                error_code="TOOL_NOT_FOUND",
            )
        executor = self._executors.get(config.executor_type)
        if executor is None:
            return ToolResult(
                False,
                f"工具 [{call.name}] 的执行器类型 [{config.executor_type}] 未注册",
                error_code="TOOL_NOT_FOUND",
            )
        return await executor.execute(call, config, ctx or ExecContext())
