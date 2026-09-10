"""工具配置加载：从 YAML 加载 ToolConfig 列表并构建注册中心。"""

from pathlib import Path
from typing import Any

import yaml

from app.tools.protocol import ToolConfig
from app.tools.registry import ToolRegistry


def load_tool_configs(path: str | Path) -> list[ToolConfig]:
    """从 YAML 文件加载工具配置（tools: [...] 顶层键）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"工具配置文件不存在：{p}")
    data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    raw_tools = data.get("tools", [])
    return [ToolConfig.model_validate(t) for t in raw_tools]


def build_registry(path: str | Path) -> ToolRegistry:
    return ToolRegistry(load_tool_configs(path))
