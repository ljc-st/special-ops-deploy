"""special（特殊作业）模块组合技能工具。

技能 = 固定行动序列的高层封装：LLM 只需选择技能，内部编排底层工具
（score_evaluate_detail / score_calculate）完成多步流程，输出提炼后的 observation。

对齐《系统评分接口规范》统一结果模型：
- 评分项编号为正式字符串编码（itemNo），不再使用数字编号；
- 评分项状态为 PASS / BUSINESS_ISSUE / DATA_INSUFFICIENT / CALCULATION_ERROR；
- 评分项详情为 detailText，实体为 entities（entityType/entityId/entityName）；
- 服务端固定使用 TARGET_PARK_ID，请求体不支持 parkId。
"""

from typing import Any, Awaitable, Callable

from app.tools.protocol import ExecContext, ToolConfig, ToolExecutor, ToolResult
from app.data_query import DataQueryService, DisabledDataQueryService
from app.tools.score_format import format_special_result

# 底层工具执行器：run(tool_name, arguments, ctx) -> ToolResult
ToolRunner = Callable[[str, dict[str, Any], ExecContext], Awaitable[ToolResult]]

_PASS = "PASS"

_MAX_DRILLDOWN_ITEMS = 5
_MAX_DIMENSION_ITEMS = 40


def _extract_dimensions(data: dict) -> list[dict]:
    """从统一结果树提取维度，并兼容迁移期旧字段。"""
    modules = data.get("modules") or []
    dimensions = modules[0].get("dimensions", []) if modules else []
    normalized: list[dict] = []
    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        item = dict(dim)
        item.setdefault("dimensionCode", item.get("key"))
        item.setdefault("dimensionName", item.get("displayName"))
        normalized_items = []
        for raw in item.get("items") or []:
            if not isinstance(raw, dict):
                continue
            value = dict(raw)
            if "status" not in value:
                value["status"] = "PASS" if value.get("matched") is True else ("BUSINESS_ISSUE" if value.get("matched") is False else None)
            value.setdefault("detailText", value.get("issueDesc") or value.get("reason"))
            normalized_items.append(value)
        item["items"] = normalized_items
        normalized.append(item)
    return normalized


def _iter_items(data: dict) -> list[tuple[str, dict]]:
    """返回 (dimensionCode, item) 列表，按维度顺序遍历。"""
    out: list[tuple[str, dict]] = []
    for dim in _extract_dimensions(data):
        code = dim.get("dimensionCode") or ""
        for it in dim.get("items") or []:
            if isinstance(it, dict):
                out.append((code, it))
    return out


def _items_of(data: dict, dimension_code: str) -> list[dict]:
    return [it for code, it in _iter_items(data) if code == dimension_code]


def _find_item_by_keyword(data: dict, dimension_code: str, keyword: str) -> dict | None:
    """在指定维度中按名称关键词定位评分项。"""
    for it in _items_of(data, dimension_code):
        if keyword in str(it.get("itemName") or ""):
            return it
    return None


def _calc_item(result: ToolResult) -> dict:
    """Normalize calculate's batch array to the first requested ItemResult."""
    raw = result.raw
    if isinstance(raw, list):
        return raw[0] if raw and isinstance(raw[0], dict) else {}
    if not isinstance(raw, dict):
        return {}
    # Java calculate 接口通常返回 {"data": [{...}]}，不能把包装对象
    # 当成评分项本身，否则 score/maxScore 会全部丢失。
    for key in ("data", "items", "results"):
        value = raw.get(key)
        if isinstance(value, list):
            return value[0] if value and isinstance(value[0], dict) else {}
        if isinstance(value, dict):
            return value
    return raw


def _field_or(item: dict, key: str, fallback: object = "-") -> object:
    """读取字段时保留合法的 0，只有 None/空字符串才使用回退值。"""
    value = item.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback
    return value


def _failed_items(data: dict, dimension_code: str | None = None) -> list[tuple[str, dict]]:
    """收集所有 status != PASS 的评分项（可限定维度）。"""
    out: list[tuple[str, dict]] = []
    for code, it in _iter_items(data):
        if dimension_code and code != dimension_code:
            continue
        if it.get("status") not in (None, _PASS):
            out.append((code, it))
    return out


async def _evaluate_detail(ctx: ExecContext, run: ToolRunner) -> ToolResult:
    return await run("score_evaluate_detail", {"module": "special"}, ctx)


async def _special_overview(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """评分总览：总分/三维度得分。"""
    result = await _evaluate_detail(ctx, run)
    if not result.ok:
        return result
    data = result.raw if isinstance(result.raw, dict) else {}
    score = data.get("score", data.get("totalScore"))
    max_score = data.get("maxScore", data.get("totalMaxScore"))
    lines = [f"特殊作业模块总分 {score}/{max_score}"]
    for dim in _extract_dimensions(data):
        lines.append(
            f"{dim.get('dimensionName')}（{dim.get('dimensionCode')}）"
            f"{dim.get('score')}/{dim.get('maxScore')}分"
        )
    return ToolResult(True, "\n".join(lines), raw=data)


async def _special_function_build_item(
    keyword: str, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """功能建设单项评分：先定位评分项，再现场试算。"""
    evaluated = await _evaluate_detail(ctx, run)
    if not evaluated.ok:
        return evaluated
    data = evaluated.raw if isinstance(evaluated.raw, dict) else {}
    item = _find_item_by_keyword(data, "functionBuild", keyword)
    if item is None:
        return ToolResult(
            False,
            f"功能建设维度中未找到包含「{keyword}」的评分项",
            error_code="ITEM_NOT_FOUND",
        )
    item_no = item.get("itemNo")
    if not item_no:
        return ToolResult(False, "评分项缺少 itemNo 编码", error_code="ITEM_NOT_FOUND")
    calc = await run(
        "score_calculate",
        {"module": "special", "dimension": "functionBuild", "itemNo": item_no},
        ctx,
    )
    return calc


async def _special_report_function_build(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """特殊作业报备功能建设评分项。"""
    return await _special_function_build_item("报备", ctx, run)


async def _special_ticket_function_build(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """特殊作业票管理功能建设评分项。"""
    return await _special_function_build_item("作业票", ctx, run)


async def _special_inspection_function_build(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """特殊作业抽查功能建设评分项。"""
    return await _special_function_build_item("抽查", ctx, run)


async def _special_dimension_evaluation(
    dimension_code: str,
    label: str,
    ctx: ExecContext,
    run: ToolRunner,
    item_no: str | None = None,
) -> ToolResult:
    """读取 Java 维度明细并逐项现场试算，适用于数据质量/应用成效。

    item_no 有值时只评估该评分项；没有值时才评估整个维度。
    """
    evaluated = await _evaluate_detail(ctx, run)
    if not evaluated.ok:
        return evaluated
    data = evaluated.raw if isinstance(evaluated.raw, dict) else {}
    dim = next(
        (d for d in _extract_dimensions(data) if d.get("dimensionCode") == dimension_code),
        None,
    )
    if dim is None:
        return ToolResult(False, f"Java 返回中未找到{label}维度", error_code="DIMENSION_NOT_FOUND")

    items = dim.get("items") or []
    if item_no:
        items = [it for it in items if str(it.get("itemNo")) == str(item_no)]
        if not items:
            return ToolResult(
                False, f"Java 返回中未找到 {item_no} 评分项", error_code="ITEM_NOT_FOUND"
            )

    rows: list[dict] = []
    for it in items[:_MAX_DIMENSION_ITEMS]:
        no = it.get("itemNo")
        if not no:
            continue
        calculated = await run(
            "score_calculate",
            {"module": "special", "dimension": dimension_code, "itemNo": no},
            ctx,
        )
        raw_calc = _calc_item(calculated) if calculated.ok else {}
        detail = raw_calc.get("detailText") or it.get("detailText") or "接口未返回原因"
        status = _field_or(raw_calc, "status", _field_or(it, "status", None))
        rows.append(
            {
                "itemNo": no,
                "itemName": it.get("itemName", ""),
                "score": _field_or(raw_calc, "score", _field_or(it, "score")),
                "maxScore": _field_or(raw_calc, "maxScore", _field_or(it, "maxScore")),
                "status": status,
                "detailText": detail,
                "entities": raw_calc.get("entities") or [],
                "calculationOk": calculated.ok,
            }
        )

    lines = [f"{label} {dim.get('score', '-')}/{dim.get('maxScore', '-')}分"]
    for row in rows:
        lines.append(
            f"{row['itemNo']} {row['itemName']}：{row['score']}，{row['status']}；原因：{row['detailText']}"
        )
    raw_out = {
        "dimensionCode": dimension_code,
        "dimensionName": label,
        "dimension": dim,
        "items": rows,
    }
    return ToolResult(True, "\n".join(lines), raw=raw_out)


async def _special_data_quality_evaluation(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    return await _special_dimension_evaluation(
        "dataQuality", "特殊作业数据质量板块", ctx, run, args.get("itemNo")
    )


async def _special_application_effect_evaluation(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    return await _special_dimension_evaluation(
        "applicationEffect", "特殊作业应用成效板块", ctx, run, args.get("itemNo")
    )


async def _special_drilldown(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """扣分分析：evaluate_detail 拿扣分项清单 → 逐项 calculate 拿原因 → 汇总。"""
    result = await _evaluate_detail(ctx, run)
    if not result.ok:
        return result
    data = result.raw if isinstance(result.raw, dict) else {}
    failed = _failed_items(data, args.get("dimension"))
    if args.get("itemNo"):
        failed = [(c, it) for c, it in failed if str(it.get("itemNo")) == str(args["itemNo"])]
    if not failed:
        return ToolResult(True, "特殊作业模块当前没有扣分项。", raw=[])

    rows: list[dict] = []
    for dimension_code, it in failed[:_MAX_DRILLDOWN_ITEMS]:
        no = it.get("itemNo")
        calc = await run(
            "score_calculate",
            {"module": "special", "dimension": dimension_code, "itemNo": no},
            ctx,
        )
        raw_calc = _calc_item(calc) if calc.ok else {}
        detail = raw_calc.get("detailText") or it.get("detailText") or "原因待查"
        rows.append(
            {
                "itemNo": no,
                "itemName": it.get("itemName", ""),
                "score": _field_or(raw_calc, "score", _field_or(it, "score")),
                "maxScore": _field_or(raw_calc, "maxScore", _field_or(it, "maxScore")),
                "status": _field_or(raw_calc, "status", _field_or(it, "status", None)),
                "detailText": detail,
                "entities": raw_calc.get("entities") or [],
            }
        )

    suffix = (
        f"（共 {len(failed)} 项，仅展示前 {_MAX_DRILLDOWN_ITEMS} 项）"
        if len(failed) > _MAX_DRILLDOWN_ITEMS
        else ""
    )
    lines = ["特殊作业模块扣分项分析："]
    for row in rows:
        lines.append(
            f"{row['itemNo']} {row['itemName']}：{row['score']}，{row['status']}；原因：{row['detailText']}"
        )
    return ToolResult(True, "\n".join(lines) + suffix, raw=rows)


async def _special_ticket_issue(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """问题票：定位应用成效下带实体的扣分项 → 逐个 calculate → 收集问题票明细。"""
    result = await _evaluate_detail(ctx, run)
    if not result.ok:
        return result
    data = result.raw if isinstance(result.raw, dict) else {}

    target: list[tuple[str, dict]] = []
    if args.get("itemNo"):
        for code, it in _iter_items(data):
            if str(it.get("itemNo")) == str(args["itemNo"]):
                target.append((code, it))
    else:
        target = [
            (c, it)
            for c, it in _failed_items(data, "applicationEffect")
            if it.get("status") == "BUSINESS_ISSUE"
        ]

    tickets: list[dict] = []
    for dimension_code, it in target:
        no = it.get("itemNo")
        calc = await run(
            "score_calculate",
            {"module": "special", "dimension": dimension_code, "itemNo": no},
            ctx,
        )
        raw = _calc_item(calc) if calc.ok else {}
        detail = raw.get("detailText") or it.get("detailText") or ""
        entities = raw.get("entities") or it.get("entities") or []
        if entities:
            for e in entities:
                if not isinstance(e, dict):
                    continue
                name = e.get("entityName") or e.get("entityId") or "未知"
                tickets.append(
                    {
                        "itemNo": no,
                        "ticket": f"{name}（{e.get('entityId', '')}）",
                        "company": e.get("entityName") or "接口未返回企业明细",
                        "reason": detail or "接口未返回原因",
                    }
                )
        else:
            tickets.append(
                {
                    "itemNo": no,
                    "ticket": "当前接口未返回具体票据明细",
                    "company": "当前接口未返回企业明细",
                    "reason": detail or "当前接口未返回具体票据明细",
                }
            )

    if not tickets:
        return ToolResult(True, "特殊作业应用问题没有扣分，未发现问题作业票。", raw=[])
    observation = "特殊作业应用问题涉及的问题作业票：\n" + "\n".join(
        f"[{row['itemNo']}] {row['ticket']}：{row['reason']}" for row in tickets
    )
    return ToolResult(True, observation, raw=tickets)


async def _special_item_search(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """按评分项名称/关键词定位正式字符串 itemNo，不猜测编码。"""
    keyword = str(args.get("keyword") or "").strip()
    if not keyword:
        return ToolResult(False, "请提供评分项名称或业务关键词", error_code="INVALID_ARGUMENT")
    result = await _evaluate_detail(ctx, run)
    if not result.ok:
        return result
    data = result.raw if isinstance(result.raw, dict) else {}
    dimension = args.get("dimension")
    matches = [(code, it) for code, it in _iter_items(data) if (not dimension or code == dimension) and keyword in str(it.get("itemName") or "")]
    if not matches:
        return ToolResult(True, f"未找到名称包含「{keyword}」的特殊作业评分项。", raw=[])
    rows = [{"dimension": code, **it} for code, it in matches]
    return ToolResult(True, "找到以下评分项：\n" + "\n".join(f"{r.get('itemNo')} {r.get('itemName')}" for r in rows), raw=rows)


async def _special_item_detail(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """严格单项查询：itemNo 直接查询，关键词必须唯一匹配。"""
    item_no = str(args.get("itemNo") or "").strip()
    if not item_no:
        keyword = str(args.get("keyword") or "").strip()
        if not keyword:
            return ToolResult(False, "请提供评分项正式编码或评分项名称/关键词", error_code="INVALID_ARGUMENT")
        found = await _special_item_search({"keyword": keyword, "dimension": args.get("dimension")}, ctx, run)
        rows = found.raw if found.ok and isinstance(found.raw, list) else []
        if len(rows) != 1:
            return ToolResult(True, "评分项无法唯一确定，请提供更具体的评分项名称或正式 itemNo。", raw=rows)
        item_no = rows[0].get("itemNo", "")
        dimension = rows[0].get("dimension") or args.get("dimension")
    else:
        dimension = args.get("dimension") or item_no.split("-")[1] if item_no.count("-") >= 2 else args.get("dimension", "")
    if not dimension:
        return ToolResult(False, "无法确定评分项所属维度", error_code="INVALID_ARGUMENT")
    return await run("score_calculate", {"module": "special", "dimension": dimension, "itemNo": item_no}, ctx)


async def _special_status_diagnosis(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    result = await _evaluate_detail(ctx, run)
    if not result.ok:
        return result
    data = result.raw if isinstance(result.raw, dict) else {}
    counts = {"PASS": 0, "BUSINESS_ISSUE": 0, "DATA_INSUFFICIENT": 0, "CALCULATION_ERROR": 0}
    for _, item in _iter_items(data):
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    labels = {"PASS": "通过", "BUSINESS_ISSUE": "存在业务问题", "DATA_INSUFFICIENT": "数据不足", "CALCULATION_ERROR": "计算异常"}
    rows = [{"status": key, "label": labels[key], "count": count} for key, count in counts.items() if count]
    return ToolResult(True, "特殊作业评分状态统计：\n" + "\n".join(f"{r['label']}：{r['count']} 项" for r in rows), raw=rows)


async def _special_data_query(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    service: DataQueryService = getattr(ctx, "data_query_service", None) or DisabledDataQueryService()
    result = await service.ask(str(args.get("question") or ""), str(args.get("tableHint") or ""))
    return ToolResult(result.ok, result.observation, raw={"columns": result.columns, "rows": result.rows}, error_code=result.error_code)


# 技能名 → 实现（ToolConfig.skill_name 或 name 命中）
SKILLS: dict[str, Callable[..., Awaitable[ToolResult]]] = {
    "special_score_overview": _special_overview,
    "special_report_function_build": _special_report_function_build,
    "special_ticket_function_build": _special_ticket_function_build,
    "special_inspection_function_build": _special_inspection_function_build,
    "special_data_quality_evaluation": _special_data_quality_evaluation,
    "special_application_effect_evaluation": _special_application_effect_evaluation,
    "special_score_drilldown": _special_drilldown,
    "special_ticket_issue": _special_ticket_issue,
    "special_item_search": _special_item_search,
    "special_item_detail": _special_item_detail,
    "special_status_diagnosis": _special_status_diagnosis,
    "special_data_query": _special_data_query,
}


class SkillExecutor(ToolExecutor):
    """技能执行器：把组合技能工具分发给对应实现，内部通过注入的底层工具 runner 编排多步流程。"""

    def __init__(self, run: ToolRunner):
        self._run = run

    async def execute(
        self, call, config: ToolConfig | None, ctx: ExecContext
    ) -> ToolResult:
        skill_name = (config.skill_name if config is not None else None) or call.name
        handler = SKILLS.get(skill_name)
        if handler is None:
            return ToolResult(
                False,
                f"技能 [{skill_name}] 未注册",
                error_code="TOOL_NOT_FOUND",
            )
        result = await handler(call.arguments, ctx, self._run)
        return format_special_result(skill_name, result)
