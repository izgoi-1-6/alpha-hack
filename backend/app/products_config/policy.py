"""Checks on the policy file alone, and the amount slider against the products it must reach."""
from ..documents.models import DOCUMENT_TYPES
from .model import Problems
from .rules import COLLATERAL_MODES, ENTITY_TYPES, OKVED_RULE, PAYMENT_MODELS, RATE_CERTAINTIES, REGION_STEPS, is_count

REQUIRED_DEFAULTS = ('low_risk_revenue_multiple', 'medium_risk_revenue_multiple', 'medium_risk_cap_rub',
                     'collateral_ltv_bps', 'priority')
PRODUCT_SETTINGS = ('amount_min_rub', 'amount_max_rub', 'term_min_months', 'term_max_months', 'collateral_mode', 'priority')


def check_policy(policy: dict, enums: dict, problems: Problems) -> None:
    if not policy.get('rules_version'):
        problems.add('policy.rules_version', 'missing')
    mapping = policy.get('entity_types') or {}
    for name in enums.get('entity_types', ()):
        if name not in mapping:
            problems.add('policy.entity_types', f'no mapping for {name!r}')
    for name, value in mapping.items():
        if value not in ENTITY_TYPES:
            problems.add(f'policy.entity_types.{name}', f'unknown entity type {value!r}')
    for index, kind in enumerate(policy.get('applyable_kinds') or []):
        if kind not in enums.get('kind', ()) or kind == 'overlay':
            problems.add(f'policy.applyable_kinds[{index}]', f'unknown kind {kind!r}')
    defaults = policy.get('defaults') or {}
    for key in REQUIRED_DEFAULTS:
        if key not in defaults:
            problems.add(f'policy.defaults.{key}', 'missing')
        elif not is_count(defaults[key], positive=key != 'priority'):
            problems.add(f'policy.defaults.{key}', 'must be an integer' if key == 'priority' else 'must be a positive integer')
    for key in ('base_documents', 'collateral_documents'):
        for index, kind in enumerate(defaults.get(key) or []):
            if kind not in DOCUMENT_TYPES:
                problems.add(f'policy.defaults.{key}[{index}]', f'unknown document type {kind!r}')
    for instrument, model in (policy.get('payment_models') or {}).items():
        if model not in PAYMENT_MODELS:
            problems.add(f'policy.payment_models.{instrument}', f'unknown payment model {model!r}')
    if not is_count(policy.get('payment_estimate_term_months')):
        problems.add('policy.payment_estimate_term_months', 'must be a positive integer')
    for product_id, settings in (policy.get('products') or {}).items():
        for key, value in settings.items():
            path = f'policy.products.{product_id}.{key}'
            if key not in PRODUCT_SETTINGS:
                problems.add(path, 'unknown setting')
            elif key == 'collateral_mode' and value not in COLLATERAL_MODES:
                problems.add(path, f'unknown value {value!r}')
            elif key == 'priority' and not is_count(value, positive=False):
                problems.add(path, 'must be an integer')
            elif key not in ('collateral_mode', 'priority') and not is_count(value):
                problems.add(path, 'must be a positive integer')
    ranking = policy.get('ranking') or {}
    for table, keys in (('collateral_burden', COLLATERAL_MODES), ('rate_certainty', RATE_CERTAINTIES)):
        for key in keys:
            if not is_count((ranking.get(table) or {}).get(key), positive=False):
                problems.add(f'policy.ranking.{table}', f'missing {key!r}')
    rule = policy.get('okved_rule') or {}
    for key, supported in OKVED_RULE.items():
        if rule.get(key) != supported:
            problems.add(f'policy.okved_rule.{key}', f'unsupported value {rule.get(key)!r}')
    for index, step in enumerate(policy.get('region_normalization') or []):
        if step not in REGION_STEPS:
            problems.add(f'policy.region_normalization[{index}]', f'unsupported step {step!r}')


def check_slider(slider: dict, products: list[dict], problems: Problems) -> None:
    """A log-scale slider whose snapping bands land exactly on its bounds, default, presets and every product minimum."""
    low, high, bands = slider.get('min_rub'), slider.get('max_rub'), slider.get('snap') or []
    if slider.get('scale') != 'log':
        problems.add('policy.amount_slider.scale', f"unsupported value {slider.get('scale')!r}")
    if not (is_count(low) and is_count(high) and low < high):
        problems.add('policy.amount_slider', 'min_rub and max_rub must be positive integers, min below max')
        return
    edges = [band.get('up_to_rub') for band in bands]
    if not bands or not all(is_count(edge) for edge in edges) or edges != sorted(set(edges)) \
            or not all(is_count(band.get('step_rub')) for band in bands):
        problems.add('policy.amount_slider.snap', 'bands need ascending up_to_rub and positive step_rub')
        return
    if edges[-1] != high:
        problems.add('policy.amount_slider.snap', f'the last band must end at max_rub {high}')

    def on_grid(value: int) -> bool:
        band = next((band for band in bands if value <= band['up_to_rub']), None)
        return band is not None and value % band['step_rub'] == 0
    values = [('min_rub', low), ('default_rub', slider.get('default_rub'))]
    values += [(f'presets_rub[{index}]', preset) for index, preset in enumerate(slider.get('presets_rub') or [])]
    for key, value in values:
        if not is_count(value) or not low <= value <= high:
            problems.add(f'policy.amount_slider.{key}', f'{value} is outside {low}–{high}')
        elif not on_grid(value):
            problems.add(f'policy.amount_slider.{key}', f'{value} does not land on a slider step')
    for product in products:
        minimum = product['amount_min_rub']
        if not is_count(minimum):
            continue
        if not low <= minimum <= high:
            problems.add('policy.amount_slider', f"product minimum {minimum} of {product['id']} is outside {low}–{high}")
        elif not on_grid(minimum):
            problems.add('policy.amount_slider', f"product minimum {minimum} of {product['id']} does not land on a slider step")
