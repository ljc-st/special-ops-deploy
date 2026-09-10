"""SSE 流式响应封装：心跳注入、断连时的资源清理。"""

import asyncio
import time
from typing import AsyncIterator

from app.sse.event import EVENT_PING, SSEEvent


async def with_ping(
    source: AsyncIterator[SSEEvent],
    interval: float,
    ping_data: dict | None = None,
) -> AsyncIterator[SSEEvent]:
    """包装事件源：超过 interval 秒无事件产出时注入 ping 心跳，防止中间层代理断连。

    用独立 task + shield 实现，超时不会把取消传播到源生成器内部。
    """
    task = asyncio.create_task(source.__anext__())
    try:
        while True:
            try:
                item = await asyncio.wait_for(asyncio.shield(task), timeout=interval)
            except asyncio.TimeoutError:
                yield SSEEvent(EVENT_PING, ping_data or {"timestamp": int(time.time())})
                continue
            except StopAsyncIteration:
                return
            task = asyncio.create_task(source.__anext__())
            yield item
    finally:
        if not task.done():
            task.cancel()
