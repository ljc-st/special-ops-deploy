"""系统评分总分接口联调测试。

用法：
  SCORE_BASE_URL=http://127.0.0.1:8081 pytest -q tests/test_system_score_total_api.py

也可以只运行实时明细测试：
  SCORE_BASE_URL=http://127.0.0.1:8081 pytest -q tests/test_system_score_total_api.py -k detail
"""

import os
from math import isclose

import httpx
import pytest


BASE_URL = os.getenv("SCORE_BASE_URL", "http://127.0.0.1:8081").rstrip("/")
MODULES = ("special", "closed", "major", "dual", "safety", "emergency", "operation")
STATUSES = {"PASS", "BUSINESS_ISSUE", "DATA_INSUFFICIENT", "CALCULATION_ERROR"}


def _post(path: str, payload: dict) -> dict:
    response = httpx.post(f"{BASE_URL}{path}", json=payload, timeout=60.0)
    assert response.status_code == 200, (
        f"{path} 返回 HTTP {response.status_code}: {response.text[:500]}"
    )
    body = response.json()
    assert isinstance(body, dict), f"{path} 返回体应为对象，实际为 {type(body).__name__}"
    return body


def _assert_result_tree(result: dict) -> None:
    assert isinstance(result.get("parkId"), str) and result["parkId"]
    assert isinstance(result.get("score"), (int, float))
    assert isinstance(result.get("maxScore"), (int, float))
    modules = result.get("modules")
    assert isinstance(modules, list) and modules, "modules 不能为空"

    module_score = 0.0
    module_max_score = 0.0
    for module in modules:
        assert module.get("moduleCode") in MODULES
        assert isinstance(module.get("moduleName"), str) and module["moduleName"]
        assert isinstance(module.get("score"), (int, float))
        assert isinstance(module.get("maxScore"), (int, float))
        dimensions = module.get("dimensions")
        assert isinstance(dimensions, list) and dimensions

        dimension_score = 0.0
        dimension_max_score = 0.0
        for dimension in dimensions:
            assert isinstance(dimension.get("dimensionCode"), str)
            assert isinstance(dimension.get("dimensionName"), str)
            assert isinstance(dimension.get("score"), (int, float))
            assert isinstance(dimension.get("maxScore"), (int, float))
            items = dimension.get("items")
            assert isinstance(items, list)
            for item in items:
                assert isinstance(item.get("itemNo"), str) and "-" in item["itemNo"]
                assert isinstance(item.get("itemName"), str) and item["itemName"]
                assert isinstance(item.get("score"), (int, float))
                assert isinstance(item.get("maxScore"), (int, float))
                assert item.get("status") in STATUSES
                assert isinstance(item.get("detailText"), str)
                assert isinstance(item.get("entities"), list)
            dimension_score += float(dimension["score"])
            dimension_max_score += float(dimension["maxScore"])

        assert isclose(dimension_score, float(module["score"]), abs_tol=0.01), (
            f"模块 {module['moduleCode']} 的维度得分之和不等于模块得分"
        )
        assert isclose(dimension_max_score, float(module["maxScore"]), abs_tol=0.01), (
            f"模块 {module['moduleCode']} 的维度满分之和不等于模块满分"
        )
        module_score += float(module["score"])
        module_max_score += float(module["maxScore"])

    assert isclose(module_score, float(result["score"]), abs_tol=0.01), (
        "根节点 score 不等于所有模块 score 之和"
    )
    assert isclose(module_max_score, float(result["maxScore"]), abs_tol=0.01), (
        "根节点 maxScore 不等于所有模块 maxScore 之和"
    )


@pytest.mark.integration
def test_evaluate_total_score_contract() -> None:
    """验证 POST /systemScore/evaluate 的全模块总分契约。"""
    _assert_result_tree(_post("/systemScore/evaluate", {}))


@pytest.mark.integration
def test_evaluate_detail_special_score_contract() -> None:
    """验证 POST /systemScore/evaluate/detail 的特殊作业总分契约。"""
    result = _post("/systemScore/evaluate/detail", {"modules": ["special"]})
    _assert_result_tree(result)
    assert [module["moduleCode"] for module in result["modules"]] == ["special"]
