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
    """按用户关心的业务场景生成可展示的三步核查说明。"""
    if any(word in query for word in ("数据库", "历史", "批次", "入库记录", "历史记录", "企业信息")):
        return (
            "第一步：我先确认你想查看的是企业信息、历史评分、评估批次，还是作业票历史记录，并明确查询范围。\n"
            "第二步：我会读取当前已有记录，核对企业、时间、评分结果和关联信息；没有查到的内容会如实说明。\n"
            "第三步：我会按你最关心的内容整理结果，让你能快速看清查到了什么、涉及哪些企业或作业票，以及是否还缺少数据。"
        )
    if any(word in query for word in ("哪张票", "哪张作业票", "问题作业票", "不通过作业票", "票号", "作业票明细")):
        return (
            "第一步：我先确认你要找的是存在问题的具体作业票，以及每张作业票对应的问题原因。\n"
            "第二步：我会核对本次评估中被判定为有问题的作业票，并查看票号、所属企业和具体问题。\n"
            "第三步：我会逐张整理清楚，让你能直接知道需要核查哪张票、联系哪家企业，以及问题出在哪里。"
        )
    if any(word in query for word in ("扣分", "为什么", "原因", "没得分", "未得分")):
        return (
            "第一步：我先确认你关注的是哪些项目被扣分，还是某一个项目为什么没有得分。\n"
            "第二步：我会查看本次最新评估结果，逐项核对得分、状态、判定依据和涉及的企业或作业票。\n"
            "第三步：我会先说清主要问题，再说明扣分依据和处理建议；数据不足与实际业务问题会分开说明，避免造成误解。"
        )
    if any(word in query for word in ("数据质量", "完整性", "接入率", "重复率", "一致性")):
        return (
            "第一步：我先确认你要了解的是特殊作业数据质量，重点关注数据是否存在、是否完整、是否重复，以及不同数据之间是否一致。\n"
            "第二步：我会读取本次最新评估结果，逐项核对特殊作业报备数据、特殊作业票数据和特殊作业抽查数据的得分与判定原因。\n"
            "第三步：我会把通过项、问题项和数据不足项分别说明，让你能快速判断问题集中在哪类数据、接下来应优先补齐什么。"
        )
    if any(word in query for word in ("应用成效", "应用效果", "活跃度", "覆盖率", "实际使用", "关联作业")):
        return (
            "第一步：我先确认你要查看的是特殊作业功能是否真正用起来，重点关注使用频率、企业覆盖和业务闭环情况。\n"
            "第二步：我会读取本次最新评估结果，核对特殊作业报备、作业票管理和作业抽查的使用情况、得分及扣分原因。\n"
            "第三步：我会说明哪些功能使用正常、哪些使用不足，以及问题涉及哪些企业或作业票，方便你安排后续整改。"
        )
    if any(word in query for word in ("功能建设", "建设情况", "功能是否建设")):
        named_function = next(
            (
                name
                for keyword, name in (
                    ("作业票", "特殊作业票管理功能建设情况"),
                    ("报备", "特殊作业报备功能建设情况"),
                    ("抽查", "特殊作业抽查功能建设情况"),
                )
                if keyword in query
            ),
            "",
        )
        if named_function:
            return (
                f"第一步：我先确认你要查看的是{named_function}，本次只核查这一项，不混入其他功能的评分。\n"
                "第二步：我会读取该项本次最新评估结果，核对近期是否已有可用于评估的业务数据，以及对应的得分、状态和判定原因。\n"
                "第三步：我会直接说明该项是否满足要求；如果存在问题或数据不足，也会告诉你问题在哪里、接下来应补充什么。"
            )
        return (
            "第一步：我先确认你要查看的是特殊作业功能建设情况，并区分报备、作业票管理和作业抽查三类功能。\n"
            "第二步：我会读取本次最新评估结果，逐项核对是否已有可用于评估的业务数据，以及对应的得分、状态和原因。\n"
            "第三步：我会先展示各项结果，再用简短总结告诉你哪些功能已满足要求、哪些需要补充数据或继续完善。"
        )
    if any(word in query for word in ("评分项", "单项", "这一项", "该项")):
        return (
            "第一步：我先确认你点名的具体评估项目，避免把单项结果和整个模块的结果混在一起。\n"
            "第二步：我会读取该项目本次最新的得分、状态和判定依据，并核对是否涉及企业或作业票。\n"
            "第三步：我只围绕这一项说明结果，用简单的话解释为什么这样评估，以及下一步可以怎样处理。"
        )
    return (
        "第一步：我先确认你要了解的是特殊作业整体评分，并从功能建设、数据质量和应用成效三个方面进行查看。\n"
        "第二步：我会读取本次最新评估结果，核对总分、各模块得分、评估状态和主要原因；数据不足的项目会单独说明。\n"
        "第三步：我会按照“总体结果、主要问题、处理建议”的顺序整理，让你能快速看懂当前情况和下一步重点。"
    )
