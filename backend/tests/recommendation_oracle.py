"""Independent reference data and arithmetic for the recommendation tests.

Nothing here imports application code. Policy numbers are read straight from the canonical JSON files
and the arithmetic uses exact rational/integer math, not the Decimal implementation under test, so a
test can compare production output against an oracle that shares no code with it.
"""
import json
from fractions import Fraction
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / 'data'
PRODUCTS = {p['id']: p for p in json.loads((DATA / 'demo-products.json').read_text())['products']}
_COMPANIES = json.loads((DATA / 'demo-companies.json').read_text())
FIXTURES = {c['fixture_id']: c for c in _COMPANIES['companies']}
HELD_OUT = _COMPANIES['held_out_tasks']


def annuity_rub(amount: int, annual_bps: int, months: int) -> int:
    """A*r/(1-(1+r)^-n) with r=bps/120000, rounded half up, in exact rational arithmetic."""
    rate = Fraction(annual_bps, 120000)
    exact = amount * rate / (1 - (1 + rate) ** -months)
    return int(exact + Fraction(1, 2))  # exact > 0, so truncating x+1/2 is round-half-up


def full_utilization_interest_rub(amount: int, annual_bps: int) -> int:
    """ceil(A*bps/120000) by integer arithmetic."""
    return -(-amount * annual_bps // 120000)


def collateral_cap_rub(declared_value: int, ltv_bps: int) -> int:
    return declared_value * ltv_bps // 10000
