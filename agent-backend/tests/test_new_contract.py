import asyncio
import httpx
import pytest
from jinja2 import ChainableUndefined, Environment

from app.main import app
from app.api.schemas import ChatRequest
from app.config import BASE_DIR
from app.tools.loader import load_tool_configs
from app.tools.protocol import ExecContext, ToolResult
from app.tools.skills import SkillExecutor
from app.llm.client import ToolCall


def test_frontend_fixed_parameters_are_accepted():
    request = ChatRequest.model_validate({
        'inputs': {
            'user_choice': '3',
            'traceId': 'trace-20260903-001',
            'upload_file': [{'name': '评分附件.xlsx', 'url': '/upload/a.xlsx'}],
        },
        'query': '继续',
        'response_mode': 'streaming',
        'user': '123',
        'files': [],
        'conversation_id': 'abc-def-123',
    })
    assert request.user_choice == '3'
    assert request.traceId == 'trace-20260903-001'
    assert request.inputs['user_choice'] == '3'
    assert len(request.upload_file) == 1


def test_legacy_top_level_fixed_parameters_are_still_accepted():
    request = ChatRequest.model_validate({'query': '测试', 'user_choice': '2', 'traceId': 't-1', 'upload_file': []})
    assert request.inputs['user_choice'] == '2'


def test_frontend_user_choice_rejects_unknown_value():
    with pytest.raises(ValueError):
        ChatRequest.model_validate({'query': '测试', 'user_choice': '4', 'traceId': '', 'upload_file': []})


def test_new_score_templates_render_string_item_codes_and_batch_calculate():
    configs = {c.name: c for c in load_tool_configs(BASE_DIR / 'config' / 'tools.yaml')}
    detail = {
        'score': 86, 'maxScore': 100,
        'modules': [{'moduleCode': 'major', 'moduleName': '重大危险源', 'score': 86, 'maxScore': 100,
                     'dimensions': [{'dimensionCode': 'dataQuality', 'dimensionName': '数据质量', 'score': 18, 'maxScore': 20,
                                     'items': [{'itemNo': 'major-dataQuality-x', 'itemName': '完整性评估', 'score': 0,
                                                'maxScore': 5, 'status': 'BUSINESS_ISSUE', 'detailText': '字段缺失', 'entities': []}]}]}]
    }
    text = Environment(undefined=ChainableUndefined).from_string(configs['score_evaluate_detail'].http.observation_template).render(**detail)
    assert 'major-dataQuality-x' in text and 'BUSINESS_ISSUE' in text
    batch = {'data': [{'itemNo': 'special-functionBuild-x', 'itemName': '报备建设', 'score': 3, 'maxScore': 3, 'status': 'PASS', 'detailText': '正常', 'entities': []}]}
    text = Environment(undefined=ChainableUndefined).from_string(configs['score_calculate'].http.observation_template).render(**batch)
    assert 'special-functionBuild-x' in text and 'PASS' in text


@pytest.mark.asyncio
async def test_thought_is_visible_but_final_answer_is_unwrapped():
    from app.graph import runner
    req = __import__('app.api.schemas', fromlist=['ChatRequest']).ChatRequest(query='你好', response_mode='blocking', user='smoke')
    events = [e async for e in runner.chat_event_stream(req)]
    end = events[-1]
    assert end.event == 'message_end'
    assert '<thought>' not in end.data['answer']
    messages = [e.data.get('answer', '') for e in events if e.event == 'message']
    final_chunks = [x for x in messages if '<thought>' not in x]
    assert ''.join(final_chunks) == end.data['answer']
    assert all(len(x) == 1 for x in final_chunks)


@pytest.mark.asyncio
async def test_blocking_error_hides_internal_detail():
    from app.api.routes import _to_blocking_response
    from app.sse.event import SSEEvent
    result = _to_blocking_response([SSEEvent('message_start', {'message_id': 'm', 'conversation_id': 'c', 'created_at': 1}), SSEEvent('error', {'code': 'X', 'status': 503, 'message': 'secret'})])
    assert result.answer == '暂无法完成评分查询，请稍后重试。'
    assert 'secret' not in result.answer
