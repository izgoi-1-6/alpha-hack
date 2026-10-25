from pydantic import Field, field_validator
from ..schemas import StrictModel
from . import catalog


def within_policy_maximum(value: int | None) -> int | None:
    """An amount up to the policy maximum (the amount slider's), read at validation time: the need and the
    questionnaire share it, and each product's own bounds are checked against it at submission (R1)."""
    maximum = catalog.config().amount_slider['max_rub']
    if value is not None and value > maximum:
        raise ValueError(f'Сумма не больше {maximum:,} ₽'.replace(',', ' '))
    return value


class NeedInput(StrictModel):
    """The need is the amount alone: purpose, term and collateral are chosen in the questionnaire within the chosen
    product's bounds. Any whole amount from 1 RUB up to the slider maximum is compared (a product may not take it)."""
    requested_amount_rub: int = Field(strict=True, gt=0)

    _maximum = field_validator('requested_amount_rub')(within_policy_maximum)
