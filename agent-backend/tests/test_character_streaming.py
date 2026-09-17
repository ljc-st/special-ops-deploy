import pytest

from app.api.schemas import ChatRequest
from app.graph.runner import _normalize_answer_markup, _render_table_html
from app.tools.score_format import _html_table


def test_score_table_uses_adaptive_width_and_semantic_alignment():
    table = _html_table([{
        "itemNo": "special-functionBuild-report",
        "itemName": "特殊作业报备功能建设情况评估",
        "score": 0,
        "maxScore": 3,
        "status": "BUSINESS_ISSUE",
        "detailText": "未发现相关数据",
    }])
    assert "width:max-content;min-width:100%" in table
    assert "min-width:72px;text-align:center" in table
    assert "min-width:280px;text-align:center" in table
    assert "min-width:140px;text-align:center" in table
    assert "min-width:560px;text-align:center" in table
    assert "overflow-x:auto" in table


def test_score_reason_alignment_depends_on_whole_column_length():
    short_table = _render_table_html([
        "| 序号 | 评分项 | 得分 | 状态 | 原因 |\n",
        "|---|---|---|---|---|\n",
        "| 1 | 报备评估 | 0/3 | 数据不足 | 评分所需数据不足 |\n",
        "| 2 | 作业票评估 | 0/3 | 数据不足 | 评分所需数据不足 |\n",
    ])
    assert "min-width:280px;text-align:center" in short_table
    assert "min-width:560px;text-align:center" in short_table

    long_table = _render_table_html([
        "| 序号 | 评分项 | 得分 | 状态 | 原因 |\n",
        "|---|---|---|---|---|\n",
        "| 1 | 报备评估 | 0/3 | 数据不足 | 评分所需数据不足 |\n",
        "| 2 | 作业票评估 | 0/3 | 数据不足 | 该项评分所需数据不足，且包含较长的企业覆盖率、更新时间和字段完整性说明，需要左对齐展示 |\n",
    ])
    assert "min-width:560px;text-align:left" in long_table


def test_old_summary_labels_are_normalized_to_module():
    text = _normalize_answer_markup("情况总结：特殊作业功能建设板块共核查3项。")
    assert text == "评估总结：特殊作业功能建设模块共核查3项。"


def test_generic_table_supports_more_than_four_columns():
    table = _render_table_html([
        "| 一 | 二 | 三 | 四 | 五 | 六 |\n",
        "|---|---|---|---|---|---|\n",
        "| a | b | c | d | e | f |\n",
    ])
    assert table.count("<th ") == 6
    assert "width:max-content;min-width:100%" in table


@pytest.mark.asyncio
async def test_final_answer_messages_stream_one_character_at_a_time():
    from app.graph import runner

    request = ChatRequest(
        query="你好",
        response_mode="streaming",
        user="stream-test",
        user_choice="1",
        traceId="trace-stream-test",
        upload_file=[],
    )
    events = [event async for event in runner.chat_event_stream(request)]
    final_answer = events[-1].data["answer"]
    answer_chunks = [
        event.data.get("answer", "")
        for event in events
        if event.event == "message" and "<thought>" not in event.data.get("answer", "")
    ]

    thoughts = [event.data.get("answer", "") for event in events if "<thought>" in event.data.get("answer", "")]
    assert final_answer
    assert "".join(answer_chunks) == final_answer
    assert all(len(chunk) == 1 for chunk in answer_chunks)
    assert len(thoughts) == 1
    assert "正在调用" not in thoughts[0]
