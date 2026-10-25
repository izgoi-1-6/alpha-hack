"""Independent expectations for the application scoring tests.

Nothing here imports application code. The factor points, risk bands, scored-limit formulas and R6-R11 order are
transcribed from the spec ("Scoring and state machine", "Product policy and recommendations"); product bounds come
from the policy JSON via recommendation_oracle (a reader, not a calculator). The arithmetic deliberately differs from
the implementation: exact fractions instead of integer cross-multiplication, and calendar stepping instead of a month
formula, so a shared mistake cannot make both agree.
"""
import calendar
from datetime import date
from fractions import Fraction
from recommendation_oracle import FIXTURES, PRODUCTS

# Spec constants stated literally ("low=min(ceiling,3R), medium=min(ceiling,1m,R)", "floor(value*7000/10000)").
LOW_MULTIPLE = 3
MEDIUM_MULTIPLE = 1
MEDIUM_CAP_RUB = 1_000_000
LTV = Fraction(7000, 10000)
HISTORY_POINTS = {'clean': 25, 'minor_closed': 10, 'serious': 0}
BY_INN = {fixture['inn']: fixture for fixture in FIXTURES.values()}


def add_months(start: date, months: int) -> date:
    year, index = divmod(start.month - 1 + months, 12)
    year += start.year
    last_day = calendar.monthrange(year, index + 1)[1]
    return date(year, index + 1, min(start.day, last_day))


def completed_months(start: date, end: date) -> int:
    """Whole calendar months from start to end, counted by stepping one month at a time."""
    months = 0
    while add_months(start, months + 1) <= end:
        months += 1
    return months


def age_points(months: int) -> int:
    return 20 if months >= 24 else 10 if months >= 6 else 0


def growth_points(revenue: int, previous: int) -> int:
    growth = Fraction(revenue - previous, previous)
    return 25 if growth > Fraction(1, 10) else 15 if growth >= Fraction(-1, 10) else 0


def burden_points(debt: int, revenue: int) -> int:
    burden = Fraction(debt, revenue)
    return 30 if burden <= Fraction(3, 10) else 15 if burden <= Fraction(1, 2) else 0


def score(months: int, revenue: int, previous: int, debt: int, history: str) -> int:
    return age_points(months) + growth_points(revenue, previous) + burden_points(debt, revenue) + HISTORY_POINTS[history]


def risk(total: int) -> str:
    return 'low' if total >= 75 else 'medium' if total >= 50 else 'high'


def scored_limit(product_id: str, band: str, revenue: int, declared_value: int | None = None) -> int | None:
    product = PRODUCTS[product_id]
    if band == 'high':
        return None
    if band == 'low':
        limit = min(product['amount_max_rub'], LOW_MULTIPLE * revenue)
    else:
        limit = min(product['amount_max_rub'], MEDIUM_CAP_RUB, MEDIUM_MULTIPLE * revenue)
    if product['collateral_required']:
        limit = min(limit, int(declared_value * LTV))  # positive values: int() truncation is the floor
    return limit


def outcome(product_id: str, total: int, limit: int | None, requested: int) -> tuple[str, str, int | None]:
    """(rule, status, preapproved amount) for a computable case without review flags: R6, R7, then R8-R11."""
    if total < 50:
        return 'R6', 'REJECTED', None
    if limit < PRODUCTS[product_id]['amount_min_rub']:
        return 'R7', 'REJECTED', None
    if risk(total) == 'low':
        return ('R8', 'PREAPPROVED', requested) if requested <= limit else ('R9', 'PREAPPROVED', limit)
    return ('R10', 'MANUAL_REVIEW', None) if requested <= limit else ('R11', 'MANUAL_REVIEW', None)
