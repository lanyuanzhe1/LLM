import pytest

from app.domain.cases.rules import CaseEvaluator
from app.schemas.api import CaseData
from app.schemas.tools import CaseEvaluateRequest


GOAL_REQUIRED_FIELDS = {
    "mold": (
        "moisture_percent",
        "grain_temperature_c",
        "ambient_humidity_percent",
        "mold_signs",
        "condensation_signs",
    ),
    "pest": ("grain_temperature_c", "pest_signs"),
    "co2": ("co2_ppm", "co2_trend"),
    "temperature": (
        "grain_temperature_c",
        "temperature_trend",
        "ambient_temperature_c",
    ),
    "moisture": ("moisture_percent", "ambient_humidity_percent"),
}


def _complete_base_case(goal: str, **fields) -> CaseData:
    return CaseData(
        grain_type="小麦",
        storage_type="平房仓",
        storage_days=60,
        goal=goal,
        **fields,
    )


def test_case_evaluator_asks_for_missing_base_fields_before_goal_fields():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=CaseData(grain_type="小麦", goal="判断霉变风险"),
        )
    )

    assert response.needs_input is True
    assert response.missing_fields[:2] == ["storage_type", "storage_days"]
    assert "仓型" in response.question


@pytest.mark.parametrize(
    ("goal", "family"),
    [
        ("判断霉变风险", "mold"),
        ("检查虫害迹象", "pest"),
        ("分析二氧化碳趋势", "co2"),
        ("分析粮温变化", "temperature"),
        ("评估温度情况", "temperature"),
        ("判断含水率情况", "moisture"),
    ],
)
def test_goal_family_requires_declared_measurements(goal, family):
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case(goal),
        )
    )

    assert response.needs_input is True
    assert response.missing_fields == list(GOAL_REQUIRED_FIELDS[family])
    assert response.rules == []
    assert "风险等级" not in (response.question or "")


@pytest.mark.parametrize(
    ("goal", "family"),
    [
        ("  判断 霉变 风险  ", "mold"),
        ("检查 虫害 迹象", "pest"),
        ("分析 CO₂ 趋势", "co2"),
        ("分析 co2 趋势", "co2"),
        ("关注 粮温 变化", "temperature"),
        ("判断 水分 状况", "moisture"),
    ],
)
def test_goal_matching_is_case_and_whitespace_robust(goal, family):
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case(goal),
        )
    )

    assert response.missing_fields == list(GOAL_REQUIRED_FIELDS[family])


def test_unknown_goal_requires_only_base_fields():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case("评估仓房整体情况"),
        )
    )

    assert response.needs_input is False
    assert response.missing_fields == []
    assert response.question is None
    assert response.rules == []


def test_incidental_ascii_substrings_do_not_match_goal_families():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case("compare temperature models"),
        )
    )

    assert response.missing_fields == []
    assert response.rules == []


def test_co2_keyword_does_not_match_inside_a_longer_ascii_token():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case("检查 CO20 传感器型号"),
        )
    )

    assert response.missing_fields == []
    assert response.rules == []


def test_complete_goal_case_returns_no_unsourced_rules_or_conclusions():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case(
                "判断霉变风险",
                moisture_percent=12.5,
                grain_temperature_c=18.0,
                ambient_humidity_percent=60.0,
                mold_signs=False,
                condensation_signs=False,
            ),
        )
    )

    assert response.needs_input is False
    assert response.rules == []
    assert response.question is None


@pytest.mark.parametrize(
    ("goal", "expected_fields"),
    [
        (
            "判断霉变和虫害风险",
            [
                *GOAL_REQUIRED_FIELDS["mold"],
                "pest_signs",
            ],
        ),
        (
            "分析温度与二氧化碳趋势",
            [
                *GOAL_REQUIRED_FIELDS["co2"],
                *GOAL_REQUIRED_FIELDS["temperature"],
            ],
        ),
    ],
)
def test_composite_goals_merge_all_families_in_declared_order(
    goal,
    expected_fields,
):
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=_complete_base_case(goal),
        )
    )

    assert response.needs_input is True
    assert response.missing_fields == expected_fields
    assert len(response.missing_fields) == len(set(response.missing_fields))
    assert response.rules == []
