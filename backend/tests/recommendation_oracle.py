"""Independent expectations for the recommendation tests.

Nothing here imports application code. Products are catalog_oracle's own reading of the raw catalog and policy
files, fixtures come straight from data/demo-companies.json, and the arithmetic is exact (Fraction and integer
ceiling), not the Decimal implementation under test. The rules are transcribed from the plan's binding changes:
machine-checkable eligibility only, failed → does_not_fit, unknown → needs_info, can_apply on the eligibility and
amount-range gates, the ranking key (status, shortfall, collateral burden, rate certainty, rate, priority, id) and the
overlay badge rule (applies_to + MSP registry + main OKVED not denied, with the policy's exemptions).
"""
import json
from fractions import Fraction
from catalog_oracle import DATA, ITEMS, OVERLAY_IDS, POLICY, PRODUCTS, okved_classes, region_key

FIXTURES = {company['fixture_id']: company for company in json.loads((DATA / 'demo-companies.json').read_text(encoding='utf-8'))['companies']}
CHECK_CODES = ['company_active', 'entity_type', 'msp_registry', 'region', 'okved', 'program_status', 'amount_min',
               'catalog_max', 'turnover', 'collateral', 'amount_capacity']
GATES = CHECK_CODES[:8]  # what must pass for can_apply
STATUS_ORDER = {'fits': 0, 'needs_info': 1, 'does_not_fit': 2}


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


def company_of(fixture: dict) -> dict:
    """The company row an onboarded fixture becomes (entity type from the INN length)."""
    return {'registry_status': fixture['registry_status'], 'entity_type': 'LLC' if len(fixture['inn']) == 10 else 'IP',
            'msp_registry': fixture['msp_registry'], 'region': fixture['region'], 'okved': fixture['okved']}


def main_class(okved: str | None) -> int | None:
    text = (okved or '').strip()
    return int(text[:2]) if len(text) >= 2 and text[:2].isdigit() else None


def indicative_limit(product: dict, revenue: int | None) -> int | None:
    """min(max, 3R, unsecured cap) for positive turnover; nothing for a product whose collateral is required (the
    need states no collateral) or for unknown/zero turnover."""
    if not revenue or revenue <= 0 or product['collateral_mode'] == 'required':
        return None
    return min(product['amount_max_rub'], product['low_multiple'] * revenue, product['unsecured_cap_rub'])


def checks(product: dict, company: dict, revenue: int | None, amount: int) -> dict:
    results = {'company_active': {'active': 'passed', 'unknown': 'unknown'}.get(company['registry_status'], 'failed'),
               'entity_type': 'passed' if company['entity_type'] in product['entity_types'] else 'failed'}
    if not product['msp_registry_required']:
        results['msp_registry'] = 'passed'
    else:
        results['msp_registry'] = {True: 'passed', False: 'failed', None: 'unknown'}[company['msp_registry']]
    if not product['regions']:
        results['region'] = 'passed'
    elif company['region'] is None:
        results['region'] = 'unknown'
    else:
        results['region'] = 'passed' if region_key(company['region']) in product['regions'] else 'failed'
    denied, okved = product['okved_denied'], main_class(company['okved'])
    results['okved'] = 'passed' if not denied else 'unknown' if okved is None else 'failed' if okved in denied else 'passed'
    results['program_status'] = 'passed' if product['open'] else 'failed'
    results['amount_min'] = 'passed' if amount >= product['amount_min_rub'] else 'failed'
    results['catalog_max'] = 'passed' if amount <= product['amount_max_rub'] else 'failed'
    results['turnover'] = 'passed' if revenue and revenue > 0 else 'unknown'
    results['collateral'] = 'unknown' if product['collateral_mode'] == 'required' else 'passed'
    limit = indicative_limit(product, revenue)
    results['amount_capacity'] = 'unknown' if limit is None else 'passed' if amount <= limit else 'failed'
    return results


def status_of(results: dict) -> str:
    values = set(results.values())
    return 'does_not_fit' if 'failed' in values else 'needs_info' if 'unknown' in values else 'fits'


def estimate_months(product: dict) -> int:
    months = POLICY['payment_estimate_term_months']
    return max(product['term_min_months'], min(product['term_max_months'], months))


def payment(product: dict, results: dict, limit: int | None, amount: int) -> int | None:
    """The indicative payment on min(request, limit), or None (inactive, a failed product condition, no payment
    model, an undisclosed rate, an unknown limit or an estimate below the product minimum)."""
    if results['company_active'] == 'failed' or any(results[code] == 'failed' for code in GATES[1:]):
        return None
    if product['payment_model'] == 'none' or product['annual_rate_bps'] is None or limit is None:
        return None
    base = min(amount, limit)
    if base < product['amount_min_rub']:
        return None
    if product['payment_model'] == 'annuity':
        return annuity_rub(base, product['annual_rate_bps'], estimate_months(product))
    return full_utilization_interest_rub(base, product['annual_rate_bps'])


def badges(product: dict, company: dict) -> list[str]:
    """Overlay ids shown on the card: listed in applies_to, MSP registry confirmed when required, main OKVED known and
    not denied unless the policy exempts the product."""
    shown = []
    for overlay_id in OVERLAY_IDS:
        overlay = ITEMS[overlay_id]
        eligibility = overlay['eligibility']
        if product['id'] not in overlay['display']['applies_to']:
            continue
        if eligibility['msp_registry_required'] and company['msp_registry'] is not True:
            continue
        exempt = POLICY['overlay_badges'].get(overlay_id, {}).get('okved_exempt_products', [])
        denied = okved_classes(eligibility['okved_deny_main'])
        okved = main_class(company['okved'])
        if denied and product['id'] not in exempt and (okved is None or okved in denied):
            continue
        shown.append(overlay_id)
    return shown


def expected(company: dict, revenue: int | None, amount: int) -> list[dict]:
    """The ranked items as the oracle sees them: id, status, can_apply, limit, payment and badges."""
    rows = []
    for product in PRODUCTS.values():
        results = checks(product, company, revenue, amount)
        limit = indicative_limit(product, revenue)
        status = status_of(results)
        shortfall = amount if limit is None else max(0, amount - limit)
        key = (STATUS_ORDER[status], shortfall, POLICY['ranking']['collateral_burden'][product['collateral_mode']],
               POLICY['ranking']['rate_certainty'][product['rate_certainty']], product['annual_rate_bps'] or 0,
               product['priority'], product['id'])
        rows.append((key, {'product_id': product['id'], 'status': status,
                           'can_apply': all(results[code] == 'passed' for code in GATES),
                           'indicative_limit_rub': limit, 'estimated_payment_rub': payment(product, results, limit, amount),
                           'badges': badges(product, company), 'checks': results}))
    return [row for _, row in sorted(rows, key=lambda pair: pair[0])]
