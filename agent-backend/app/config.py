"""应用配置（pydantic-settings）。

优先级：环境变量 > config/settings.yaml > 代码默认值。
环境变量前缀：
  AGENT_   -> 服务级配置（如 AGENT_MAX_ITERATIONS=3）
  LLM_     -> 大模型配置（如 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL）
  AUTH_    -> 鉴权配置（如 AUTH_ENABLED=true、AUTH_API_KEYS='["k1","k2"]'）
  TOOL_    -> 工具注册表配置（如 TOOL_CONFIG_PATH=config/tools.yaml）
  MEMORY_  -> 会话存储配置（如 MEMORY_BACKEND=redis）
"""

from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any, Type

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

BASE_DIR = Path(__file__).resolve().parent.parent


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", env_ignore_empty=True)

    # openai | mock（mock 用于本地联调，不请求真实 LLM）
    mode: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout_seconds: float = 60.0


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_ignore_empty=True)

    # 是否启用 Bearer API Key 校验（生产必须开启）
    enabled: bool = False
    # 允许的 API Key 列表
    api_keys: list[str] = []


class ToolSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOOL_", env_ignore_empty=True)

    # 工具注册表文件路径（相对项目根或绝对路径）
    config_path: str = "config/tools.yaml"


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORY_", env_ignore_empty=True)

    # mysql | sqlite | memory | redis
    backend: str = "mysql"
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = "root"
    database: str = "agent_memory"
    redis_url: str = "redis://localhost:6379/0"
    ttl_days: int = 7
    sqlite_path: str = "data/memory.db"
    window_turns: int = 6
    window_chars: int = 12000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_ignore_empty=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 优先级：初始化参数 > 环境变量 > config/settings.yaml
        yaml_file = str(BASE_DIR / "config" / "settings.yaml")
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(
                settings_cls,
                yaml_file=yaml_file,
                yaml_file_encoding="utf-8",
            ),
        )

    app_name: str = "agent-service"
    # function calling 循环最大迭代次数
    max_iterations: int = 5
    # 系统提示词外部文件路径（空=使用内置默认，见 app/graph/prompts.py）
    system_prompt_file: str = ""
    # 工具 observation 截断长度
    observation_truncate_chars: int = 2000
    # SSE 心跳间隔（秒）
    sse_ping_interval_seconds: float = 20.0
    # 单请求总超时（秒）
    request_timeout_seconds: float = 120.0

    llm: LLMSettings = LLMSettings()
    auth: AuthSettings = AuthSettings()
    tools: ToolSettings = ToolSettings()
    memory: MemorySettings = MemorySettings()

    @property
    def tools_config_abspath(self) -> Path:
        p = Path(self.tools.config_path)
        return p if p.is_absolute() else BASE_DIR / p


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    # 兼容本地启动脚本使用的 LLM_* 环境变量。Pydantic Settings 对嵌套
    # LLMSettings 不会自动读取无分隔符的旧式变量，因此在这里显式覆盖。
    env_fields = {
        "mode": ("LLM_MODE", str),
        "base_url": ("LLM_BASE_URL", str),
        "api_key": ("LLM_API_KEY", str),
        "model": ("LLM_MODEL", str),
        "temperature": ("LLM_TEMPERATURE", float),
        "max_tokens": ("LLM_MAX_TOKENS", int),
        "timeout_seconds": ("LLM_TIMEOUT_SECONDS", float),
    }
    values: dict[str, Any] = {}
    for field, (env_name, converter) in env_fields.items():
        raw = os.environ.get(env_name)
        if raw:
            values[field] = converter(raw)
    if values:
        settings.llm = LLMSettings.model_validate(
            {**settings.llm.model_dump(), **values}
        )

    # AUTH_* 环境变量覆盖（Docker/生产部署用，nested model 不会自动读取）
    auth_values: dict[str, Any] = {}
    raw = os.environ.get("AUTH_ENABLED")
    if raw:
        auth_values["enabled"] = raw.strip().lower() in ("1", "true", "yes", "on")
    raw = os.environ.get("AUTH_API_KEYS")
    if raw:
        try:
            auth_values["api_keys"] = json.loads(raw)
        except Exception:
            auth_values["api_keys"] = [k.strip() for k in raw.split(",") if k.strip()]
    if auth_values:
        settings.auth = AuthSettings.model_validate(
            {**settings.auth.model_dump(), **auth_values}
        )

    # MEMORY_* 环境变量覆盖（Docker/生产部署用，nested model 不会自动读取）
    memory_env = {
        "backend": ("MEMORY_BACKEND", str),
        "host": ("MEMORY_HOST", str),
        "port": ("MEMORY_PORT", int),
        "user": ("MEMORY_USER", str),
        "password": ("MEMORY_PASSWORD", str),
        "database": ("MEMORY_DATABASE", str),
        "window_turns": ("MEMORY_WINDOW_TURNS", int),
        "window_chars": ("MEMORY_WINDOW_CHARS", int),
    }
    memory_values: dict[str, Any] = {}
    for field, (env_name, converter) in memory_env.items():
        raw = os.environ.get(env_name)
        if raw:
            memory_values[field] = converter(raw)
    if memory_values:
        settings.memory = MemorySettings.model_validate(
            {**settings.memory.model_dump(), **memory_values}
        )
    return settings
