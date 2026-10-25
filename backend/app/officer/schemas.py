"""Strict officer command bodies and queue filters. Unknown keys are 422 at every level, so no status, assignee,
phase, kind or score can be injected; the officer comes from the session."""
from typing import Literal
from pydantic import Field, StrictStr, field_validator
from ..applications.info_requests import ANSWER_PATHS
from ..applications.schemas import MAX_RUB, ReasonText
from ..schemas import StrictModel

AssigneeFilter = Literal['me', 'unassigned']


class ReasonedInput(StrictModel):
    """Every officer decision: the current version and a reason of 1-2000 characters after trimming."""
    version: int = Field(ge=1, strict=True)
    reason: ReasonText


class RejectInput(ReasonedInput):
    pass


class PreapproveInput(ReasonedInput):
    amount_rub: int = Field(strict=True, gt=0, le=MAX_RUB)


class RequestInfoInput(ReasonedInput):
    """The reason is the question shown to the customer; the fields are distinct questionnaire answer paths."""
    requested_fields: list[StrictStr] = Field(min_length=1, max_length=len(ANSWER_PATHS))

    @field_validator('requested_fields')
    @classmethod
    def answer_paths(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or not set(value) <= set(ANSWER_PATHS):
            raise ValueError('Укажите разные поля анкеты из её состава')
        return value
