"""Stable user-facing summaries for scoring skill results."""

import re

from app.tools.protocol import ToolResult


def _format_percent(value: object) -> str:
    """格式化 Java 返回的比例；不对缺失值做推断。"""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number * 100:.0f}%" if abs(number) <= 1 else f"{number:.0f}%"


def _format_item_metrics(metrics: object) -> str:
    """将评分接口指标转换为用户可读事实，不暴露内部字段名。"""
    if not isinstance(metrics, dict):
        return ""
    parts: list[str] = []
    if metrics.get("recordCount") is not None:
        parts.append(f"记录数：{metrics['recordCount']}条")
    if metrics.get("lookbackMonths") is not None:
        parts.append(f"统计周期：近{metrics['lookbackMonths']}个月")
    if metrics.get("usageStatus"):
        parts.append(f"使用状态：{metrics['usageStatus']}")
    if metrics.get("evaluationRule"):
        parts.append(f"判定规则：{metrics['evaluationRule']}")
    if metrics.get("reportRecordCount") is not None:
        report = f"报备共{metrics['reportRecordCount']}条"
        if metrics.get("reportDuplicateCount") is not None:
            report += f"，重复{metrics['reportDuplicateCount']}条"
        if metrics.get("reportDistinctCount") is not None:
            report += f"，去重后{metrics['reportDistinctCount']}条"
        if metrics.get("reportDuplicateRate") is not None:
            report += f"，重复率{_format_percent(metrics['reportDuplicateRate'])}"
        parts.append(report)
    if metrics.get("ticketRecordCount") is not None:
        ticket = f"作业票共{metrics['ticketRecordCount']}条"
        if metrics.get("ticketDuplicateCount") is not None:
            ticket += f"，重复{metrics['ticketDuplicateCount']}条"
        if metrics.get("ticketDistinctCount") is not None:
            ticket += f"，去重后{metrics['ticketDistinctCount']}条"
        if metrics.get("ticketDuplicateRate") is not None:
            ticket += f"，重复率{_format_percent(metrics['ticketDuplicateRate'])}"
        parts.append(ticket)
    if metrics.get("coveredCompanyCount") is not None or metrics.get("targetCompanyCount") is not None:
        covered = metrics.get("coveredCompanyCount", "-")
        target = metrics.get("targetCompanyCount", "-")
        coverage = metrics.get("coverageRate")
        text = f"覆盖企业{covered}/{target}"
        if coverage is not None:
            text += f"，覆盖率{_format_percent(coverage)}"
        parts.append(text)
    if metrics.get("missingRate") is not None or metrics.get("missingCount") is not None:
        text = "字段缺失"
        if metrics.get("missingCount") is not None:
            text += f"{metrics['missingCount']}条"
        if metrics.get("completeCount") is not None:
            text += f"，完整{metrics['completeCount']}条"
        if metrics.get("missingRate") is not None:
            text += f"，缺失率{_format_percent(metrics['missingRate'])}"
        parts.append(text)
    if metrics.get("highRiskFireVideoCount") is not None:
        parts.append(
            f"高风险动火视频{metrics.get('highRiskFireVideoFilledCount', 0)}"
            f"/{metrics['highRiskFireVideoCount']}"
        )
    if metrics.get("ticketGeoFilledCount") is not None or metrics.get("ticketGeoMissingCount") is not None:
        parts.append(
            f"作业票经纬度完整{metrics.get('ticketGeoFilledCount', 0)}"
            f"/{metrics.get('ticketCount', '-') }"
        )
    if metrics.get("threshold") is not None:
        threshold = metrics["threshold"]
        if isinstance(threshold, (int, float)):
            threshold = _format_percent(threshold)
        parts.append(f"判定阈值：{threshold}")
    if "evidenceEnabled" in metrics:
        parts.append(
            "建设证据/企业台账校验："
            + ("已启用" if metrics["evidenceEnabled"] else "未启用")
        )
    return "；".join(parts)


def _clean_reason(value: object) -> str:
    """清理接口原因中的评价时间描述，保留其余判定事实。"""
    text = "" if value is None else str(value)
    if not text:
        return ""
    # 评价时间由前端统一展示，本轮评分原因只保留数量、比例、阈值和结论。
    text = re.sub(
        r"(?:评价时间窗|评价窗口|评价时间)\s*(?:为|是|：|:)?\s*[^，。；;\n]*(?:[，。；;]|$)",
        "",
        text,
    )
    text = re.sub(r"^[，。；;、\s]+|[，。；;、\s]+$", "", text)
    text = re.sub(r"[，。；;]{2,}", "；", text)
    return text.strip()


def _table_cell(value: object) -> str:
    """防止接口原因中的换行或竖线破坏 Markdown 表格。"""
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _dimension_parks(raw: object) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    if isinstance(raw.get("parks"), list):
        return [park for park in raw["parks"] if isinstance(park, dict)]
    return [raw]


def _dimension_item_row(item_result: dict) -> dict:
    evaluation = item_result.get("evaluation") or {}
    calculation = item_result.get("calculation") or {}
    score = (
        f"{calculation.get('score', evaluation.get('score', '-'))}/"
        f"{calculation.get('maxScore', evaluation.get('maxScore', '-'))}"
    )
    status = item_result.get("status") or calculation.get("status")

    # 新格式状态映射
    if not item_result.get("calculationOk", True):
        state = "无法判定"
    elif status == "PASS":
        state = "通过"
    elif status in ("BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"):
        state = "存在问题" if status == "BUSINESS_ISSUE" else "无法判定"
    else:
        # 旧格式兼容
        state = "通过" if status == "NO_EXCEPTION" and not calculation.get("isAbnormal", False) else "存在问题"

    # 新格式：detailText；旧格式：reason, issueDesc
    reason = _clean_reason(
        item_result.get("reason")
        or calculation.get("detailText")
        or calculation.get("reason")
        or evaluation.get("issueDesc")
        or "接口未返回原因"
    )
    entities = calculation.get("entities") or []
    if entities:
        names = [
            str(entity.get("entityName") or entity.get("entityId") or "未知")
            for entity in entities
            if isinstance(entity, dict)
        ]
        if names:
            reason = f"{reason}；涉及实体：{'、'.join(names)}"
    metrics = _format_item_metrics(calculation.get("metrics"))
    if metrics:
        reason = f"{reason}；关键事实：{metrics}"
    return {
        "itemNo": evaluation.get("itemNo") or calculation.get("itemNo") or "-",
        "itemName": evaluation.get("itemName") or calculation.get("itemName") or "",
        "score": score,
        "state": state,
        "reason": reason,
    }


def _render_dimension(raw: object, label: str) -> str:
    """按评分项数量渲染维度；达到 3 项时使用表格。"""
    sections: list[str] = []
    for park in _dimension_parks(raw):
        dimension = park.get("dimension") if isinstance(park.get("dimension"), dict) else {}
        # 兼容新旧格式
        park_name = park.get("parkName") or dimension.get("parkName") or park.get("parkId") or "当前园区"
        score = f"{dimension.get('score', '-')}/{dimension.get('maxScore', '-')}分"
        rows = [
            _dimension_item_row(item)
            for item in (park.get("items") or [])
            if isinstance(item, dict)
        ]
        lines = [f"{park_name}：{label} {score}"]
        if len(rows) >= 3:
            lines.extend([
                "",
                "| 评分项 | 项目名称 | 得分 | 状态 | 原因 |",
                "|---|---|---:|---|---|",
            ])
            lines.extend(
                f"| {_table_cell(row['itemNo'])} | {_table_cell(row['itemName'])} | "
                f"{_table_cell(row['score'])} | {_table_cell(row['state'])} | {_table_cell(row['reason'])} |"
                for row in rows
            )
        else:
            lines.extend(
                f"- {row['itemNo']} {row['itemName']}：{row['score']}，{row['state']}；原因：{row['reason']}"
                for row in rows
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _render_drilldown(raw: object, fallback: str) -> str:
    rows = [row for row in (raw if isinstance(raw, list) else []) if isinstance(row, dict)]
    if not rows:
        return fallback
    display_rows: list[dict] = []
    for row in rows:
        display = dict(row)
        metrics = _format_item_metrics(row.get("metrics"))
        if metrics:
            display["reason"] = f"{_clean_reason(row.get('reason', '原因待查'))}；关键事实：{metrics}"
        else:
            display["reason"] = _clean_reason(display.get("reason"))
        display_rows.append(display)
    if len(rows) >= 3:
        lines = [
            "特殊作业模块扣分项分析：",
            "",
            "| 评分项 | 项目名称 | 得分 | 状态 | 原因 |",
            "|---|---|---:|---|---|",
        ]
        lines.extend(
            f"| {_table_cell(row.get('itemNo'))} | {_table_cell(row.get('itemName'))} | "
            f"{_table_cell(row.get('score'))} | {_table_cell(row.get('state'))} | "
            f"{_table_cell(row.get('reason'))} |"
            for row in display_rows
        )
        return "\n".join(lines)
    return "特殊作业模块扣分项分析：\n" + "\n".join(
        f"- {row.get('itemNo', '-')} {row.get('itemName', '')}：{row.get('score', '-')}，"
        f"{row.get('state', '存在问题')}；原因：{_clean_reason(row.get('reason', '原因待查'))}"
        for row in display_rows
    )


def _render_ticket_issues(raw: object, fallback: str) -> str:
    rows = [row for row in (raw if isinstance(raw, list) else []) if isinstance(row, dict)]
    if not rows:
        return fallback
    if len(rows) >= 2:
        lines = [
            "特殊作业应用问题涉及的问题作业票：",
            "",
            "| 评分项 | 票号/票据 | 企业 | 问题原因 |",
            "|---|---|---|---|",
        ]
        lines.extend(
            f"| {_table_cell(row.get('itemNo'))} | {_table_cell(row.get('ticket'))} | "
            f"{_table_cell(row.get('company'))} | {_table_cell(_clean_reason(row.get('reason')))} |"
            for row in rows
        )
        return "\n".join(lines)
    row = rows[0]
    return (
        "特殊作业应用问题涉及的问题作业票：\n"
        f"- 评分项：{row.get('itemNo', '-')}\n"
        f"  问题票据：{row.get('ticket') or '当前接口未返回具体票据明细'}\n"
        f"  企业：{row.get('company') or '当前接口未返回企业明细'}\n"
        f"  原因：{_clean_reason(row.get('reason')) or '接口未返回原因'}"
    )


def format_special_result(skill_name: str, result: ToolResult) -> ToolResult:
    """Normalize special skill text without changing its machine-readable raw data."""
    if not result.ok:
        return result

    if skill_name == "special_score_overview":
        data = result.raw or {}
        if data.get("parks"):
            lines = [
                "【特殊作业评分概览】",
                f"所有园区实时评估，共 {data.get('parkCount', len(data['parks']))} 个园区：",
                "",
                "| 园区 | 得分 | 结论 |",
                "|---|---:|---|",
            ]
            for park in data.get("parks") or []:
                park_name = park.get("parkName") or park.get("parkId") or "未知园区"
                status = "通过" if park.get("passed") else "未通过"
                # 兼容新旧字段名
                total_score = park.get("totalScore") or park.get("score")
                total_max_score = park.get("totalMaxScore") or park.get("maxScore")
                lines.append(
                    f"| {_table_cell(park_name)} | {total_score or '-'}/"
                    f"{total_max_score or '-'} | {status} |"
                )
            answer = "\n".join(lines)
        elif not data or not data.get("modules"):
            answer = "【特殊作业评分】\n暂未找到可用的评分数据。"
        else:
            status = "通过" if data.get("passed") else "未通过"
            # 兼容新旧字段名
            total_score = data.get("totalScore") or data.get("score")
            total_max_score = data.get("totalMaxScore") or data.get("maxScore")
            lines = [
                "【特殊作业评分概览】",
                f"总分：{total_score or '-'}/{total_max_score or '-'}",
                f"结论：{status}",
            ]
            modules = data.get("modules") or []
            for dimension in modules[0].get("dimensions") or []:
                # 新格式：dimensionName；旧格式：displayName, key
                label = dimension.get("dimensionName") or dimension.get("displayName") or dimension.get("key") or "-"
                lines.append(
                    f"维度：{label} {dimension.get('score', '-')}/{dimension.get('maxScore', '-')}"
                )
            answer = "\n".join(lines)
        return ToolResult(result.ok, answer, raw=result.raw, error_code=result.error_code)

    if skill_name in {
        "special_report_function_build",
        "special_ticket_function_build",
        "special_inspection_function_build",
    }:
        item_no = (result.raw or {}).get("itemNo") or {
            "special_report_function_build": "1.1",
            "special_ticket_function_build": "1.2",
            "special_inspection_function_build": "1.3",
        }[skill_name]
        item_name = (result.raw or {}).get("itemName") or ""
        raw = result.raw or {}
        if raw.get("parks"):
            lines = [
                f"【特殊作业单项评估】\n{item_no} 所有园区实时评估，共 "
                f"{raw.get('parkCount', len(raw['parks']))} 个园区："
            ]
            for park in raw.get("parks") or []:
                park_name = park.get("parkName") or park.get("parkId") or "未知园区"
                status = park.get("status")
                # 新格式状态映射
                if status == "PASS":
                    state = "通过"
                elif status in ("BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"):
                    state = "未通过" if status == "BUSINESS_ISSUE" else "无法判定"
                else:
                    # 旧格式兼容
                    state = "通过" if status == "NO_EXCEPTION" and not park.get("isAbnormal") else "未通过"
                # 新格式：detailText；旧格式：reason
                reason = _clean_reason(park.get("detailText") or park.get("reason")) or "接口未返回原因"
                metrics = _format_item_metrics(park.get("metrics"))
                if metrics:
                    reason = f"{reason}；关键事实：{metrics}"
                lines.append(f"- {park_name}：{state}；原因：{reason}")
            return ToolResult(result.ok, "\n".join(lines), raw=result.raw, error_code=result.error_code)
        status = raw.get("status")
        if status == "DATA_INSUFFICIENT" or status == "NO_DATA":
            body = "暂未找到可用的评分数据。"
        else:
            # 新格式状态映射
            if status == "PASS":
                state = "通过"
            elif status in ("BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"):
                state = "未通过" if status == "BUSINESS_ISSUE" else "无法判定"
            else:
                # 旧格式兼容
                state = "通过" if status == "NO_EXCEPTION" and not raw.get("isAbnormal") else "未通过"
            body = f"{item_no} {item_name}：{state}。"
            # 新格式：detailText；旧格式：reason
            reason = _clean_reason(raw.get("detailText") or raw.get("reason"))
            if reason:
                body += f"\n原因：{reason}"
            metrics = _format_item_metrics(raw.get("metrics"))
            if metrics:
                body += f"\n关键事实：{metrics}"
        return ToolResult(
            result.ok,
            f"【特殊作业单项评估】\n{body}",
            raw=result.raw,
            error_code=result.error_code,
        )

    if skill_name in {
        "special_data_quality_evaluation",
        "special_application_effect_evaluation",
    }:
        title = "数据质量评估" if skill_name.endswith("data_quality_evaluation") else "应用成效评估"
        label = "数据质量" if skill_name.endswith("data_quality_evaluation") else "应用成效"
        body = _render_dimension(result.raw, label) or result.observation or "暂未找到可用的评分数据。"
        return ToolResult(result.ok, f"【特殊作业{title}】\n{body}", raw=result.raw, error_code=result.error_code)

    if skill_name == "special_score_drilldown":
        prefix = "【特殊作业扣分明细】"
        body = _render_drilldown(result.raw, result.observation)
        return ToolResult(result.ok, f"{prefix}\n{body}", raw=result.raw, error_code=result.error_code)

    if skill_name == "special_ticket_issue":
        prefix = "【特殊作业问题票据】"
        body = _render_ticket_issues(result.raw, result.observation)
        return ToolResult(result.ok, f"{prefix}\n{body}", raw=result.raw, error_code=result.error_code)

    return result
