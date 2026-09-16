"""可替换的只读智能问数适配层。

评分接口和数据库问数故意解耦：未来可以把 MySQL 适配器替换成 SQLAlchemy、Trino、
数据服务 API 或企业内部查询平台，而不修改 Skill/Agent 编排。
"""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import httpx
from typing import Protocol


@dataclass(frozen=True)
class DataQueryResult:
    ok: bool
    observation: str
    columns: list[str]
    rows: list[dict]
    error_code: str | None = None


class DataQueryService(Protocol):
    async def ask(self, question: str, table_hint: str = "") -> DataQueryResult: ...


class DisabledDataQueryService:
    """默认实现：未配置数据库时安全拒绝执行，不猜测数据。"""

    async def ask(self, question: str, table_hint: str = "") -> DataQueryResult:
        return DataQueryResult(
            False,
            "智能问数尚未配置数据库连接，当前不能读取数据库明细。请先配置数据库地址、端口、账号和密码。",
            [],
            [],
            "DATA_QUERY_NOT_CONFIGURED",
        )


class ReadOnlySQLDataQueryService:
    """受限 MySQL 只读适配器。

    该适配器只接受应用内生成的 SELECT 查询；当前 Skill 默认不接受用户直接传 SQL，
    因此后续可在此处接入 SQL 生成器、表白名单和列级脱敏策略。
    """

    def __init__(self, connection_factory=None, allowed_tables: set[str] | None = None, max_rows: int = 100, gateway_url: str = ""):
        self._connection_factory = connection_factory
        self._allowed_tables = allowed_tables or set()
        self._max_rows = max(1, min(max_rows, 500))
        self._gateway_url = gateway_url.rstrip("/")

    @staticmethod
    def validate_select(sql: str, allowed_tables: set[str]) -> tuple[bool, str]:
        normalized = " ".join(sql.strip().lower().split())
        if not normalized.startswith("select "):
            return False, "仅允许只读 SELECT 查询"
        forbidden = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "create ", "grant ", ";", "--", "/*")
        if any(token in normalized for token in forbidden):
            return False, "查询包含被禁止的写入或多语句操作"
        if allowed_tables and not any(f" {table.lower()} " in f" {normalized} " for table in allowed_tables):
            return False, "查询涉及未授权的数据表"
        return True, ""

    async def ask(self, question: str, table_hint: str = "") -> DataQueryResult:
        table = self._choose_table(question, table_hint)
        if not table:
            return DataQueryResult(False, "暂不支持该类数据库查询，请查询评分结果、问题票据或企业明细。", [], [], "DATA_QUERY_UNSUPPORTED")
        # 白名单表结构并不统一，不能假设所有表都有 deleted 字段；网关本身只读，直接限制行数。
        sql = f"SELECT * FROM `{table}` LIMIT {self._max_rows}"
        try:
            if self._gateway_url:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(f"{self._gateway_url}/sql", json={"sql": sql})
                    response.raise_for_status()
                    payload = response.json()
                if not payload.get("ok"):
                    return DataQueryResult(False, "数据库查询暂时不可用，请稍后重试。", [], [], "DATA_QUERY_FAILED")
                columns = [str(c) for c in payload.get("cols", [])]
                rows = [dict(zip(columns, [str(v) for v in row])) for row in payload.get("rows", [])]
                return DataQueryResult(True, f"已查询到 {len(rows)} 条数据库记录。", columns, rows)
            return await asyncio.to_thread(self._execute, sql, ())
        except Exception:
            return DataQueryResult(False, "数据库查询暂时不可用，请稍后重试。", [], [], "DATA_QUERY_FAILED")

    def _choose_table(self, question: str, table_hint: str) -> str:
        hint = str(table_hint or "").strip().lower()
        if hint in self._allowed_tables:
            return hint
        text = str(question or "")
        if any(word in text for word in ("企业信息", "企业列表", "有哪些企业", "公司信息")):
            return "das_company_info"
        if any(word in text for word in ("企业", "公司", "作业票", "票据", "问题")):
            return "das_score_issue_entity"
        if "维度" in text:
            return "das_score_dimension_result"
        if "评分" in text or "得分" in text:
            return "das_score_result"
        return "das_score_issue"

    def _execute(self, sql: str, params: tuple) -> DataQueryResult:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                columns = [str(item[0]) for item in cursor.description or []]
            safe_rows = []
            for row in rows:
                clean = {}
                for key, value in dict(row).items():
                    if any(token in str(key).lower() for token in ("password", "token", "secret")):
                        clean[key] = "***"
                    else:
                        clean[key] = value
                safe_rows.append(clean)
            return DataQueryResult(True, f"已查询到 {len(safe_rows)} 条数据库记录。", columns, safe_rows)
        finally:
            connection.close()


# 结果表说明中明确列出的可查询表白名单；默认只允许这些结果/票据快照表。
SCORE_RESULT_TABLES = frozenset({
    "das_company_info",
    "das_score_batch_sequence",
    "das_score_batch",
    "das_score_result",
    "das_score_dimension_result",
    "das_score_issue",
    "das_score_issue_entity",
    "das_work_ticket_evaluate_result",
})
