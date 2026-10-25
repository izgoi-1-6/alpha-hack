"""`load_config`: read both files, run every rule, stamp the versions and return the runtime model."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from .items import ItemBuilder
from .model import ConfigError, Problems, ProductConfig
from .policy import check_policy, check_slider


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


def key_rate_of(catalog: dict, problems: Problems) -> Decimal | None:
    percent = ((catalog.get('params') or {}).get('key_rate') or {}).get('value_percent')
    if percent is None:
        problems.add('params.key_rate.value_percent', 'missing')
        return None
    rate = Decimal(percent)
    if rate * 100 != (rate * 100).to_integral_value():
        problems.add('params.key_rate.value_percent', f'{percent} is not a whole number of basis points')
    return rate


def item_labels(items: list[dict], problems: Problems) -> list[str]:
    """`items[<id>]` for error paths, `items[<index>]` where the id is repeated or missing."""
    labels, seen = [], set()
    for index, entry in enumerate(items):
        item_id = entry.get('id')
        if item_id in seen:
            problems.add(f'items[{index}].id', f'duplicate id {item_id!r}')
        labels.append(f'items[{item_id}]' if item_id not in seen and isinstance(item_id, str) else f'items[{index}]')
        seen.add(item_id)
    return labels


def build(catalog: dict, policy: dict, problems: Problems, key_rate: Decimal | None) -> tuple[list[dict], list[dict]]:
    items = [entry for entry in catalog.get('items') or [] if isinstance(entry, dict)]
    labelled = list(zip(items, item_labels(items, problems)))
    kinds = policy.get('applyable_kinds') or []
    cards = [(entry, label) for entry, label in labelled
             if entry.get('kind') in kinds and (entry.get('display') or {}).get('as') == 'card']
    overlay_items = {entry['id']: (entry, label) for entry, label in labelled if entry.get('kind') == 'overlay'}
    card_ids = [entry['id'] for entry, _ in cards]
    builder = ItemBuilder(catalog, policy, problems, key_rate=key_rate, overlay_items=overlay_items, card_ids=card_ids)
    for entry, label in labelled:
        builder.guarded(label, lambda: builder.check_common(entry, label))
    products = [product for entry, label in cards if (product := builder.guarded(label, lambda: builder.product(entry, label)))]
    overlays = [overlay for entry, label in overlay_items.values()
                if (overlay := builder.guarded(label, lambda: builder.overlay(entry, label)))]
    for product_id in policy.get('products') or {}:
        if product_id not in card_ids:
            problems.add(f'policy.products.{product_id}', 'unknown product')
    for overlay_id in policy.get('overlay_badges') or {}:
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
    for key in ('catalog_version', 'enums', 'items'):
        if key not in catalog:
            problems.add(key, 'missing')
    key_rate = key_rate_of(catalog, problems)
    check_policy(policy, catalog.get('enums') or {}, problems)
    products, overlays = build(catalog, policy, problems, key_rate)
    slider = policy.get('amount_slider') or {}
    check_slider(slider, products, problems)
    if problems:
        raise ConfigError(problems)
    source = catalog['params']['key_rate']
    return ProductConfig(
        catalog_version=stamp(catalog['catalog_version'], catalog_bytes), rules_version=stamp(policy['rules_version'], policy_bytes),
        key_rate={'value_bps': int(key_rate * 100), 'effective_from': source.get('effective_from'),
                  'next_review': source.get('next_review'), 'source_url': source.get('source_url')},
        amount_slider={key: slider[key] for key in ('scale', 'min_rub', 'max_rub', 'default_rub')}
        | {'snap': [dict(band) for band in slider['snap']], 'presets_rub': list(slider.get('presets_rub') or [])},
        products=tuple(products), overlays=tuple(overlays), ranking=policy['ranking'],
        payment_estimate_term_months=policy['payment_estimate_term_months'],
        region_normalization=tuple(policy.get('region_normalization') or ()))
