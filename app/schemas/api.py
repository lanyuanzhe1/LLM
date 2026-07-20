from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


StrictFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
StrictInteger = Annotated[int, Field(strict=True)]
StrictBoolean = Annotated[bool, Field(strict=True)]


class StrictPublicRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class Role(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    RESEARCHER = "researcher"
    TECHNICIAN = "technician"


class ChatRequest(StrictPublicRequest):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    role: Role = Role.STUDENT
    project_id: str | None = Field(default=None, min_length=1, max_length=64)


class CaseData(StrictPublicRequest):
    grain_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    storage_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    moisture_percent: StrictFloat | None = Field(default=None, ge=0, le=100)
    grain_temperature_c: StrictFloat | None = Field(
        default=None,
        ge=-50,
        le=100,
    )
    temperature_trend: Literal["rising", "stable", "falling"] | None = None
    ambient_temperature_c: StrictFloat | None = Field(
        default=None,
        ge=-50,
        le=100,
    )
    ambient_humidity_percent: StrictFloat | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    co2_ppm: StrictFloat | None = Field(default=None, ge=0)
    co2_trend: Literal["rising", "stable", "falling"] | None = None
    pest_signs: StrictBoolean | None = None
    mold_signs: StrictBoolean | None = None
    condensation_signs: StrictBoolean | None = None
    storage_days: StrictInteger | None = Field(default=None, ge=0)
    goal: str | None = Field(default=None, min_length=1, max_length=1000)


class CaseAnalyzeRequest(StrictPublicRequest):
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    role: Role = Role.TECHNICIAN
    case: CaseData
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
