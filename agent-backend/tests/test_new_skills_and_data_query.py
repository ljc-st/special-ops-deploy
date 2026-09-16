import pytest

from app.graph.prompts import OUTPUT_CONTRACT
from app.log_client import thought_for_query
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


def test_output_contract_uses_full_user_facing_names():
    assert '评估总结：' in OUTPUT_CONTRACT
    assert '特殊作业功能建设维度' in OUTPUT_CONTRACT
    assert '特殊作业数据质量维度' in OUTPUT_CONTRACT
    assert '特殊作业应用成效维度' in OUTPUT_CONTRACT
    assert '特殊作业报备数据、特殊作业票数据、特殊作业抽查数据' in OUTPUT_CONTRACT


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
    assert '评估总结：特殊作业报备功能建设情况评估' in formatted.observation
    assert '特殊作业报备功能建设情况评估总结建议：' in formatted.observation
    assert '情况总结：' not in formatted.observation
    assert '特殊作业功能建设维度' not in formatted.observation


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
    assert '评估总结：特殊作业数据质量维度共核查3项' in formatted.observation
    assert '特殊作业数据质量维度总结建议：' in formatted.observation
    assert '\n数据质量总结建议：' not in formatted.observation
    assert '情况总结：' not in formatted.observation
    assert '板块' not in formatted.observation


def test_single_dimension_item_summary_uses_item_name_only():
    result = ToolResult(True, '', raw={
        'dimensionCode': 'dataQuality',
        'dimensionName': '数据质量',
        'dimension': {'dimensionCode': 'dataQuality', 'score': 0, 'maxScore': 5},
        'singleItem': True,
        'items': [{
            'itemNo': 'special-dataQuality-item-1.1',
            'itemName': '特殊作业数据完整性评估',
            'score': 0,
            'maxScore': 5,
            'status': 'DATA_INSUFFICIENT',
            'detailText': '评分所需数据不足',
        }],
    })
    formatted = format_special_result('special_data_quality_evaluation', result)
    assert '评估总结：特殊作业数据完整性评估' in formatted.observation
    assert '特殊作业数据质量维度' not in formatted.observation
    assert '1.1' not in formatted.observation


def test_visible_thought_is_three_plain_language_steps():
    thought = thought_for_query('请评估特殊作业功能建设')
    assert thought.splitlines()[0].startswith('第一步：')
    assert thought.splitlines()[1].startswith('第二步：')
    assert thought.splitlines()[2].startswith('第三步：')
    assert 'SQL' not in thought
    assert 'itemNo' not in thought


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
