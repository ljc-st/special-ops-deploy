"""Stable user-facing summaries for scoring skill results（统一结果模型）。"""

from app.tools.protocol import ToolResult
from html import escape as _html_escape


def _clean_reason(reason: object) -> str:
    """Remove evaluation time windows while retaining business facts."""
    import re
    text = str(reason or "").strip()
    # 面向用户统一使用“评估”，避免暴露偏技术化的“计算”措辞。
    text = text.replace("无法完成计算", "无法完成评估")
    text = text.replace("完成计算", "完成评估")
    text = re.sub(r"评价窗口[^，。；]*[，。；]?", "", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}T[^，。；]*至\d{4}-\d{2}-\d{2}T[^，。；]*", "", text)
    # 接口详情有时会把几十家企业完整拼在原因中，保留前三家和总数即可。
    pattern = re.compile(r"(涉及(?:实体|企业)(?:包括|为)?[:：]\s*)([^。；\n]+)")
    def compact(match: re.Match) -> str:
        names = [part.strip() for part in re.split(r"[、,，]", match.group(2)) if part.strip()]
        if len(names) <= 4:
            return match.group(0)
        count_match = re.search(r"(?:共|等)\s*(\d+)\s*家", match.group(2))
        count = count_match.group(1) if count_match else str(len(names))
        return match.group(1) + "、".join(names[:3]) + f"等{count}家"
    text = pattern.sub(compact, text)
    return text.strip(" ，。；")


_STATUS_TEXT = {
    "PASS": "通过",
    "BUSINESS_ISSUE": "存在问题",
    "DATA_INSUFFICIENT": "数据不足",
    "CALCULATION_ERROR": "计算异常",
}

_SCORE_ITEM_SEQUENCE = (
    ("报备功能建设", "1.1"),
    ("作业票管理功能建设", "1.2"),
    ("作业票功能建设", "1.2"),
    ("抽查功能建设", "1.3"),
    ("重复数据", "2.1"),
    ("数据冗余", "2.1"),
    ("报备接入率", "2.2"),
    ("报备数据接入", "2.2"),
    ("作业票接入率", "2.3"),
    ("作业票数据接入", "2.3"),
    ("电子票数据接入", "2.3"),
    ("报备字段完整性", "2.4"),
    ("报备记录关键要素完整性", "2.4"),
    ("作业票字段完整性", "2.5"),
    ("作业票记录关键要素完整性", "2.5"),
    ("票接入记录关键要素完整性", "2.5"),
    ("视频/经纬度", "2.6"),
    ("视频经纬度", "2.6"),
    ("视频字段", "2.6"),
    ("独特性数据接入", "2.6"),
    ("动火作业独特性", "2.6"),
    ("报备有效性", "3.1"),
    ("设备有效性", "3.1"),
    ("报备及时性", "3.2"),
    ("设备及时性", "3.2"),
    ("作业票有效性", "3.2"),
    ("作业票管理功能应用活跃度", "3.3"),
    ("票管理功能应用活跃度", "3.3"),
    ("报备功能应用充分性", "3.4"),
    ("报备功能应用活跃度", "3.5"),
    ("报备应用活跃度", "3.5"),
    ("作业票管理功能应用充分性", "3.6"),
    ("抽查功能应用活跃度", "3.7"),
    ("抽查应用活跃度", "3.7"),
    ("抽查功能应用充分性", "3.8"),
    ("园区监管整体覆盖性", "3.9"),
    ("安全承诺公告与报备数据一致性", "3.10"),
    ("安全承诺公告与作业票数据一致性", "3.11"),
    ("作业票面符合性", "3.12"),
    ("审批流转合理性", "3.13"),
    ("审批时间合理性", "3.14"),
    ("完工验收及时性", "3.15"),
    ("交叉作业评估", "3.16"),
)

_ITEM_CODE_NAMES = {
    "special-applicationEffect-tszypglgnyyhydpg": "特殊作业票管理功能应用活跃度评估",
    "special-applicationEffect-tszypglgnyycfxpg": "特殊作业票管理功能应用充分性评估",
    "special-applicationEffect-tszybbgnyyhydpg": "特殊作业报备功能应用活跃度评估",
    "special-applicationEffect-tszybbgnyycfxpg": "特殊作业报备功能应用充分性评估",
    "special-applicationEffect-tszyccgnyyhydpg": "特殊作业抽查功能应用活跃度评估",
    "special-applicationEffect-tszyccgnyycfxpg": "特殊作业抽查功能应用充分性评估",
}

_DIMENSION_DISPLAY_NAMES = {
    "functionBuild": "特殊作业功能建设维度",
    "功能建设": "特殊作业功能建设维度",
    "特殊作业功能建设": "特殊作业功能建设维度",
    "特殊作业功能建设板块": "特殊作业功能建设维度",
    "dataQuality": "特殊作业数据质量维度",
    "数据质量": "特殊作业数据质量维度",
    "数据质量评估": "特殊作业数据质量维度",
    "特殊作业数据质量": "特殊作业数据质量维度",
    "特殊作业数据质量板块": "特殊作业数据质量维度",
    "applicationEffect": "特殊作业应用成效维度",
    "应用成效": "特殊作业应用成效维度",
    "应用成效评估": "特殊作业应用成效维度",
    "特殊作业应用成效": "特殊作业应用成效维度",
    "特殊作业应用成效板块": "特殊作业应用成效维度",
}


def _full_dimension_name(value: object, code: object = "") -> str:
    """将 Java 返回的维度简称转换为面向用户的完整业务名称。"""
    raw = str(value or "").strip()
    raw_code = str(code or "").strip()
    if raw_code in _DIMENSION_DISPLAY_NAMES:
        return _DIMENSION_DISPLAY_NAMES[raw_code]
    if raw in _DIMENSION_DISPLAY_NAMES:
        return _DIMENSION_DISPLAY_NAMES[raw]
    if raw.startswith("特殊作业"):
        return raw
    return f"特殊作业{raw}维度" if raw else "特殊作业评分维度"


def _score_sequence(item_no: object, item_name: object) -> str:
    """将正式评分编码转换为业务展示序号，未知项保留占位符。"""
    import re

    raw_no = str(item_no or "")
    match = re.search(r"(?:^|[^\d])(\d+\.\d+(?:\.\d+)?)(?:$|[^\d])", raw_no)
    if match:
        return match.group(1)
    name = str(item_name or "") or _ITEM_CODE_NAMES.get(raw_no, "")
    for keyword, sequence in _SCORE_ITEM_SEQUENCE:
        if keyword in name:
            return sequence
    return "—"


def _score_item_cell(item_no: object, item_name: object) -> str:
    """第二列只展示业务名称，正式编码仅用于内部匹配序号。"""
    raw_code = str(item_no or "").strip()
    # 接口未给名称时也不能把内部 itemNo 暴露给用户。
    name = str(item_name or "").strip() or _ITEM_CODE_NAMES.get(raw_code, "-")
    # 兼容接口把正式编码拼到名称前后的情况，展示给用户时只保留中文名称。
    import re
    name = re.sub(r"\bspecial-[A-Za-z0-9_-]+\b", "", name)
    name = re.sub(r"\s*[（(]编码[:：]?\s*[^）)]*[）)]", "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" ：:，,") or "-"


def _score_text(item: dict) -> str:
    """统一得分展示，兼容接口返回数字或已拼好的“实得/满分”字符串。"""
    # 0 是合法得分，不能用 ``or '-'`` 将其误判为缺失。
    raw_score = item.get("score", "-")
    score = "-" if raw_score is None or str(raw_score).strip() == "" else str(raw_score).strip()
    if "/" in score:
        left, right = (part.strip() for part in score.split("/", 1))
        try:
            if float(left) == 0 and float(right) == 0:
                return "-0.00 / 0.00"
        except (TypeError, ValueError):
            pass
        return f"{_number_text(left)} / {_number_text(right)}"
    raw_max_score = item.get("maxScore", "-")
    max_score = "-" if raw_max_score is None or str(raw_max_score).strip() == "" else raw_max_score
    if score in {"-", "—", "未返回"}:
        try:
            if float(str(max_score).strip()) == 0:
                return "数据不足"
        except (TypeError, ValueError):
            pass
    try:
        # 满分为 0 的项目是扣分项；0 分前加负号，表示该项已无分可扣。
        if float(score) == 0 and float(str(max_score).strip()) == 0:
            return "-0.00 / 0.00"
    except (TypeError, ValueError):
        pass
    return f"{_number_text(score)} / {_number_text(max_score)}"


def _first_item(raw: object) -> dict:
    """取出 calculate 接口返回的首个评分项，兼容 data/items/results 包装。"""
    if isinstance(raw, list):
        return raw[0] if raw and isinstance(raw[0], dict) else {}
    if not isinstance(raw, dict):
        return {}
    for key in ("data", "items", "results"):
        value = raw.get(key)
        if isinstance(value, list):
            return value[0] if value and isinstance(value[0], dict) else {}
        if isinstance(value, dict):
            return value
    return raw


def _number_text(value: object) -> str:
    """分数统一保留两位小数，非数值文本原样保留。"""
    try:
        return f"{float(str(value).strip()):.2f}"
    except (TypeError, ValueError):
        return str(value or "-")


def _ratio_text(score: object, max_score: object, suffix: str = "") -> str:
    return f"{_number_text(score)} / {_number_text(max_score)}{suffix}"


def _html_table(rows: list[dict], include_sequence: bool = True) -> str:
    """输出适配现有网页 Markdown 渲染器的三线表，避免单元格被挤成逐字换行。"""
    head_border = "border:0;border-top:1px solid #6baee2;border-bottom:1px solid #6baee2;"
    cell = "padding:8px 12px;vertical-align:top;font-family:inherit;font-size:16px;line-height:1.6;white-space:nowrap;word-break:normal;overflow-wrap:normal;writing-mode:horizontal-tb;"
    headers = ["序号", "评分项", "得分", "状态", "原因"] if include_sequence else ["评分项", "票号/票据", "企业", "问题原因"]
    widths = (["72px", "280px", "140px", "120px", "560px"] if include_sequence
              else ["280px", "280px", "280px", "600px"])
    centered = {"序号", "得分", "状态"}
    head_html = "".join(
        f'<th style="{head_border}{cell}min-width:{widths[index]};text-align:{"center" if label in centered else "left"};color:#eef7ff;font-weight:700;">{_html_escape(label)}</th>'
        for index, label in enumerate(headers)
    )
    body_html: list[str] = []
    for row_index, row in enumerate(rows):
        border = "border:0;border-bottom:1px solid rgba(142,193,230,.35);"
        if include_sequence:
            values = [
                str(row_index + 1),
                _score_item_cell(row.get("itemNo"), row.get("itemName")),
                _score_text(row),
                _status_text(row.get("status")),
                _detail(row),
            ]
        else:
            # 问题票据表第一列面向用户展示评分项中文名称，正式 itemNo 仅用于内部匹配。
            values = [
                _score_item_cell(row.get("itemNo"), row.get("itemName")),
                row.get("ticket", "-"),
                row.get("company", "-"),
                row.get("reason", "-"),
            ]
        cells = "".join(
            f'<td style="{border}{cell}text-align:{"center" if headers[index] in centered else "left"};color:#d9eaff;">{_html_escape("-" if value is None or value == "" else str(value))}</td>'
            for index, value in enumerate(values)
        )
        body_html.append(f"<tr>{cells}</tr>")
    return (
        '<div style="width:100%;max-width:100%;overflow-x:auto;overflow-y:visible;margin:12px 0;scrollbar-width:thin;">'
        '<table style="width:max-content;min-width:100%;border-collapse:collapse;table-layout:auto;">'
        f"<thead><tr>{head_html}</tr></thead><tbody>{''.join(body_html)}</tbody></table></div>"
    )


def _dimension_summary(items: list[dict], label: str) -> list[str]:
    """面向用户给出简短评估总结和建议，不替代明细原因。"""
    problem = sum(1 for item in items if item.get("status") in {"BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"})
    passed = sum(1 for item in items if item.get("status") == "PASS")
    if problem == 0:
        summary = f"评估总结：{label}共核查{len(items)}项，当前未发现异常。"
        suggestions = [f"- 建议继续保持{label}相关数据的正常更新和使用。"]
    else:
        summary = f"评估总结：{label}共核查{len(items)}项，其中{passed}项通过、{problem}项存在问题或数据不足，问题主要集中在数据覆盖、更新及时性或字段完整性方面。"
        suggestions = [f"- 建议优先补齐{label}中未覆盖或数据不足的评分项。", "- 建议持续更新相关业务数据，并定期复核异常项。"]
    return [summary, f"{label}总结建议：", *suggestions]


def _status_text(status: object) -> str:
    if status is None:
        return "无法判定"
    if str(status) in {"DATA_INSUFFICIENT", "数据不足"}:
        return "—"
    return _STATUS_TEXT.get(str(status), str(status))


def _application_effect_note() -> str:
    return (
        '<div style="margin:6px 0 0;text-align:left;color:#99b7d9;'
        'font-family:inherit;font-size:13px;line-height:1.6;">'
        '注：对于扣分项，当某项评估指标因数据不足无法完成评估时，该项扣分将全部扣除。'
        '</div>'
    )


def _table_cell(value: object) -> str:
    """防止详情文本中的换行或竖线破坏 Markdown 表格。"""
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _detail(item: dict) -> str:
    """评分项详情：detailText + entities 实体名。"""
    parts: list[str] = []
    text = _clean_reason(item.get("detailText") or item.get("reason") or item.get("issueDesc") or "")
    if text:
        parts.append(text)
    entities = item.get("entities") or []
    if entities:
        names = [
            str(e.get("entityName") or e.get("entityId") or "未知")
            for e in entities
            if isinstance(e, dict)
        ]
        if names:
            if len(names) > 4:
                parts.append("涉及实体：" + "、".join(names[:3]) + f"等{len(names)}家")
            else:
                parts.append("涉及实体：" + "、".join(names))
    return "；".join(parts) if parts else "接口未返回原因"


def format_special_result(skill_name: str, result: ToolResult) -> ToolResult:
    """Normalize special skill text without changing its machine-readable raw data."""
    if not result.ok:
        return result
    raw = result.raw

    if skill_name == "special_score_overview":
        data = raw if isinstance(raw, dict) else {}
        if "score" not in data and "totalScore" in data:
            data = {**data, "score": data.get("totalScore"), "maxScore": data.get("totalMaxScore")}
        if not data or not data.get("modules"):
            return ToolResult(result.ok, "【特殊作业评分】\n暂未找到可用的评分数据。", raw=raw, error_code=result.error_code)
        lines = [
            "【特殊作业评分概览】",
            f"总分：{_ratio_text(data.get('score', '-'), data.get('maxScore', '-'), ' 分')}",
        ]
        if "passed" in data:
            lines.append(f"结论：{'通过' if data.get('passed') else '未通过'}")
        modules = data.get("modules") or []
        for dim in modules[0].get("dimensions") or []:
            label = _full_dimension_name(
                dim.get("dimensionName") or dim.get("displayName"),
                dim.get("dimensionCode") or dim.get("key"),
            )
            lines.append(
                f"维度：{label} {_ratio_text(dim.get('score', '-'), dim.get('maxScore', '-'), ' 分')}"
            )
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    if skill_name in {
        "special_report_function_build",
        "special_ticket_function_build",
        "special_inspection_function_build",
    }:
        data = _first_item(raw)
        item_name = _score_item_cell(data.get("itemNo"), data.get("itemName"))
        state = _status_text(data.get("status"))
        body = f"{item_name}：{_score_text(data)}，{state}"
        detail = _detail(data)
        if detail:
            body += f"\n原因：{detail}"
        if state == "通过":
            summary = "评估总结：特殊作业功能建设维度中的该评分项已通过核查，当前未发现异常。"
            suggestion = "特殊作业功能建设维度总结建议：\n- 建议继续保持该功能的正常配置和使用。"
        elif state == "数据不足":
            summary = "评估总结：特殊作业功能建设维度中的该评分项因数据不足，暂无法完整判断实际建设情况。"
            suggestion = "特殊作业功能建设维度总结建议：\n- 建议补齐该功能的相关数据后重新核查。"
        else:
            summary = "评估总结：特殊作业功能建设维度中的该评分项存在异常，具体问题已列在原因中。"
            suggestion = "特殊作业功能建设维度总结建议：\n- 建议根据上述原因及时完善该功能，并在修复后复核评分。"
        return ToolResult(
            result.ok,
            f"【特殊作业单项评估】\n{body}\n\n{summary}\n{suggestion}",
            raw=raw,
            error_code=result.error_code,
        )

    if skill_name in {
        "special_data_quality_evaluation",
        "special_application_effect_evaluation",
    }:
        title = "数据质量评估" if skill_name.endswith("data_quality_evaluation") else "应用成效评估"
        data = raw if isinstance(raw, dict) else {}
        dim = data.get("dimension") or {}
        label = _full_dimension_name(
            data.get("dimensionName") or dim.get("dimensionName") or title,
            data.get("dimensionCode") or dim.get("dimensionCode"),
        )
        lines = [
            f"【特殊作业{title}】",
            f"{label} {_ratio_text(dim.get('score', '-'), dim.get('maxScore', '-'), ' 分')}",
        ]
        items = data.get("items") or []
        if items:
            if len(items) >= 3:
                lines.append("")
                lines.append(_html_table(items))
                if skill_name == "special_application_effect_evaluation":
                    lines.append(_application_effect_note())
            else:
                for index, it in enumerate(items, 1):
                    state = _status_text(it.get("status"))
                    lines.append(
                        f"- {index} "
                        f"{_score_item_cell(it.get('itemNo'), it.get('itemName'))}："
                        f"{_score_text(it)}，{state}；原因：{_detail(it)}"
                    )
            lines.extend(["", *_dimension_summary(items, label)])
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    if skill_name == "special_item_search":
        rows = raw if isinstance(raw, list) else []
        if len(rows) <= 1:
            return result
        lines = ["【特殊作业评分项匹配结果】", "", "| 维度 | 评分项编码 | 评分项名称 |", "|---|---|---|"]
        for row in rows:
            lines.append(f"| {_table_cell(row.get('dimension'))} | {_table_cell(row.get('itemNo'))} | {_table_cell(row.get('itemName'))} |")
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    if skill_name == "special_item_detail":
        data = _first_item(raw)
        if data:
            item_name = _score_item_cell(data.get("itemNo"), data.get("itemName"))
            state = _status_text(data.get("status"))
            text = f"【特殊作业单项详情】\n{item_name}：{_score_text(data)}，{state}\n原因：{_detail(data)}"
            return ToolResult(result.ok, text, raw=raw, error_code=result.error_code)
        return result

    if skill_name == "special_score_drilldown":
        rows = [row for row in (raw if isinstance(raw, list) else []) if isinstance(row, dict)]
        if not rows:
            return ToolResult(result.ok, result.observation, raw=raw, error_code=result.error_code)
        lines = ["【特殊作业扣分明细】", ""]
        if len(rows) >= 3:
            lines.append(_html_table(rows))
        else:
            for index, row in enumerate(rows, 1):
                lines.append(
                    f"- {index} "
                    f"{_score_item_cell(row.get('itemNo'), row.get('itemName'))}："
                    f"{_score_text(row)}，"
                    f"{_status_text(row.get('status'))}；原因：{_detail(row)}"
                )
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    if skill_name == "special_status_diagnosis":
        rows = raw if isinstance(raw, list) else []
        lines = ["【特殊作业评分状态】", "", "| 状态 | 数量 |", "|---|---:|"]
        for row in rows:
            lines.append(f"| {_table_cell(row.get('label'))} | {_table_cell(row.get('count'))} |")
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    if skill_name == "special_data_query":
        data = raw if isinstance(raw, dict) else {}
        columns = data.get("columns") or []
        rows = data.get("rows") or []
        if not rows:
            return ToolResult(result.ok, result.observation or "暂未找到可用数据。", raw=raw, error_code=result.error_code)
        lines = ["【数据库查询明细】", "", "| " + " | ".join(_table_cell(c) for c in columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
        for row in rows:
            lines.append("| " + " | ".join(_table_cell(row.get(c)) for c in columns) + " |")
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    if skill_name == "special_ticket_issue":
        rows = [row for row in (raw if isinstance(raw, list) else []) if isinstance(row, dict)]
        if not rows:
            return ToolResult(result.ok, result.observation, raw=raw, error_code=result.error_code)
        lines = ["【特殊作业问题票据】", ""]
        if len(rows) >= 2:
            lines.append(_html_table(rows, include_sequence=False))
        else:
            row = rows[0]
            lines.append(f"- 评分项：{_score_item_cell(row.get('itemNo'), row.get('itemName'))}")
            lines.append(f"  票号/票据：{_table_cell(row.get('ticket'))}")
            lines.append(f"  企业：{_table_cell(row.get('company'))}")
            lines.append(f"  问题原因：{_table_cell(row.get('reason'))}")
        return ToolResult(result.ok, "\n".join(lines), raw=raw, error_code=result.error_code)

    return result
