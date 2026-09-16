"""异步调用外部日志服务；日志失败不影响主问答链路。"""
from __future__ import annotations

import httpx


class LogClient:
    def __init__(self, endpoint: str, timeout_seconds: float = 3.0):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    async def write(self, trace_id: str, message: str) -> None:
        if not self.endpoint or not message:
            return
        payload = {"traceId": trace_id, "logmessage": message}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.endpoint, json=payload)
                response.raise_for_status()
        except Exception:
            # 日志服务不可用时不能阻塞评分和问答。
            return


async def generate_visible_thought(llm, query: str) -> str:
    """返回面向普通用户的三步执行说明，不展示隐藏思维链。"""
    return thought_for_query(query)


def thought_for_query(query: str) -> str:
    """生成简短、可展示的三步执行说明，不暴露隐藏推理或内部参数。"""
    if any(word in query for word in ("数据库", "明细", "历史", "批次", "记录", "作业票")):
        return (
            "第一步：确认你要查询的企业、评分或作业票信息。\n"
            "第二步：调用数据查询服务，读取当前可核验的记录。\n"
            "第三步：整理查询结果，用清楚的文字或表格返回。"
        )
    if any(word in query for word in ("扣分", "原因", "为什么", "评分项")):
        return (
            "第一步：确认你关注的评分项和需要说明的问题。\n"
            "第二步：调用特殊作业评分服务，读取当前得分、状态和判定原因。\n"
            "第三步：把核查结果整理成易懂的说明，并给出对应建议。"
        )
    return (
        "第一步：确认你要查看的是总分、评分维度还是具体评分项。\n"
        "第二步：调用特殊作业评分服务，读取当前评分结果。\n"
        "第三步：整理得分、状态和原因，用清楚的方式返回。"
    )
