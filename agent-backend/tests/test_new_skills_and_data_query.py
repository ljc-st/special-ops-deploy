import pytest

from app.llm.client import ToolCall
from app.tools.protocol import ExecContext, ToolResult
from app.tools.skills import SkillExecutor
from app.tools.score_format import _score_text, format_special_result


EVAL = {
    'score': 3, 'maxScore': 10,
    'modules': [{'moduleCode': 'special', 'moduleName': '特殊作业', 'score': 3, 'maxScore': 10,
                 'dimensions': [{'dimensionCode': 'functionBuild', 'dimensionName': '功能建设', 'score': 3, 'maxScore': 3,
                                 'items': [{'itemNo': 'special-functionBuild-report', 'itemName': '报备功能建设', 'score': 3, 'maxScore': 3, 'status': 'PASS', 'detailText': '正常'}]},
                                {'dimensionCode': 'applicationEffect', 'dimensionName': '应用成效', 'score': 0, 'maxScore': 7,
                                 'items': [{'itemNo': 'special-applicationEffect-ticket', 'itemName': '作业票应用评估', 'score': 0, 'maxScore': 7, 'status': 'DATA_INSUFFICIENT', 'detailText': '数据不足', 'entities': []}]}]}]
}

@pytest.mark.asyncio
async def test_item_search_and_detail_use_formal_code():
    calls = []
    async def run(name, args, ctx):
        calls.append((name, args))
        if name == 'score_evaluate_detail': return ToolResult(True, '', raw=EVAL)
        return ToolResult(True, '', raw=[{'itemNo': args['itemNo'], 'itemName': '报备功能建设', 'score': 3, 'maxScore': 3, 'status': 'PASS', 'detailText': '正常', 'entities': []}])
    executor = SkillExecutor(run)
    result = await executor.execute(ToolCall(id='1', name='special_item_detail', arguments={'keyword':'报备'}), None, ExecContext())
    assert result.ok
    assert calls[-1][1]['itemNo'] == 'special-functionBuild-report'

@pytest.mark.asyncio
async def test_status_diagnosis_distinguishes_data_insufficient():
    async def run(name, args, ctx): return ToolResult(True, '', raw=EVAL)
    result = await SkillExecutor(run).execute(ToolCall(id='1', name='special_status_diagnosis', arguments={}), None, ExecContext())
    assert result.ok and '数据不足' in result.observation

@pytest.mark.asyncio
async def test_database_query_is_safe_before_credentials_are_configured():
    async def run(name, args, ctx): return ToolResult(True, '', raw=EVAL)
    result = await SkillExecutor(run).execute(ToolCall(id='1', name='special_data_query', arguments={'question':'查询最近评分明细'}), None, ExecContext())
    assert not result.ok
    assert result.error_code == 'DATA_QUERY_NOT_CONFIGURED'
    assert '数据库' in result.observation


def test_score_format_preserves_zero_and_missing_values():
    assert _score_text({'score': 0, 'maxScore': 3}) == '0.00 / 3.00'
    assert _score_text({'score': 0, 'maxScore': 0}) == '-0.00 / 0.00'
    assert _score_text({'score': '0/0'}) == '-0.00 / 0.00'
    assert _score_text({'score': -20, 'maxScore': 0}) == '-20.00 / 0.00'
    assert _score_text({'score': '-', 'maxScore': 0}) == '数据不足'
    assert _score_text({'score': '0/3'}) == '0.00 / 3.00'


def test_function_build_format_unwraps_java_data_and_hides_internal_code():
    result = ToolResult(True, '', raw={'data': [{
        'itemNo': 'special-functionBuild-report',
        'itemName': '特殊作业报备功能建设情况评估',
        'score': 0,
        'maxScore': 3,
        'status': 'BUSINESS_ISSUE',
        'detailText': '未发现相关数据',
    }]})
    formatted = format_special_result('special_report_function_build', result)
    assert '0.00 / 3.00' in formatted.observation
    assert 'special-functionBuild-report' not in formatted.observation
    assert '情况总结：特殊作业功能建设板块' in formatted.observation
    assert '特殊作业功能建设板块总结建议：' in formatted.observation


def test_dimension_summary_uses_full_special_operation_name():
    result = ToolResult(True, '', raw={
        'dimensionCode': 'dataQuality',
        'dimensionName': '数据质量',
        'dimension': {'dimensionCode': 'dataQuality', 'dimensionName': '数据质量', 'score': 0, 'maxScore': 30},
        'items': [{
            'itemNo': f'special-dataQuality-item-{index}',
            'itemName': f'数据质量评分项{index}',
            'score': 0,
            'maxScore': 5,
            'status': 'DATA_INSUFFICIENT',
            'detailText': '评分所需数据不足',
        } for index in range(1, 4)],
    })
    formatted = format_special_result('special_data_quality_evaluation', result)
    assert '情况总结：特殊作业数据质量板块共核查3项' in formatted.observation
    assert '特殊作业数据质量板块总结建议：' in formatted.observation
    assert '\n数据质量总结建议：' not in formatted.observation


def test_application_effect_penalty_rows_and_note_are_user_facing():
    result = ToolResult(True, '', raw={
        'dimensionCode': 'applicationEffect',
        'dimensionName': '应用成效',
        'dimension': {'dimensionCode': 'applicationEffect', 'score': 0, 'maxScore': 60},
        'items': [{
            'itemNo': f'special-applicationEffect-item-{index}',
            'itemName': f'应用成效扣分项{index}',
            'score': 0,
            'maxScore': 0,
            'status': 'DATA_INSUFFICIENT',
            'detailText': '该项因评分所需数据不足，无法完成计算',
        } for index in range(1, 4)],
    })
    formatted = format_special_result('special_application_effect_evaluation', result)
    assert '-0.00 / 0.00' in formatted.observation
    assert '>—</td>' in formatted.observation
    assert '无法完成评估' in formatted.observation
    assert '无法完成计算' not in formatted.observation
    assert '注：对于扣分项，当某项评估指标因数据不足无法完成评估时，该项扣分将全部扣除。' in formatted.observation
