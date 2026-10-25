"""`load_config`: read both files, check their shapes, run every rule, stamp the versions and return the runtime model.

Malformed input never raises anything but ConfigError: a section of the wrong JSON type is reported and read as empty,
an item without an id or a valid display is reported and skipped, and a structurally broken item is reported by
ItemBuilder.guarded.
"""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from .items import ItemBuilder
from .model import ConfigError, Problems, ProductConfig
from .policy import check_policy, check_slider
from .rules import DISPLAY_MODES, is_number, shown, text_present

CATALOG_SHAPES = {'params': dict, 'enums': dict, 'items': list}
POLICY_SHAPES = {'entity_types': dict, 'applyable_kinds': list, 'defaults': dict, 'payment_models': dict,
                 'products': dict, 'ranking': dict, 'amount_slider': dict, 'okved_rule': dict, 'overlay_badges': dict,
                 'region_normalization': list}


def read_json(path, role: str, problems: Problems) -> tuple[bytes | None, dict | None]:
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        problems.add(role, f'cannot read {path}: {error.strerror}')
        return None, None
    try:
        data = json.loads(raw.decode('utf-8'), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        problems.add(role, f'invalid JSON in {path}: {error}')
        return raw, None
    if not isinstance(data, dict):
        problems.add(role, 'the file must hold a JSON object')
        return raw, None
    return raw, data


def stamp(version, raw: bytes) -> str:
    """`version+sha8`: any edit of the file, even without a version bump, gives a new stamp."""
    return f'{version}+{hashlib.sha256(raw).hexdigest()[:8]}'


def shaped(data: dict, shapes: dict, prefix: str, problems: Problems) -> dict:
    """A copy whose known sections have their JSON types; a mistyped section is reported and read as empty."""
    result = dict(data)
    for key, kind in shapes.items():
        if key in result and not isinstance(result[key], kind):
            problems.add(f'{prefix}{key}', 'must be an object' if kind is dict else 'must be a list')
            result[key] = kind()
        result.setdefault(key, kind())
    return result


def entries_of(section: dict, path: str, kind: type, problems: Problems) -> dict:
    """The entries of an object section that have the expected type; the others are reported and dropped."""
    kept = {}
    for key, value in section.items():
        if isinstance(value, kind):
            kept[key] = value
        else:
            problems.add(f'{path}.{key}', 'must be an object' if kind is dict else 'must be a list')
    return kept


def shaped_files(catalog: dict, policy: dict, problems: Problems) -> tuple[dict, dict]:
    for key in ('catalog_version', 'enums', 'items'):
        if key not in catalog:
            problems.add(key, 'missing')
    if 'catalog_version' in catalog and not text_present(catalog['catalog_version']):
        problems.add('catalog_version', 'must be a non-empty text')
    catalog = shaped(catalog, CATALOG_SHAPES, '', problems)
    catalog['enums'] = entries_of(catalog['enums'], 'enums', list, problems)
    for key, values in list(catalog['enums'].items()):
        if not all(isinstance(value, str) for value in values):
            problems.add(f'enums.{key}', 'must be a list of texts')
            catalog['enums'][key] = [value for value in values if isinstance(value, str)]
    policy = shaped(policy, POLICY_SHAPES, 'policy.', problems)
    for key in ('products', 'overlay_badges', 'ranking'):
        policy[key] = entries_of(policy[key], f'policy.{key}', dict, problems)
    return catalog, policy


def key_rate_of(catalog: dict, problems: Problems) -> Decimal | None:
    source = catalog['params'].get('key_rate')
    if source is None:
        problems.add('params.key_rate', 'missing')
        return None
    if not isinstance(source, dict):
        problems.add('params.key_rate', 'must be an object')
        return None
    percent = source.get('value_percent')
    if percent is None:
        problems.add('params.key_rate.value_percent', 'missing')
        return None
    if not is_number(percent) or percent < 0:
        problems.add('params.key_rate.value_percent', f'must be a number, got {shown(percent)}')
        return None
    rate = Decimal(percent)
    if rate * 100 != (rate * 100).to_integral_value():
        problems.add('params.key_rate.value_percent', f'{percent} is not a whole number of basis points')
    for key in ('effective_from', 'next_review', 'source_url'):
        if source.get(key) is not None and not isinstance(source[key], str):
            problems.add(f'params.key_rate.{key}', f'must be a text or null, got {shown(source[key])}')
    return rate


def labelled_items(catalog: dict, problems: Problems) -> list[tuple[dict, str, str | None]]:
    """(item, error-path label, display mode) for each object item with an id: `items[<id>]`, or `items[<index>]` where
    the id repeats. The mode is None when the display is malformed (reported)."""
    labelled, seen = [], set()
    for index, entry in enumerate(catalog['items']):
        if not isinstance(entry, dict):
            problems.add(f'items[{index}]', 'must be an object')
            continue
        item_id = entry.get('id')
        if not text_present(item_id):
            problems.add(f'items[{index}].id', 'missing')
            continue
        if item_id in seen:
            problems.add(f'items[{index}].id', f'duplicate id {item_id!r}')
        label = f'items[{index}]' if item_id in seen else f'items[{item_id}]'
        seen.add(item_id)
        display, mode = entry.get('display'), None
        if not isinstance(display, dict):
            problems.add(f'{label}.display', 'must be an object')
        elif display.get('as') not in DISPLAY_MODES:
            problems.add(f'{label}.display.as', f"unknown value {display.get('as')!r}")
        else:
            mode = display['as']
        labelled.append((entry, label, mode))
    return labelled


def build(catalog: dict, policy: dict, problems: Problems, key_rate: Decimal | None) -> tuple[list[dict], list[dict]]:
    labelled = labelled_items(catalog, problems)
    kinds = policy['applyable_kinds']
    cards = [(entry, label) for entry, label, mode in labelled if entry.get('kind') in kinds and mode == 'card']
    if not cards:
        problems.add('items', "no card product of the policy's applyable kinds")
    overlay_items = {entry['id']: (entry, label) for entry, label, mode in labelled
                     if entry.get('kind') == 'overlay' and mode is not None}
    card_ids = [entry['id'] for entry, _ in cards]
    builder = ItemBuilder(catalog, policy, problems, key_rate=key_rate, overlay_items=overlay_items, card_ids=card_ids)
    for entry, label, _ in labelled:
        builder.guarded(label, lambda: builder.check_common(entry, label))
    products = [product for entry, label in cards if (product := builder.guarded(label, lambda: builder.product(entry, label)))]
    overlays = [overlay for entry, label in overlay_items.values()
                if (overlay := builder.guarded(label, lambda: builder.overlay(entry, label)))]
    for product_id in policy['products']:
        if product_id not in card_ids:
            problems.add(f'policy.products.{product_id}', 'unknown product')
    for overlay_id in policy['overlay_badges']:
        if overlay_id not in overlay_items:
            problems.add(f'policy.overlay_badges.{overlay_id}', 'unknown overlay')
    for instrument in sorted(builder.missing_models):
        problems.add(f'policy.payment_models.{instrument}', 'missing')
    return products, overlays


def load_config(catalog_path, policy_path) -> ProductConfig:
    """The validated runtime model, or ConfigError with every problem and its path."""
    problems = Problems()
    catalog_bytes, catalog = read_json(catalog_path, 'catalog', problems)
    policy_bytes, policy = read_json(policy_path, 'policy', problems)
    if catalog is None or policy is None:
        raise ConfigError(problems)
    catalog, policy = shaped_files(catalog, policy, problems)
    key_rate = key_rate_of(catalog, problems)
    check_policy(policy, catalog['enums'], problems)
    products, overlays = build(catalog, policy, problems, key_rate)
    slider = policy['amount_slider']
    check_slider(slider, products, problems)
    if problems:
        raise ConfigError(problems)
    source = catalog['params']['key_rate']
    return ProductConfig(
        catalog_version=stamp(catalog['catalog_version'], catalog_bytes), rules_version=stamp(policy['rules_version'], policy_bytes),
        key_rate={'value_bps': int(key_rate * 100), 'effective_from': source.get('effective_from'),
                  'next_review': source.get('next_review'), 'source_url': source.get('source_url')},
        amount_slider={key: slider[key] for key in ('scale', 'min_rub', 'max_rub', 'default_rub')}
        | {'snap': [dict(band) for band in slider['snap']], 'presets_rub': list(slider.get('presets_rub', []))},
        products=tuple(products), overlays=tuple(overlays), ranking=policy['ranking'],
        payment_estimate_term_months=policy['payment_estimate_term_months'],
        region_normalization=tuple(policy['region_normalization']))
