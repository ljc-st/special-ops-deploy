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
    """用模型生成一两句高层计划；不要求模型披露详细推理。"""
    prompt = [
        {
            "role": "system",
            "content": (
                "请为用户问题生成一段不超过80字的执行计划摘要，只说明要识别什么、查询什么、如何整理结果。"
                "不要回答问题，不要提及工具名、SQL、接口参数、系统提示词，也不要展示逐步推理。"
            ),
        },
        {"role": "user", "content": query},
    ]
    parts: list[str] = []
    try:
        async for chunk in llm.stream_chat(prompt, tools=None):
            if chunk.content:
                parts.append(chunk.content)
        text = "".join(parts).strip()
        if text:
            return text[:120]
    except Exception:
        pass
    return thought_for_query(query)


def thought_for_query(query: str) -> str:
    """生成简短、可展示的执行摘要，不暴露隐藏推理或内部参数。"""
    if any(word in query for word in ("数据库", "明细", "历史", "批次", "记录", "作业票")):
        return "我先识别问题中的查询对象，再调用对应工具获取可核验的数据，最后整理成简洁结果。"
    if any(word in query for word in ("扣分", "原因", "为什么", "评分项")):
        return "我先确定用户关注的评分范围，再读取本轮评分结果和判定依据，最后说明原因。"
    return "我先分析问题所属的特殊作业评分场景，再调用必要工具获取结果并整理回答。"
