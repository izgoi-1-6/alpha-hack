"""Checks on the policy file alone, and the amount slider against the products it must reach. Sections arrive with
their JSON types already checked (loader.shaped)."""
from ..documents.models import DOCUMENT_TYPES
from .model import Problems
from .rules import (COLLATERAL_MODES, ENTITY_TYPES, OKVED_RULE, PAYMENT_MODELS, RATE_CERTAINTIES, REGION_STEPS, is_count,
                    shown, text_present)

REQUIRED_DEFAULTS = ('low_risk_revenue_multiple', 'medium_risk_revenue_multiple', 'medium_risk_cap_rub',
                     'collateral_ltv_bps', 'priority')
# Fallbacks for catalog nulls: optional (a null without one is reported on the item), positive integers when present.
FALLBACK_DEFAULTS = ('amount_min_rub', 'amount_max_rub_if_null', 'term_min_months', 'term_max_months')
PRODUCT_SETTINGS = ('amount_min_rub', 'amount_max_rub', 'term_min_months', 'term_max_months', 'collateral_mode', 'priority')
# The secured final approval caps the amount by the verified value on the accepted valuation (officer.policy).
VALUATION = 'COLLATERAL_VALUATION'


def check_count(value, path: str, problems: Problems, *, positive: bool = True) -> None:
    if not is_count(value, positive=positive):
        problems.add(path, f"must be {'a positive integer' if positive else 'an integer'}, got {shown(value)}")


def check_documents(defaults: dict, problems: Problems) -> None:
    """Known document types, each listed once; at least one base document; the collateral documents include the
    valuation."""
    seen = set()
    for key in ('base_documents', 'collateral_documents'):
        path, kinds = f'policy.defaults.{key}', defaults.get(key)
        if kinds is None:
            kinds = []
        if not isinstance(kinds, list):
            problems.add(path, 'must be a list of document types')
            continue
        for index, kind in enumerate(kinds):
            if not isinstance(kind, str) or kind not in DOCUMENT_TYPES:
                problems.add(f'{path}[{index}]', f'unknown document type {kind!r}')
                continue
            if kind in seen:
                problems.add(f'{path}[{index}]', f'duplicate document type {kind!r}')
            seen.add(kind)
        if key == 'base_documents' and not kinds:
            problems.add(path, 'at least one document type is required')
        if key == 'collateral_documents' and VALUATION not in kinds:
            problems.add(path, f'must include {VALUATION}, whose verified value bounds a secured final approval')


def check_policy(policy: dict, enums: dict, problems: Problems) -> None:
    if not text_present(policy.get('rules_version')):
        problems.add('policy.rules_version', 'missing')
    mapping = policy.get('entity_types', {})
    for name in enums.get('entity_types', ()):
        if name not in mapping:
            problems.add('policy.entity_types', f'no mapping for {name!r}')
    for name, value in mapping.items():
        if value not in ENTITY_TYPES:
            problems.add(f'policy.entity_types.{name}', f'unknown entity type {value!r}')
    kinds = policy.get('applyable_kinds', [])
    if not kinds:
        problems.add('policy.applyable_kinds', 'at least one kind is required')
    for index, kind in enumerate(kinds):
        if kind not in enums.get('kind', ()) or kind == 'overlay':
            problems.add(f'policy.applyable_kinds[{index}]', f'unknown kind {kind!r}')
    defaults = policy.get('defaults', {})
    for key in REQUIRED_DEFAULTS:
        if key not in defaults:
            problems.add(f'policy.defaults.{key}', 'missing')
        else:
            check_count(defaults[key], f'policy.defaults.{key}', problems, positive=key != 'priority')
    for key in FALLBACK_DEFAULTS:
        if defaults.get(key) is not None:
            check_count(defaults[key], f'policy.defaults.{key}', problems)
    check_documents(defaults, problems)
    for instrument, model in policy.get('payment_models', {}).items():
        if model not in PAYMENT_MODELS:
            problems.add(f'policy.payment_models.{instrument}', f'unknown payment model {model!r}')
    if not is_count(policy.get('payment_estimate_term_months')):
        problems.add('policy.payment_estimate_term_months', 'must be a positive integer')
    for product_id, settings in policy.get('products', {}).items():
        for key, value in settings.items():
            path = f'policy.products.{product_id}.{key}'
            if key not in PRODUCT_SETTINGS:
                problems.add(path, 'unknown setting')
            elif key == 'collateral_mode':
                if value not in COLLATERAL_MODES:
                    problems.add(path, f'unknown value {value!r}')
            else:
                check_count(value, path, problems, positive=key != 'priority')
    ranking = policy.get('ranking', {})
    for table, keys in (('collateral_burden', COLLATERAL_MODES), ('rate_certainty', RATE_CERTAINTIES)):
        for key in keys:
            if not is_count(ranking.get(table, {}).get(key), positive=False):
                problems.add(f'policy.ranking.{table}', f'missing {key!r}')
    rule = policy.get('okved_rule', {})
    for key, supported in OKVED_RULE.items():
        if rule.get(key) != supported:
            problems.add(f'policy.okved_rule.{key}', f'unsupported value {rule.get(key)!r}')
    for index, step in enumerate(policy.get('region_normalization', [])):
        if not isinstance(step, str) or step not in REGION_STEPS:
            problems.add(f'policy.region_normalization[{index}]', f'unsupported step {step!r}')


def check_slider(slider: dict, products: list[dict], problems: Problems) -> None:
    """A log-scale slider whose snapping bands land exactly on its bounds, default, presets and every product minimum."""
    low, high, bands = slider.get('min_rub'), slider.get('max_rub'), slider.get('snap')
    if slider.get('scale') != 'log':
        problems.add('policy.amount_slider.scale', f"unsupported value {slider.get('scale')!r}")
    if not (is_count(low) and is_count(high) and low < high):
        problems.add('policy.amount_slider', 'min_rub and max_rub must be positive integers, min below max')
        return
    if not isinstance(bands, list) or not bands or not all(isinstance(band, dict) for band in bands):
        problems.add('policy.amount_slider.snap', 'bands need ascending up_to_rub and positive step_rub')
        return
    edges = [band.get('up_to_rub') for band in bands]
    if not all(is_count(edge) for edge in edges) or edges != sorted(set(edges)) \
            or not all(is_count(band.get('step_rub')) for band in bands):
        problems.add('policy.amount_slider.snap', 'bands need ascending up_to_rub and positive step_rub')
        return
    if edges[-1] != high:
        problems.add('policy.amount_slider.snap', f'the last band must end at max_rub {high}')

    def on_grid(value: int) -> bool:
        band = next((band for band in bands if value <= band['up_to_rub']), None)
        return band is not None and value % band['step_rub'] == 0
    presets = slider.get('presets_rub', [])
    if not isinstance(presets, list):
        problems.add('policy.amount_slider.presets_rub', 'must be a list of amounts')
        presets = []
    values = [('min_rub', low), ('default_rub', slider.get('default_rub'))]
    values += [(f'presets_rub[{index}]', preset) for index, preset in enumerate(presets)]
    for key, value in values:
        if not is_count(value) or not low <= value <= high:
            problems.add(f'policy.amount_slider.{key}', f'{shown(value)} is outside {low}–{high}')
        elif not on_grid(value):
            problems.add(f'policy.amount_slider.{key}', f'{value} does not land on a slider step')
    for product in products:
        minimum = product['amount_min_rub']
        if not is_count(minimum):
            continue  # an invalid minimum is reported on its catalog item
        if not low <= minimum <= high:
            problems.add('policy.amount_slider', f"product minimum {minimum} of {product['id']} is outside {low}–{high}")
        elif not on_grid(minimum):
            problems.add('policy.amount_slider', f"product minimum {minimum} of {product['id']} does not land on a slider step")
