from pydantic import Field, field_validator
from ..schemas import StrictModel
from . import catalog


class NeedInput(StrictModel):
    """The need is the amount alone: purpose, term and collateral are chosen in the questionnaire within the chosen
    product's bounds. Any whole amount from 1 RUB up to the slider maximum is compared (a product may not take it)."""
    requested_amount_rub: int = Field(strict=True, gt=0)

    @field_validator('requested_amount_rub')
    @classmethod
    def within_slider(cls, value: int) -> int:
        maximum = catalog.config().amount_slider['max_rub']
        if value > maximum:
            raise ValueError(f'Сумма не больше {maximum:,} ₽'.replace(',', ' '))
        return value
