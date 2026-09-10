"""special（特殊作业）模块组合技能工具。

技能 = 固定行动序列的高层封装：LLM 只需选择技能，内部编排底层工具（
score_evaluate_detail / score_calculate）完成多步流程，输出提炼后的 observation。
底层工具保留，供技能覆盖不到的问题兜底（LLM 可自由选择）。

技能清单：
- special_score_overview   评分总览：evaluate_detail(module=special) → 提炼总分/三维度/通过
- special_report_function_build  报备功能建设（1.1）：calculate(special,functionBuild,1.1) → 返回现场评估
- special_ticket_function_build  作业票功能建设（1.2）：calculate(special,functionBuild,1.2) → 返回现场评估
- special_inspection_function_build  抽查功能建设（1.3）：calculate(special,functionBuild,1.3) → 返回现场评估
- special_data_quality_evaluation  数据质量（2.x）：evaluate_detail → 逐项 calculate → 返回得分/状态/原因
- special_application_effect_evaluation  应用成效（3.x）：evaluate_detail → 逐项 calculate → 返回得分/状态/原因
- special_score_drilldown  扣分分析：evaluate_detail → 筛扣分项 → 逐项 calculate → 汇总原因
- special_ticket_issue     问题票：找 3.5.x 子项 → calculate → 收集 entities 票明细
"""

from dataclasses import replace
from typing import Any, Awaitable, Callable

from app.tools.protocol import ExecContext, ToolConfig, ToolExecutor, ToolResult
from app.tools.score_format import format_special_result

# 底层工具执行器：run(tool_name, arguments, ctx) -> ToolResult
ToolRunner = Callable[[str, dict[str, Any], ExecContext], Awaitable[ToolResult]]

# 统一结果新格式：评分项编号为字符串编码（如 special-functionBuild-tszybbgnjsqkpg）
# 从编号中提取维度
_MAX_DRILLDOWN_ITEMS = 5
_MAX_TICKET_SUB_ITEMS = 3
_MAX_DIMENSION_ITEMS = 40


def dimension_of(item_no: str) -> str:
    """由评分项编号反推 dimension（供 score_calculate 入参）。

    新格式编号：special-functionBuild-tszybbgnjsqkpg
    旧格式编号：1.1, 2.3, 3.5（兼容处理）
    """
    # 新格式：module-dimension-code
    if "-" in item_no:
        parts = item_no.split("-")
        if len(parts) >= 2:
            return parts[1]  # 返回 dimension 部分

    # 旧格式兼容：1.x/2.x/3.x
    segment = item_no.split(".")[0]
    dimension_map = {
        "1": "functionBuild",
        "2": "dataQuality",
        "3": "applicationEffect",
    }
    return dimension_map.get(segment, "applicationEffect")


def _extract_dimensions(data: dict) -> list[dict]:
    """从 evaluate_detail 返回中提取维度明细。"""
    modules = data.get("modules") or []
    return modules[0].get("dimensions", []) if modules else []


def _failed_items(data: dict, dimension: str | None = None) -> list[dict]:
    """收集所有未通过的评分项（status != PASS）。

    新格式：status 字段取值 PASS, BUSINESS_ISSUE, DATA_INSUFFICIENT, CALCULATION_ERROR
    旧格式：matched=false 表示未通过（兼容）
    """
    items: list[dict] = []
    for dim in _extract_dimensions(data):
        # 兼容新旧字段名：dimensionCode 或 key
        dim_code = dim.get("dimensionCode") or dim.get("key")
        if dimension and dim_code != dimension:
            continue
        for it in dim.get("items") or []:
            # 新格式：检查 status 字段
            status = it.get("status")
            if status and status != "PASS":
                items.append(it)
            # 旧格式兼容：matched=false
            elif not it.get("matched", True):
                items.append(it)
    return items


def _park_context(ctx: ExecContext, park_id: str) -> ExecContext:
    """为逐园区调用复制上下文，避免修改当前请求的输入。"""
    return replace(ctx, inputs={**ctx.inputs, "parkId": park_id})


async def _resolve_park_contexts(
    ctx: ExecContext, run: ToolRunner
) -> tuple[list[tuple[str | None, ExecContext]], ToolResult | None]:
    """解析指定园区或 ALL 范围；ALL 通过 Java 园区列表逐园区执行。"""
    requested = str(ctx.inputs.get("parkId") or "").strip()
    if requested and requested.upper() == "ALL":
        parks = await run("score_list_parks", {}, ctx)
        if not parks.ok:
            return [], parks
        rows = parks.raw if isinstance(parks.raw, list) else []
        contexts: list[tuple[str | None, ExecContext]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            park_id = row.get("id") or row.get("parkId")
            if park_id:
                label = row.get("parkName") or row.get("name") or str(park_id)
                contexts.append((f"{label}（{park_id}）", _park_context(ctx, str(park_id))))
        if not contexts:
            return [], ToolResult(False, "Java 园区列表为空，无法执行所有园区评估", error_code="NO_PARKS")
        return contexts, None
    return [(requested or None, ctx)], None


def _park_label(data: dict, fallback: str | None) -> str:
    return str(data.get("parkName") or data.get("parkId") or fallback or "当前园区")


async def _special_overview(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """评分总览：总分/三维度得分/是否通过。"""
    contexts, error = await _resolve_park_contexts(ctx, run)
    if error:
        return error
    results: list[dict] = []
    for label, park_ctx in contexts:
        result = await run("score_evaluate_detail", {"module": "special"}, park_ctx)
        if not result.ok:
            return result
        raw = result.raw or {}
        if label and isinstance(raw, dict) and not raw.get("parkName"):
            raw = {**raw, "parkName": label}
        results.append(raw)
    if len(results) > 1:
        return ToolResult(True, "", raw={"parkCount": len(results), "parks": results})
    data = results[0] if results else {}
    # 兼容新旧格式
    score = data.get("score") or data.get("totalScore")
    max_score = data.get("maxScore") or data.get("totalMaxScore")
    passed = data.get("passed")
    lines = [
        f"特殊作业模块总分 {score}/{max_score}，"
        f"{'通过' if passed else '未通过'}"
    ]
    for dim in _extract_dimensions(data):
        # 新格式：dimensionName, dimensionCode；旧格式：displayName, key
        dim_name = dim.get("dimensionName") or dim.get("displayName")
        dim_code = dim.get("dimensionCode") or dim.get("key")
        lines.append(
            f"{dim_name}（{dim_code}）{dim.get('score')}/{dim.get('maxScore')}分"
        )
    return ToolResult(True, "\n".join(lines), raw=data)


async def _special_function_build_item(
    item_no: str, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """功能建设单项评分：每次请求都现场试算对应评分项。"""
    contexts, error = await _resolve_park_contexts(ctx, run)
    if error:
        return error
    results: list[dict] = []
    observations: list[str] = []
    for label, park_ctx in contexts:
        result = await run(
            "score_calculate",
            {"module": "special", "dimension": "functionBuild", "itemNo": item_no},
            park_ctx,
        )
        if not result.ok:
            return result
        raw = result.raw or {}
        if label and isinstance(raw, dict) and not raw.get("parkName"):
            raw = {**raw, "parkName": label}
        results.append(raw)
        if label:
            observations.append(f"{label}：{result.observation}")
    if len(results) == 1:
        return ToolResult(True, "", raw=results[0])
    return ToolResult(
        True,
        "\n".join(observations),
        raw={"itemNo": item_no, "parkCount": len(results), "parks": results},
    )


async def _special_report_function_build(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """特殊作业报备功能建设评分项 1.1。"""
    return await _special_function_build_item("1.1", ctx, run)


async def _special_ticket_function_build(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """特殊作业票管理功能建设评分项 1.2。"""
    return await _special_function_build_item("1.2", ctx, run)


async def _special_inspection_function_build(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    """特殊作业抽查功能建设评分项 1.3。"""
    return await _special_function_build_item("1.3", ctx, run)


async def _special_dimension_evaluation(
    dimension: str,
    label: str,
    ctx: ExecContext,
    run: ToolRunner,
    item_no: str | None = None,
) -> ToolResult:
    """读取 Java 维度明细并逐项现场试算，适用于 2.x/3.x。

    item_no 有值时只评估该评分项；没有值时才评估整个维度。
    """
    contexts, error = await _resolve_park_contexts(ctx, run)
    if error:
        return error
    park_results: list[dict] = []
    output: list[str] = []
    for park_label, park_ctx in contexts:
        evaluated = await run("score_evaluate_detail", {"module": "special"}, park_ctx)
        if not evaluated.ok:
            return evaluated
        data = evaluated.raw or {}
        dimensions = _extract_dimensions(data)
        # 兼容新旧字段名：dimensionCode 或 key
        target = next(
            (d for d in dimensions if d.get("dimensionCode") == dimension or d.get("key") == dimension or d.get("dimension") == dimension),
            None,
        )
        if target is None:
            return ToolResult(False, f"Java 返回中未找到{label}维度", error_code="DIMENSION_NOT_FOUND")
        item_results: list[dict] = []
        lines = [
            f"{park_label or _park_label(data, None)}：{label} "
            f"{target.get('score', '-')}/{target.get('maxScore', '-')}分"
        ]
        items = target.get("items") or []
        if item_no:
            items = [item for item in items if str(item.get("itemNo")) == str(item_no)]
            if not items:
                return ToolResult(
                    False,
                    f"Java 返回中未找到{item_no}评分项",
                    error_code="ITEM_NOT_FOUND",
                )
        for item in items[:_MAX_DIMENSION_ITEMS]:
            item_no_val = item.get("itemNo")
            if not item_no_val:
                continue
            calculated = await run(
                "score_calculate",
                {"module": "special", "dimension": dimension, "itemNo": item_no_val},
                park_ctx,
            )
            raw_calc = calculated.raw if calculated.ok and isinstance(calculated.raw, dict) else None
            if not calculated.ok or not raw_calc:
                # evaluate_detail 只能用于定位评分项，不能在单项试算失败时冒充本轮结论。
                score = f"{item.get('score', '-')}/{item.get('maxScore', '-')}"
                reason = calculated.observation or "评分项现场试算未返回结果"
                status = "UNAVAILABLE"
                state = "无法判定"
            else:
                score = f"{raw_calc.get('score', item.get('score', '-'))}/{raw_calc.get('maxScore', item.get('maxScore', '-'))}"
                # 新格式：detailText；旧格式：reason, issueDesc
                reason = raw_calc.get("detailText") or raw_calc.get("reason") or item.get("issueDesc") or "接口未返回原因"
                status = raw_calc.get("status")
                # 新格式状态映射：PASS=通过，其他=存在问题
                if status == "PASS":
                    state = "通过"
                elif status in ("BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"):
                    state = "存在问题" if status == "BUSINESS_ISSUE" else "无法判定"
                else:
                    # 旧格式兼容
                    state = "通过" if status == "NO_EXCEPTION" and not raw_calc.get("isAbnormal", False) else "存在问题"
            lines.append(f"{item_no_val} {item.get('itemName', '')}：{score}，{state}；原因：{reason}")
            item_results.append(
                {
                    "evaluation": item,
                    "calculation": raw_calc or {},
                    "calculationOk": calculated.ok,
                    "status": status,
                    "reason": reason,
                }
            )
        park_results.append(
            {
                "parkId": data.get("parkId"),
                "parkName": data.get("parkName"),
                "dimension": target,
                "items": item_results,
            }
        )
        output.extend(lines)
    raw: dict = park_results[0] if len(park_results) == 1 else {
        "dimension": dimension,
        "dimensionLabel": label,
        "parkCount": len(park_results),
        "parks": park_results,
    }
    return ToolResult(True, "\n".join(output), raw=raw)


async def _special_data_quality_evaluation(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    return await _special_dimension_evaluation(
        "dataQuality", "数据质量", ctx, run, args.get("itemNo")
    )


async def _special_application_effect_evaluation(
    args: dict, ctx: ExecContext, run: ToolRunner
) -> ToolResult:
    return await _special_dimension_evaluation(
        "applicationEffect", "应用成效", ctx, run, args.get("itemNo")
    )


async def _special_drilldown(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """扣分分析：evaluate 拿扣分项清单 → 逐项 calculate 拿原因 → 汇总。"""
    contexts, error = await _resolve_park_contexts(ctx, run)
    if error:
        return error
    details: list[str] = []
    all_items: list[dict] = []
    output_rows: list[dict] = []
    for park_label, park_ctx in contexts:
        result = await run("score_evaluate_detail", {"module": "special"}, park_ctx)
        if not result.ok:
            return result
        items = _failed_items(result.raw or {}, args.get("dimension"))
        if args.get("itemNo"):
            items = [it for it in items if it["itemNo"] == args["itemNo"]]
        all_items.extend(items)
        if park_label:
            details.append(park_label)
        for it in items[:_MAX_DRILLDOWN_ITEMS]:
            calc = await run(
                "score_calculate",
                {
                    "module": "special",
                    "dimension": dimension_of(it["itemNo"]),
                    "itemNo": it["itemNo"],
                },
                park_ctx,
            )
            calc_raw = calc.raw if calc.ok and isinstance(calc.raw, dict) else {}
            # 新格式：detailText；旧格式：reason, issueDesc
            reason = calc_raw.get("detailText") or calc_raw.get("reason") if calc.ok else None
            reason = reason or it.get("issueDesc") or "原因待查"
            details.append(f"{it['itemNo']} {it.get('itemName')}：{reason}")
            # 新格式状态映射
            status = calc_raw.get("status")
            if status == "PASS":
                state = "通过"
            elif status in ("BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"):
                state = "存在问题"
            else:
                # 旧格式兼容
                state = "通过" if status == "NO_EXCEPTION" else "存在问题"
            output_rows.append(
                {
                    "parkName": park_label,
                    "itemNo": it.get("itemNo"),
                    "itemName": it.get("itemName", ""),
                    "score": f"{calc_raw.get('score', it.get('score', '-'))}/{calc_raw.get('maxScore', it.get('maxScore', '-'))}",
                    "state": state,
                    "reason": reason,
                    "metrics": calc_raw.get("metrics") or {},
                }
            )
    if not all_items:
        return ToolResult(True, "特殊作业模块当前没有未得分（扣分）项。", raw=[])
    suffix = f"（共 {len(all_items)} 项，仅展示每个园区前 {_MAX_DRILLDOWN_ITEMS} 项）" if len(all_items) > _MAX_DRILLDOWN_ITEMS else ""
    return ToolResult(True, "特殊作业模块扣分项分析：\n" + "\n".join(details) + suffix, raw=output_rows)


async def _special_ticket_issue(args: dict, ctx: ExecContext, run: ToolRunner) -> ToolResult:
    """问题票：定位 3.5.x 应用问题子项 → 逐个 calculate → 收集问题票明细。"""
    contexts, error = await _resolve_park_contexts(ctx, run)
    if error:
        return error
    tickets: list[dict] = []
    for park_label, park_ctx in contexts:
        sub_item_nos: list[str] = []
        if args.get("itemNo"):
            sub_item_nos = [args["itemNo"]]
        else:
            ev = await run("score_evaluate_detail", {"module": "special"}, park_ctx)
            if not ev.ok:
                return ev
            # 兼容新旧格式评分项编号
            failed = _failed_items(ev.raw or {})
            sub_item_nos = [
                it["itemNo"] for it in failed
                # 新格式：special-applicationEffect-xxxxx
                # 旧格式：3.5.x
                if (it["itemNo"].startswith("3.5") or
                    ("applicationEffect" in it["itemNo"] and "3.5" in str(it.get("itemName", ""))))
            ]
        for item_no in sub_item_nos[:_MAX_TICKET_SUB_ITEMS]:
            calc = await run(
                "score_calculate",
                {"module": "special", "dimension": "applicationEffect", "itemNo": item_no},
                park_ctx,
            )
            prefix = f"{park_label} " if park_label else ""
            if not calc.ok:
                tickets.append(
                    {
                        "itemNo": item_no,
                        "ticket": "当前接口未返回具体票据明细",
                        "company": "当前接口未返回企业明细",
                        "reason": f"查询失败（{calc.observation}）",
                    }
                )
                continue
            raw = calc.raw or {}
            entities = raw.get("entities") or []
            # 新格式：detailText；旧格式：reason
            reason = raw.get("detailText") or raw.get("reason") or ""
            if entities:
                for e in entities:
                    name = e.get("entityName") or e.get("entityId") or "未知"
                    tickets.append(
                        {
                            "itemNo": item_no,
                            "ticket": f"{name}（{e.get('entityId', '')}）",
                            "company": e.get("companyName") or e.get("enterpriseName") or "接口未返回企业明细",
                            "reason": reason or "接口未返回原因",
                        }
                    )
            else:
                tickets.append(
                    {
                        "itemNo": item_no,
                        "ticket": "当前接口未返回具体票据明细",
                        "company": "当前接口未返回企业明细",
                        "reason": reason or "当前接口未返回具体票据明细",
                    }
                )

    if not tickets:
        return ToolResult(True, "特殊作业应用问题没有扣分，未发现问题作业票。", raw=[])
    observation = "特殊作业应用问题涉及的问题作业票：\n" + "\n".join(
        f"[{row['itemNo']}] {row['ticket']}：{row['reason']}" for row in tickets
    )
    return ToolResult(True, observation, raw=tickets)


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
