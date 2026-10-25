"""Independent reading of the product configuration for the tests.

Nothing here imports application code. It reads `data/credit_catalog.json` and `data/demo-policy.json` straight from
disk and derives each card product's effective terms by the plan's rules, in its own way:

- a value is the policy's per-product override if one exists, else the catalog's value, else the policy default;
- rates come from the key-rate formula (or the stated percent) in exact Fraction arithmetic;
- a deny entry counts only when its text starts with a two-digit OKVED class or a class range (string slicing, not a
  regular expression), so free text such as «кроме ОКВЭД 55, 56» never bans anything;
- regions compare after casefolding, ё→е and collapsing spaces.

The literal golden table in test_products_config.py anchors this reading, so the oracle and the production loader
can only agree by both matching hand-written values.
"""
import json
from fractions import Fraction
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / 'data'
CATALOG_PATH = DATA / 'credit_catalog.json'
POLICY_PATH = DATA / 'demo-policy.json'
CATALOG = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
POLICY = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
ITEMS = {item['id']: item for item in CATALOG['items']}
CARD_IDS = [item['id'] for item in CATALOG['items'] if item['kind'] in ('product', 'gov_program') and item['display']['as'] == 'card']
OVERLAY_IDS = [item['id'] for item in CATALOG['items'] if item['kind'] == 'overlay']
KEY_RATE = Fraction(str(CATALOG['params']['key_rate']['value_percent']))


def exact(value) -> Fraction:
    """A JSON number as the exact decimal it was written as (23.5 -> 47/2)."""
    return Fraction(str(value))


def formula_rate(formula: str) -> Fraction:
    text = formula.replace(' ', '')
    if text == 'KEY_RATE':
        return KEY_RATE
    if text.startswith('KEY_RATE+'):
        return KEY_RATE + Fraction(text[len('KEY_RATE+'):])
    if text.startswith('KEY_RATE-'):
        return KEY_RATE - Fraction(text[len('KEY_RATE-'):])
    return Fraction(text)


def okved_classes(entries: list[str]) -> set[int]:
    """Two-digit classes named by entries that start with `NN` or `NN–NN` (en dash or hyphen)."""
    classes = set()
    for entry in entries:
        head = entry.strip()
        if len(head) < 2 or not head[:2].isdigit() or (len(head) > 2 and head[2].isdigit()):
            continue
        start = end = int(head[:2])
        rest = head[2:].lstrip()
        if rest[:1] in ('–', '-'):
            tail = rest[1:].lstrip()
            if len(tail) >= 2 and tail[:2].isdigit() and (len(tail) == 2 or not tail[2].isdigit()):
                end = int(tail[:2])
        classes.update(range(start, end + 1))
    return classes


def unparsed_okved(entries: list[str]) -> list[str]:
    return [entry for entry in entries if not okved_classes([entry])]


def region_key(text: str) -> str:
    return ' '.join(text.casefold().replace('ё', 'е').split())


def effective(product_id: str) -> dict:
    """The effective terms of one card product."""
    item = ITEMS[product_id]
    defaults, override = POLICY['defaults'], POLICY['products'].get(product_id, {})

    def pick(policy_key: str, catalog_value, default_key: str | None):
        if policy_key in override:
            return override[policy_key]
        if catalog_value is not None:
            return catalog_value
        return defaults[default_key] if default_key else None

    amount_min = pick('amount_min_rub', item['amount']['min'], 'amount_min_rub')
    amount_max = pick('amount_max_rub', item['amount']['max'], 'amount_max_rub_if_null')
    if item['term']['unlimited']:
        term_min = term_max = None
    else:
        term_min = pick('term_min_months', item['term']['min_months'], 'term_min_months')
        term_max = pick('term_max_months', item['term']['max_months'], 'term_max_months')
    required = item['collateral']['required']
    mode = override.get('collateral_mode') or {True: 'required', False: 'none'}[required]
    period = item['rate']['periods'][0]
    if item['rate']['type'] == 'undisclosed':
        bps, certainty, preferential = None, 'undisclosed', None
    else:
        rate = formula_rate(period['rate_formula']) if period['rate_formula'] else exact(period['rate_percent'])
        assert (rate * 100).denominator == 1, (product_id, rate)
        bps = int(rate * 100)
        to_month = period['to_month']
        preferential = to_month if to_month is not None and (term_max is None or to_month < term_max) else None
        certainty = 'preferential' if preferential else 'full'
    unsecured = item['amount'].get('max_unsecured')
    cap = 0 if mode == 'required' else unsecured if unsecured is not None else amount_max
    eligibility = item['eligibility']
    return {
        'id': product_id, 'kind': item['kind'], 'instrument_type': item['instrument_type'],
        'purposes': list(item['purposes']),
        'entity_types': [POLICY['entity_types'][name] for name in eligibility['entity_types']],
        'amount_min_rub': amount_min, 'amount_max_rub': amount_max, 'unsecured_cap_rub': cap,
        'term_min_months': term_min, 'term_max_months': term_max,
        'term_max_months_by_purpose': dict(item['term'].get('max_months_by_purpose') or {}),
        'collateral_mode': mode, 'annual_rate_bps': bps, 'rate_certainty': certainty,
        'rate_preferential_months': preferential,
        'payment_model': POLICY['payment_models'][item['instrument_type']],
        'priority': override.get('priority', defaults['priority']),
        'msp_registry_required': eligibility['msp_registry_required'],
        'regions': {region_key(region) for region in eligibility['regions_allow']},
        'okved_denied': okved_classes(eligibility['okved_deny_main']),
        'low_multiple': defaults['low_risk_revenue_multiple'], 'medium_multiple': defaults['medium_risk_revenue_multiple'],
        'medium_cap_rub': defaults['medium_risk_cap_rub'], 'ltv': Fraction(defaults['collateral_ltv_bps'], 10000),
        'open': item['status'] == 'active' and item['limit_status'] == 'open',
    }


PRODUCTS = {product_id: effective(product_id) for product_id in CARD_IDS}
