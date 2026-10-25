"""Strict request bodies. Unknown keys are 422 at every level (no status, product, company, snapshot, score or BKI
injection). Answers validate type and range on every partial save; completeness and product fit are checked at submit.
Submission consents are only shape-checked here, so a missing or unchecked consent is the domain error NEED_INFO."""
from datetime import date
from typing import Literal
from pydantic import Field, StrictBool, StrictStr, field_validator
from ..schemas import StrictModel

MAX_RUB = 9_000_000_000_000_000
StatusFilter = Literal['DRAFT', 'CHECKING', 'WAIT_EXTERNAL', 'MANUAL_REVIEW', 'NEED_INFO', 'PREAPPROVED', 'DOCS_UPLOADED',
                       'DOCS_REWORK', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED']


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CreateInput(StrictModel):
    company_id: StrictStr = Field(max_length=36)
    product_id: StrictStr = Field(max_length=80)
    recommendation_snapshot_id: StrictStr = Field(max_length=36)


class CollateralAnswer(StrictModel):
    """A partial pledge declaration; it is merged into the saved one key by key."""
    status: Literal['unknown', 'none', 'declared'] | None = None
    type: Literal['real_estate', 'vehicle', 'equipment', 'inventory', 'deposit'] | None = None
    declared_value_rub: int | None = Field(default=None, strict=True, gt=0, le=MAX_RUB)
    description: StrictStr | None = Field(default=None, max_length=500)
    owner_confirmed: StrictBool | None = None
    encumbered: StrictBool | None = None

    _trim = field_validator('description')(blank_to_none)


class AnswersInput(StrictModel):
    """The questionnaire whitelist (spec "Six saved questionnaire stages"); credit history and overdue days are BKI-owned."""
    company_confirmed: StrictBool | None = None
    actual_address: StrictStr | None = Field(default=None, max_length=300)
    actual_activity: StrictStr | None = Field(default=None, max_length=300)
    purpose: Literal['working_capital', 'business_development', 'investment', 'refinancing'] | None = None
    funding_pattern: Literal['one_time', 'repeated'] | None = None
    requested_amount_rub: int | None = Field(default=None, strict=True, gt=0, le=150_000_000)
    term_months: int | None = Field(default=None, strict=True, ge=1, le=120)
    collateral: CollateralAnswer | None = None
    monthly_revenue_rub: int | None = Field(default=None, strict=True, ge=0, le=MAX_RUB)
    previous_monthly_revenue_rub: int | None = Field(default=None, strict=True, ge=0, le=MAX_RUB)
    financial_period_end: date | None = None
    tax_regime: Literal['OSN', 'USN', 'PSN', 'OTHER'] | None = None
    employees: int | None = Field(default=None, strict=True, ge=0, le=1_000_000)
    seasonal: StrictBool | None = None
    monthly_debt_payment_rub: int | None = Field(default=None, strict=True, ge=0, le=MAX_RUB)
    tax_debt_rub: int | None = Field(default=None, strict=True, ge=0, le=MAX_RUB)
    legal_proceedings: StrictBool | None = None
    obligations_note: StrictStr | None = Field(default=None, max_length=1000)
    representative_name: StrictStr | None = Field(default=None, max_length=100)
    representative_authority_confirmed: StrictBool | None = None
    beneficial_owners_confirmed: StrictBool | None = None
    accuracy_confirmed: StrictBool | None = None

    _trim = field_validator('actual_address', 'actual_activity', 'obligations_note', 'representative_name')(blank_to_none)


class AnswersPatch(StrictModel):
    version: int = Field(ge=1, strict=True)
    current_stage: int = Field(ge=1, le=6, strict=True)
    answers: AnswersInput = Field(default_factory=AnswersInput)


class SubmissionConsent(StrictModel):
    code: StrictStr = Field(max_length=40)
    version: StrictStr = Field(max_length=80)
    accepted: StrictBool


class SubmitInput(StrictModel):
    version: int = Field(ge=1, strict=True)
    consents: list[SubmissionConsent] = Field(default_factory=list, max_length=10)


class CancelInput(StrictModel):
    version: int = Field(ge=1, strict=True)
    reason: StrictStr

    @field_validator('reason')
    @classmethod
    def trimmed_reason(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 2000:
            raise ValueError('Укажите причину: от 1 до 2000 символов')
        return value
