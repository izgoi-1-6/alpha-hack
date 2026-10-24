from typing import Literal
from pydantic import Field, StrictBool, model_validator
from ..schemas import StrictModel

class CollateralInput(StrictModel):
    status: Literal['unknown', 'none', 'declared']
    type: Literal['real_estate', 'vehicle', 'equipment', 'inventory', 'deposit'] | None = None
    declared_value_rub: int | None = Field(default=None, strict=True, gt=0, le=9_000_000_000_000_000)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    owner_confirmed: StrictBool | None = None
    encumbered: StrictBool | None = None

    @model_validator(mode='after')
    def declaration(self):
        if self.status == 'declared' and (not self.type or not self.declared_value_rub or not self.description or not self.description.strip()):
            raise ValueError('Для заявленного залога укажите тип, стоимость и описание')
        return self

class NeedInput(StrictModel):
    purpose: Literal['working_capital', 'business_development', 'investment', 'refinancing']
    funding_pattern: Literal['one_time', 'repeated']
    requested_amount_rub: int = Field(strict=True, gt=0, le=150_000_000)
    term_months: int = Field(strict=True, ge=1, le=120)
    collateral: CollateralInput | None = None
