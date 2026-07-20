import re
import unicodedata
from types import MappingProxyType

from app.schemas.tools import CaseEvaluateRequest, CaseEvaluateResponse


BASE_FIELDS = ("grain_type", "storage_type", "storage_days", "goal")
GOAL_REQUIRED_FIELDS = MappingProxyType(
    {
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
)
GOAL_KEYWORDS = MappingProxyType(
    {
        "mold": ("霉变", "发霉", "霉菌"),
        "pest": ("虫害", "害虫", "虫情"),
        "co2": ("二氧化碳", "co2"),
        "temperature": ("粮温", "温度", "温度变化", "温度趋势"),
        "moisture": ("含水率", "水分"),
    }
)
FIELD_LABELS = {
    "grain_type": "粮种",
    "storage_type": "仓型与储藏方式",
    "storage_days": "储藏时间",
    "goal": "分析目标",
    "moisture_percent": "粮食水分",
    "grain_temperature_c": "粮温",
    "temperature_trend": "粮温趋势",
    "ambient_temperature_c": "环境温度",
    "ambient_humidity_percent": "环境湿度",
    "co2_ppm": "二氧化碳浓度",
    "co2_trend": "二氧化碳趋势",
    "pest_signs": "虫害迹象",
    "mold_signs": "霉变迹象",
    "condensation_signs": "结露迹象",
}


def _normalize_goal(goal: str) -> str:
    normalized = unicodedata.normalize("NFKC", goal).casefold()
    return re.sub(r"\s+", "", normalized)


def _contains_keyword(goal: str, keyword: str) -> bool:
    if keyword.isascii() and keyword.isalnum():
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])",
                goal,
            )
        )
    return keyword in goal


def _goal_families(goal: str | None) -> tuple[str, ...]:
    if not goal:
        return ()
    normalized = _normalize_goal(goal)
    return tuple(
        family
        for family, keywords in GOAL_KEYWORDS.items()
        if any(_contains_keyword(normalized, keyword) for keyword in keywords)
    )


class CaseEvaluator:
    def evaluate(self, request: CaseEvaluateRequest) -> CaseEvaluateResponse:
        families = _goal_families(request.case.goal)
        required_fields = tuple(
            dict.fromkeys(
                (
                    *BASE_FIELDS,
                    *(
                        field
                        for family in families
                        for field in GOAL_REQUIRED_FIELDS[family]
                    ),
                )
            )
        )
        missing = [
            field
            for field in required_fields
            if getattr(request.case, field) in (None, "")
        ]
        question = None
        if missing:
            labels = "、".join(FIELD_LABELS[field] for field in missing)
            question = f"请补充以下关键信息：{labels}。"
        return CaseEvaluateResponse(
            request_id=request.request_id,
            needs_input=bool(missing),
            missing_fields=missing,
            question=question,
            rules=[],
        )
