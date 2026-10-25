"""The product configuration layer: loading, every validation rule, version stamps, the CLI and the effective terms.

Expected values are literal (the golden table below, transcribed from the plan's effective-terms table) and the
independent reading in catalog_oracle.py; neither uses the loader under test. Broken configurations are edited copies
of the shipped files in a temporary directory, loaded with `load_config` directly.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from app.products_config import ConfigError, configured_paths, load_config, normalize_region, okved_deny, parse_rate_formula
import catalog_oracle as oracle

BACKEND = Path(__file__).resolve().parents[1]
SOURCE_CATALOG = json.loads(oracle.CATALOG_PATH.read_text(encoding='utf-8'))
SOURCE_POLICY = json.loads(oracle.POLICY_PATH.read_text(encoding='utf-8'))
N = None  # no term / no rate / no preferential period
# The plan's effective-terms table, literally: amount min/max, unsecured cap, term min/max, per-purpose term caps,
# collateral mode, annual rate (bps), rate certainty, preferential months, payment model, fields filled by the policy.
GOLDEN = {
    'alfa_term_loan_unsecured': (300_000, 30_000_000, 30_000_000, 12, 60, {}, 'none', 2350, 'full', N, 'annuity', []),
    'alfa_term_loan_secured': (500_000, 150_000_000, 0, 12, 120, {}, 'required', 2150, 'full', N, 'annuity', []),
    'alfa_revolving_line_unsecured': (300_000, 30_000_000, 30_000_000, N, N, {}, 'none', 2350, 'full', N,
                                      'interest_full_utilization', []),
    'alfa_revolving_line_secured': (500_000, 60_000_000, 0, 6, 60, {}, 'required', 2300, 'full', N,
                                    'interest_full_utilization', []),
    'alfa_nonrevolving_line_secured': (500_000, 60_000_000, 0, 6, 60, {}, 'required', 2200, 'full', N, 'annuity', []),
    'alfa_goscredit_zont': (300_000, 50_000_000, 50_000_000, 6, 60, {'working_capital': 36}, 'none', 2400, 'full', N,
                            'annuity', ['amount_min_rub', 'term_min_months']),
    'alfa_universal_limit': (300_000, 70_000_000, 20_000_000, 6, 120, {}, 'optional', N, 'undisclosed', N,
                             'interest_full_utilization', ['amount_min_rub', 'term_min_months']),
    'alfa_factoring': (300_000, 2_000_000_000, 2_000_000_000, 1, 12, {}, 'none', N, 'undisclosed', N, 'none',
                       ['amount_min_rub', 'amount_max_rub', 'term_min_months']),
    'psk_invest_subsidy': (25_000_000, 2_000_000_000, 2_000_000_000, 6, 120, {}, 'optional', 1050, 'full', N, 'annuity',
                           ['term_min_months', 'collateral_mode']),
    'psk_working_capital': (500_000, 500_000_000, 500_000_000, 6, 36, {}, 'optional', 1700, 'preferential', 12, 'annuity',
                            ['term_min_months', 'term_max_months', 'collateral_mode']),
    'psk_borderline': (300_000, 30_000_000, 30_000_000, 6, 36, {}, 'none', 1400, 'preferential', 12, 'annuity',
                       ['amount_min_rub', 'term_min_months', 'term_max_months']),
}
FIELDS = ('amount_min_rub', 'amount_max_rub', 'unsecured_cap_rub', 'term_min_months', 'term_max_months',
          'term_max_months_by_purpose', 'collateral_mode', 'annual_rate_bps', 'rate_certainty', 'rate_preferential_months',
          'payment_model', 'fallbacks')
GOSCREDIT_DENIED = ['05', '06', '07', '08', '09', '64', '65', '66', '92']


@pytest.fixture(scope='module')
def shipped():
    return load_config(oracle.CATALOG_PATH, oracle.POLICY_PATH)


def sha8(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def write_pair(tmp_path, catalog=None, policy=None) -> tuple[Path, Path]:
    """Edited copies; an unedited file is copied byte for byte, so its stamped hash stays the shipped one."""
    catalog_path, policy_path = tmp_path / 'catalog.json', tmp_path / 'policy.json'
    for path, data, source in ((catalog_path, catalog, oracle.CATALOG_PATH), (policy_path, policy, oracle.POLICY_PATH)):
        path.write_bytes(source.read_bytes() if data is None else json.dumps(data, ensure_ascii=False).encode('utf-8'))
    return catalog_path, policy_path


def errors_of(tmp_path, catalog=None, policy=None) -> list[str]:
    with pytest.raises(ConfigError) as caught:
        load_config(*write_pair(tmp_path, catalog, policy))
    assert caught.value.errors and str(caught.value) == '\n'.join(caught.value.errors)
    return caught.value.errors


def item(catalog: dict, item_id: str) -> dict:
    return next(entry for entry in catalog['items'] if entry['id'] == item_id)


def test_the_shipped_files_load_and_stamp_content_hashed_versions(shipped):
    assert SOURCE_CATALOG['schema_version'] == '3.2' and SOURCE_CATALOG['catalog_version'] == '2026-10-25.1'
    assert SOURCE_POLICY['rules_version'] == 'demo-rules-v2'
    assert shipped.catalog_version == f"2026-10-25.1+{sha8(oracle.CATALOG_PATH)}"
    assert shipped.rules_version == f"demo-rules-v2+{sha8(oracle.POLICY_PATH)}"
    assert [product['id'] for product in shipped.products] == list(GOLDEN)  # catalog order, the overlay excluded
    assert [overlay['id'] for overlay in shipped.overlays] == ['zont_corpmsp']
    assert all(product['applyable'] for product in shipped.products)
    assert shipped.key_rate == {'value_bps': 1400, 'effective_from': '2026-10-23', 'next_review': '2026-12-18',
                                'source_url': 'https://www.cbr.ru/press/keypr/'}


@pytest.mark.parametrize('product_id', list(GOLDEN))
def test_effective_terms_match_the_golden_table(shipped, product_id):
    product = shipped.product(product_id)
    assert tuple(product[field] for field in FIELDS) == GOLDEN[product_id]


@pytest.mark.parametrize('product_id', list(GOLDEN))
def test_the_independent_oracle_matches_the_golden_table(product_id):
    expected = dict(zip(FIELDS, GOLDEN[product_id]))
    expected.pop('fallbacks')
    assert {field: oracle.PRODUCTS[product_id][field] for field in expected} == expected


def test_product_facts_come_from_the_catalog_and_policy_defaults(shipped):
    for product in shipped.products:
        raw = oracle.ITEMS[product['id']]
        assert (product['name'], product['kind'], product['instrument_type'], product['purposes']) == \
               (raw['name'], raw['kind'], raw['instrument_type'], raw['purposes'])
        assert product['entity_types'] == ['IP', 'LLC']
        assert (product['low_risk_revenue_multiple'], product['medium_risk_revenue_multiple'], product['medium_risk_cap_rub'],
                product['collateral_ltv_bps']) == (3, 1, 1_000_000, 7000)
        assert product['base_documents'] == ['BANK_STATEMENT', 'FINANCIAL_REPORT']
        assert product['collateral_documents'] == ['COLLATERAL_OWNERSHIP', 'COLLATERAL_VALUATION']
        assert product['priority'] == oracle.PRODUCTS[product['id']]['priority']
        assert product['eligibility']['msp_registry_required'] is raw['eligibility']['msp_registry_required']
        assert product['display']['headline'] == raw['display']['headline']
        assert product['term_note'] == raw['term']['note']
    revolving = shipped.product('alfa_revolving_line_unsecured')
    assert (revolving['tranche_min_rub'], revolving['tranche_max_rub']) == (50_000, 30_000_000)
    assert revolving['term_note'] == 'Договор на 18 месяцев с автопродлением каждый год'
    assert shipped.product('psk_invest_subsidy')['rate_formula'] == 'KEY_RATE - 3.5'
    assert shipped.product('alfa_universal_limit')['amount_max_unsecured_rub'] == 20_000_000
    assert shipped.product('zont_corpmsp') is None and shipped.product('nope') is None


def test_every_card_product_has_its_explanation_texts(shipped):
    for product in shipped.products:
        display = product['display']
        assert display['summary'].strip() and display['best_for'].strip(), product['id']
        assert 3 <= len(display['features']) <= 5 and all(text.strip() for text in display['features']), product['id']
        assert not any(word in ' '.join([display['summary'], display['best_for'], *display['features']]).lower()
                       for word in ('демо', 'демонстрац', 'имитац')), product['id']


def test_okved_parse_sets_per_product(shipped):
    denied = {product['id']: product['eligibility']['okved_denied_classes'] for product in shipped.products}
    assert denied == {product_id: (GOSCREDIT_DENIED if product_id == 'alfa_goscredit_zont' else []) for product_id in GOLDEN}
    assert {'55', '56'}.isdisjoint(denied['alfa_goscredit_zont'])  # «кроме ОКВЭД 55, 56» never bans 55 or 56
    assert sorted(f'{n:02d}' for n in oracle.PRODUCTS['alfa_goscredit_zont']['okved_denied']) == GOSCREDIT_DENIED
    goscredit = shipped.product('alfa_goscredit_zont')
    assert {'kind': 'okved', 'text': 'производство и продажа подакцизных товаров (кроме ОКВЭД 55, 56)'} in goscredit['conditions_to_confirm']
    overlay = shipped.overlays[0]
    assert overlay['eligibility']['okved_denied_classes'] == ['47']
    assert overlay['okved_exempt_products'] == ['psk_borderline']


@pytest.mark.parametrize('entries,classes,unparsed', [
    (['47 — Торговля розничная (как основной ОКВЭД; допустим как дополнительный)'], ['47'], []),
    (['64–66 — банки', '92 — игорный бизнес'], ['64', '65', '66', '92'], []),
    (['05-09 добыча'], ['05', '06', '07', '08', '09'], []),
    (['  12 табак'], ['12'], []),
    (['производство и продажа подакцизных товаров (кроме ОКВЭД 55, 56)'], [], ['производство и продажа подакцизных товаров (кроме ОКВЭД 55, 56)']),
    (['470 — не класс', 'ОКВЭД 47', '4 — одна цифра'], [], ['470 — не класс', 'ОКВЭД 47', '4 — одна цифра']),
    (['64 — 66 банки'], ['64'], []),  # an em dash separates the description; it is never a range
    # A subclass names part of a class, so it is a condition to confirm, never a ban on the whole class.
    (['47.11 — торговля в неспециализированных магазинах'], [], ['47.11 — торговля в неспециализированных магазинах']),
    (['64–66.19 — часть финансовых услуг'], [], ['64–66.19 — часть финансовых услуг']),
    (['47,11 торговля', '47. Торговля'], ['47'], ['47,11 торговля']),
])
def test_okved_entries_count_only_with_a_leading_code_or_range(entries, classes, unparsed):
    assert okved_deny(entries) == (classes, unparsed)


def test_conditions_to_confirm_list_requirements_categories_and_unparsed_okved(shipped):
    for product in shipped.products:
        raw = oracle.ITEMS[product['id']]['eligibility']
        expected = ([{'kind': 'requirement', 'text': text} for text in raw['requirements']]
                    + [{'kind': 'category', 'text': text} for text in raw['categories']]
                    + [{'kind': 'okved', 'text': text} for text in oracle.unparsed_okved(raw['okved_deny_main'])])
        assert product['conditions_to_confirm'] == expected, product['id']
    assert shipped.product('alfa_term_loan_unsecured')['conditions_to_confirm'] == []


@pytest.mark.parametrize('formula,expected', [
    ('KEY_RATE', '14.0'), ('KEY_RATE + 3', '17.0'), ('KEY_RATE - 3.5', '10.5'), ('KEY_RATE+0.25', '14.25'),
    ('  KEY_RATE   -   14 ', '0.0'), ('21.5', '21.5'), ('7', '7'),
])
def test_rate_formula_parser_supports_key_rate_offsets_and_numbers(formula, expected):
    assert parse_rate_formula(formula, Decimal('14.0')) == Decimal(expected)


@pytest.mark.parametrize('formula', ['KEY_RATE * 2', 'KEY_RATE + KEY_RATE', '__import__("os")', 'KEY_RATE +', '-3',
                                     'key_rate + 1', 'KEY_RATE + 1e2', '', '1/2'])
def test_rate_formula_parser_refuses_anything_else(formula):
    with pytest.raises(ValueError):
        parse_rate_formula(formula, Decimal('14.0'))


def test_regions_are_normalised_on_both_sides(shipped):
    steps = ('casefold', 'yo_to_ye', 'collapse_spaces')
    assert normalize_region('  Курская   ОБЛАСТЬ ', steps) == normalize_region('курская область', steps) == 'курская область'
    assert normalize_region('Орёл', steps) == 'орел'
    assert shipped.region_key('Белгородская  область') == shipped.region_key('белгородская область')
    assert shipped.product('psk_borderline')['eligibility']['regions_allow'] == ['Курская область', 'Белгородская область', 'Брянская область']


def test_overlays_render_as_badges_with_a_softer_text_on_secured_cards(shipped):
    overlay = shipped.overlays[0]
    raw = oracle.ITEMS['zont_corpmsp']
    assert overlay['applies_to'] == raw['display']['applies_to']
    assert overlay['badge_text'] == raw['display']['headline'] and 'Залог не нужен' in overlay['badge_text']
    assert overlay['badge_text_collateral_required'] and 'Залог не нужен' not in overlay['badge_text_collateral_required']
    assert overlay['eligibility']['msp_registry_required'] is True
    for product in shipped.products:
        assert product['overlay_ids'] == (['zont_corpmsp'] if product['id'] in raw['display']['applies_to'] else []), product['id']


def test_the_amount_slider_reaches_every_product_minimum_exactly(shipped):
    slider = shipped.amount_slider
    assert (slider['scale'], slider['min_rub'], slider['max_rub'], slider['default_rub']) == ('log', 300_000, 2_000_000_000, 2_000_000)

    def step(value):
        return next(band['step_rub'] for band in slider['snap'] if value <= band['up_to_rub'])
    for value in (300_000, 500_000, 25_000_000, *[product['amount_min_rub'] for product in shipped.products]):
        assert slider['min_rub'] <= value <= slider['max_rub'] and value % step(value) == 0, value
    assert all(slider['min_rub'] <= preset <= slider['max_rub'] and preset % step(preset) == 0 for preset in slider['presets_rub'])


def test_public_catalog_shape_has_no_research_items(shipped):
    body = shipped.public()
    assert set(body) == {'catalog_version', 'rules_version', 'key_rate', 'amount_slider', 'products', 'overlays'}
    assert body['products'] == list(shipped.products) and body['overlays'] == list(shipped.overlays)
    json.dumps(body)  # plain JSON: no Decimal, Path or tuple surprises


def test_any_edit_changes_the_stamped_version_even_without_a_version_bump(tmp_path, shipped):
    catalog = deepcopy(SOURCE_CATALOG)
    item(catalog, 'alfa_factoring')['display']['features'][0] += '.'
    edited = load_config(*write_pair(tmp_path, catalog=catalog))
    assert edited.catalog_version.split('+')[0] == shipped.catalog_version.split('+')[0] == '2026-10-25.1'
    assert edited.catalog_version != shipped.catalog_version and edited.rules_version == shipped.rules_version
    policy = deepcopy(SOURCE_POLICY)
    policy['products']['psk_borderline']['priority'] += 1
    repriced = load_config(*write_pair(tmp_path, policy=policy))
    assert repriced.rules_version.split('+')[0] == 'demo-rules-v2' and repriced.rules_version != shipped.rules_version


def test_config_changes_really_change_the_runtime_model(tmp_path):
    catalog, policy = deepcopy(SOURCE_CATALOG), deepcopy(SOURCE_POLICY)
    catalog['params']['key_rate']['value_percent'] = 16.0
    item(catalog, 'psk_working_capital')['rate']['periods'][0]['rate_percent'] = 19.0
    item(catalog, 'psk_invest_subsidy')['rate']['periods'][0]['rate_percent'] = 12.5
    item(catalog, 'psk_borderline')['rate']['periods'][0]['rate_percent'] = 16.0
    item(catalog, 'alfa_term_loan_unsecured')['amount']['max'] = 25_000_000
    policy['defaults']['amount_min_rub'] = 400_000
    policy['defaults']['term_max_months'] = 24
    config = load_config(*write_pair(tmp_path, catalog, policy))
    assert config.product('psk_working_capital')['annual_rate_bps'] == 1900
    assert config.product('alfa_term_loan_unsecured')['amount_max_rub'] == 25_000_000
    assert config.product('alfa_goscredit_zont')['amount_min_rub'] == 400_000
    assert config.product('psk_borderline')['term_max_months'] == 24
    assert config.product('psk_borderline')['rate_certainty'] == 'preferential'  # 12 < 24


def drop(container: dict, key: str) -> None:
    del container[key]


# (description, catalog edit, policy edit, expected error line). Each edit breaks exactly one rule of the shipped files.
CASES = [
    ('catalog version missing', lambda c: drop(c, 'catalog_version'), None, 'catalog_version: missing'),
    ('key rate missing', lambda c: drop(c['params']['key_rate'], 'value_percent'), None, 'params.key_rate.value_percent: missing'),
    ('unknown kind', lambda c: item(c, 'alfa_factoring').update(kind='loan'), None, "items[alfa_factoring].kind: unknown value 'loan'"),
    ('unknown instrument', lambda c: item(c, 'alfa_factoring').update(instrument_type='leasing'), None,
     "items[alfa_factoring].instrument_type: unknown value 'leasing'"),
    ('unknown purpose', lambda c: item(c, 'alfa_factoring').update(purposes=['consumer']), None,
     "items[alfa_factoring].purposes[0]: unknown value 'consumer'"),
    ('purpose the app cannot ask', lambda c: (c['enums']['purposes'].append('leasing'), item(c, 'alfa_factoring')['purposes'].append('leasing')),
     None, "items[alfa_factoring].purposes[1]: 'leasing' is not supported by the application"),
    ('unknown rate type', lambda c: item(c, 'alfa_factoring')['rate'].update(type='floating'), None,
     "items[alfa_factoring].rate.type: unknown value 'floating'"),
    ('unknown limit status', lambda c: item(c, 'alfa_factoring').update(limit_status='paused'), None,
     "items[alfa_factoring].limit_status: unknown value 'paused'"),
    ('unknown entity type', lambda c: item(c, 'alfa_factoring')['eligibility'].update(entity_types=['АО']), None,
     "items[alfa_factoring].eligibility.entity_types[0]: unknown value 'АО'"),
    ('unknown confidence', lambda c: item(c, 'alfa_factoring')['source'].update(confidence='rumour'), None,
     "items[alfa_factoring].source.confidence: unknown value 'rumour'"),
    ('duplicate id', lambda c: item(c, 'alfa_factoring').update(id='alfa_term_loan_unsecured'), None,
     "items[7].id: duplicate id 'alfa_term_loan_unsecured'"),
    ('unknown guarantee overlay', lambda c: item(c, 'psk_borderline')['collateral'].update(guarantee_overlay='zont_x'), None,
     "items[psk_borderline].collateral.guarantee_overlay: unknown overlay 'zont_x'"),
    ('guarantee overlay without the product', lambda c: item(c, 'alfa_universal_limit')['collateral'].update(guarantee_overlay='zont_corpmsp'),
     None, "items[alfa_universal_limit].collateral.guarantee_overlay: zont_corpmsp does not list this product in display.applies_to"),
    ('overlay names an unknown product', lambda c: item(c, 'zont_corpmsp')['display']['applies_to'].append('nope'), None,
     "items[zont_corpmsp].display.applies_to[9]: unknown product 'nope'"),
    ('formula disagrees with its percent', lambda c: item(c, 'psk_invest_subsidy')['rate']['periods'][0].update(rate_percent=11.0), None,
     'items[psk_invest_subsidy].rate.periods[0].rate_percent: 11.0 does not equal KEY_RATE - 3.5 = 10.5'),
    ('unsupported formula', lambda c: item(c, 'psk_borderline')['rate']['periods'][0].update(rate_formula='KEY_RATE * 1'), None,
     "items[psk_borderline].rate.periods[0].rate_formula: unsupported formula 'KEY_RATE * 1'"),
    ('disclosed rate without a percent', lambda c: item(c, 'alfa_term_loan_unsecured')['rate']['periods'][0].update(rate_percent=None), None,
     'items[alfa_term_loan_unsecured].rate.periods[0].rate_percent: null for a disclosed rate'),
    ('undisclosed rate with a percent', lambda c: item(c, 'alfa_factoring')['rate']['periods'][0].update(rate_percent=12.0), None,
     'items[alfa_factoring].rate.periods[0].rate_percent: set for an undisclosed rate'),
    ('rate below a basis point', lambda c: item(c, 'alfa_term_loan_unsecured')['rate']['periods'][0].update(rate_percent=23.505), None,
     'items[alfa_term_loan_unsecured].rate.periods[0].rate_percent: 23.505 is not a whole number of basis points'),
    ('two rate periods', lambda c: item(c, 'alfa_term_loan_unsecured')['rate']['periods'].append(
        dict(item(c, 'alfa_term_loan_unsecured')['rate']['periods'][0], from_month=13)), None,
     'items[alfa_term_loan_unsecured].rate.periods: exactly one period from month 1 is supported'),
    ('null maximum without a fallback', None, lambda p: drop(p['defaults'], 'amount_max_rub_if_null'),
     'items[alfa_factoring].amount.max: null, no policy fallback'),
    ('null minimum without a fallback', None, lambda p: drop(p['defaults'], 'amount_min_rub'),
     'items[alfa_goscredit_zont].amount.min: null, no policy fallback'),
    ('minimum above maximum', lambda c: item(c, 'alfa_term_loan_unsecured')['amount'].update(min=40_000_000), None,
     'items[alfa_term_loan_unsecured].amount: min 40000000 is above max 30000000'),
    ('unsecured cap above maximum', lambda c: item(c, 'alfa_universal_limit')['amount'].update(max_unsecured=80_000_000), None,
     'items[alfa_universal_limit].amount.max_unsecured: 80000000 is above max 70000000'),
    ('null term without a fallback', None, lambda p: drop(p['defaults'], 'term_min_months'),
     'items[alfa_goscredit_zont].term.min_months: null, no policy fallback'),
    ('unlimited term with bounds', lambda c: item(c, 'alfa_revolving_line_unsecured')['term'].update(max_months=18), None,
     'items[alfa_revolving_line_unsecured].term: unlimited with month bounds'),
    ('term minimum above maximum', lambda c: item(c, 'alfa_term_loan_unsecured')['term'].update(min_months=61), None,
     'items[alfa_term_loan_unsecured].term: min 61 is above max 60'),
    ('per-purpose term outside the range', lambda c: item(c, 'alfa_goscredit_zont')['term'].update(max_months_by_purpose={'working_capital': 70}),
     None, 'items[alfa_goscredit_zont].term.max_months_by_purpose.working_capital: 70 is outside 6–60'),
    ('per-purpose term for another purpose', lambda c: item(c, 'alfa_goscredit_zont')['term'].update(max_months_by_purpose={'business_development': 24}),
     None, "items[alfa_goscredit_zont].term.max_months_by_purpose.business_development: not a purpose of this product"),
    ('null collateral without a policy mode', None, lambda p: drop(p['products']['psk_invest_subsidy'], 'collateral_mode'),
     'items[psk_invest_subsidy].collateral.required: null, no policy fallback'),
    ('missing summary', lambda c: item(c, 'alfa_factoring')['display'].update(summary=' '), None,
     'items[alfa_factoring].display.summary: missing explanation text'),
    ('too few features', lambda c: item(c, 'alfa_factoring')['display'].update(features=['a', 'b']), None,
     'items[alfa_factoring].display.features: 3–5 explanation bullets required'),
    ('missing best_for', lambda c: drop(item(c, 'psk_borderline')['display'], 'best_for'), None,
     'items[psk_borderline].display.best_for: missing explanation text'),
    ('rules version missing', None, lambda p: drop(p, 'rules_version'), 'policy.rules_version: missing'),
    ('entity type unmapped', None, lambda p: drop(p['entity_types'], 'ИП'), "policy.entity_types: no mapping for 'ИП'"),
    ('entity type mapped to an unknown type', None, lambda p: p['entity_types'].update({'ЮЛ': 'CORP'}),
     "policy.entity_types.ЮЛ: unknown entity type 'CORP'"),
    ('unknown document type', None, lambda p: p['defaults']['base_documents'].append('PASSPORT'),
     "policy.defaults.base_documents[2]: unknown document type 'PASSPORT'"),
    ('missing payment model', None, lambda p: drop(p['payment_models'], 'factoring'), 'policy.payment_models.factoring: missing'),
    ('unknown payment model', None, lambda p: p['payment_models'].update(term_loan='bullet'),
     "policy.payment_models.term_loan: unknown payment model 'bullet'"),
    ('override for an unknown product', None, lambda p: p['products'].update(nope={'priority': 1}), 'policy.products.nope: unknown product'),
    ('override widens the maximum', None, lambda p: p['products']['alfa_term_loan_unsecured'].update(amount_max_rub=40_000_000),
     'policy.products.alfa_term_loan_unsecured.amount_max_rub: 40000000 weakens the catalog max 30000000'),
    ('override lowers the minimum', None, lambda p: p['products']['alfa_term_loan_secured'].update(amount_min_rub=300_000),
     'policy.products.alfa_term_loan_secured.amount_min_rub: 300000 weakens the catalog min 500000'),
    ('override shortens the minimum term', None, lambda p: p['products']['alfa_term_loan_unsecured'].update(term_min_months=6),
     'policy.products.alfa_term_loan_unsecured.term_min_months: 6 weakens the catalog min 12'),
    ('override lengthens the maximum term', None, lambda p: p['products']['alfa_factoring'].update(term_max_months=24),
     'policy.products.alfa_factoring.term_max_months: 24 weakens the catalog max 12'),
    ('override makes required collateral optional', None, lambda p: p['products']['alfa_term_loan_secured'].update(collateral_mode='optional'),
     "policy.products.alfa_term_loan_secured.collateral_mode: 'optional' weakens the catalog's required collateral"),
    ('unknown collateral mode', None, lambda p: p['products']['alfa_universal_limit'].update(collateral_mode='maybe'),
     "policy.products.alfa_universal_limit.collateral_mode: unknown value 'maybe'"),
    ('non-integer priority', None, lambda p: p['products']['psk_borderline'].update(priority='high'),
     'policy.products.psk_borderline.priority: must be an integer, got "high"'),
    ('incomplete ranking table', None, lambda p: drop(p['ranking']['collateral_burden'], 'optional'),
     "policy.ranking.collateral_burden: missing 'optional'"),
    ('slider misses a product minimum', None, lambda p: p['amount_slider'].update(min_rub=400_000),
     'policy.amount_slider: product minimum 300000 of alfa_term_loan_unsecured is outside 400000–2000000000'),
    ('slider steps miss a product minimum', None, lambda p: p['amount_slider']['snap'][2].update(step_rub=3_000_000),
     'policy.amount_slider: product minimum 25000000 of psk_invest_subsidy does not land on a slider step'),
    ('slider default off the grid', None, lambda p: p['amount_slider'].update(default_rub=2_050_000),
     'policy.amount_slider.default_rub: 2050000 does not land on a slider step'),
    ('slider bands end before the maximum', None, lambda p: p['amount_slider']['snap'][-1].update(up_to_rub=1_000_000_000),
     'policy.amount_slider.snap: the last band must end at max_rub 2000000000'),
    ('badge for an unknown overlay', None, lambda p: p['overlay_badges'].update(nope={'text_collateral_required': 'x', 'okved_exempt_products': []}),
     'policy.overlay_badges.nope: unknown overlay'),
    ('badge exemption outside applies_to', None, lambda p: p['overlay_badges']['zont_corpmsp']['okved_exempt_products'].append('alfa_factoring'),
     "policy.overlay_badges.zont_corpmsp.okved_exempt_products[1]: 'alfa_factoring' is not in the overlay's applies_to"),
    ('unsupported OKVED rule', None, lambda p: p['okved_rule'].update(deny_entries='any_mention'),
     "policy.okved_rule.deny_entries: unsupported value 'any_mention'"),
    ('unsupported region step', None, lambda p: p['region_normalization'].append('transliterate'),
     "policy.region_normalization[3]: unsupported step 'transliterate'"),
    ('non-positive estimate term', None, lambda p: p.update(payment_estimate_term_months=0),
     'policy.payment_estimate_term_months: must be a positive integer'),
    # Fix round 1: mistyped numbers must fail the check instead of reaching a recommendation.
    ('amount maximum as a string', lambda c: item(c, 'alfa_term_loan_unsecured')['amount'].update(max='30000000'), None,
     'items[alfa_term_loan_unsecured].amount.max: must be a positive integer, got "30000000"'),
    ('fractional amount maximum', lambda c: item(c, 'alfa_term_loan_unsecured')['amount'].update(max=30000000.5), None,
     'items[alfa_term_loan_unsecured].amount.max: must be a positive integer, got 30000000.5'),
    ('zero amount minimum', lambda c: item(c, 'alfa_term_loan_unsecured')['amount'].update(min=0), None,
     'items[alfa_term_loan_unsecured].amount.min: must be a positive integer, got 0'),
    ('negative term maximum', lambda c: item(c, 'alfa_term_loan_unsecured')['term'].update(max_months=-5), None,
     'items[alfa_term_loan_unsecured].term.max_months: must be a positive integer, got -5'),
    ('string term minimum', lambda c: item(c, 'alfa_term_loan_secured')['term'].update(min_months='12'), None,
     'items[alfa_term_loan_secured].term.min_months: must be a positive integer, got "12"'),
    ('unsecured cap as a string', lambda c: item(c, 'alfa_universal_limit')['amount'].update(max_unsecured='20000000'), None,
     'items[alfa_universal_limit].amount.max_unsecured: must be a positive integer or null, got "20000000"'),
    ('tranche minimum as a string', lambda c: item(c, 'alfa_revolving_line_unsecured')['amount'].update(tranche_min='50000'), None,
     'items[alfa_revolving_line_unsecured].amount.tranche_min: must be a positive integer or null, got "50000"'),
    ('string default minimum', None, lambda p: p['defaults'].update(amount_min_rub='300000'),
     'policy.defaults.amount_min_rub: must be a positive integer, got "300000"'),
    ('zero default term', None, lambda p: p['defaults'].update(term_min_months=0),
     'policy.defaults.term_min_months: must be a positive integer, got 0'),
    ('fractional default maximum', None, lambda p: p['defaults'].update(amount_max_rub_if_null=2000000000.5),
     'policy.defaults.amount_max_rub_if_null: must be a positive integer, got 2000000000.5'),
    ('base documents removed', None, lambda p: drop(p['defaults'], 'base_documents'),
     'policy.defaults.base_documents: at least one document type is required'),
    ('base documents empty', None, lambda p: p['defaults'].update(base_documents=[]),
     'policy.defaults.base_documents: at least one document type is required'),
    ('collateral documents without the valuation', None, lambda p: p['defaults'].update(collateral_documents=['COLLATERAL_OWNERSHIP']),
     'policy.defaults.collateral_documents: must include COLLATERAL_VALUATION, whose verified value bounds a secured final approval'),
    ('a document type listed twice', None, lambda p: p['defaults'].update(base_documents=['BANK_STATEMENT', 'BANK_STATEMENT']),
     "policy.defaults.base_documents[1]: duplicate document type 'BANK_STATEMENT'"),
    ('documents not a list', None, lambda p: p['defaults'].update(collateral_documents='COLLATERAL_VALUATION'),
     'policy.defaults.collateral_documents: must be a list of document types'),
    ('annuity over an unlimited term', lambda c: item(c, 'alfa_term_loan_unsecured')['term'].update(unlimited=True, min_months=None, max_months=None),
     None, 'items[alfa_term_loan_unsecured].term.unlimited: an annuity payment needs a term'),
    ('unlimited flag not a boolean', lambda c: item(c, 'alfa_factoring')['term'].update(unlimited='no'), None,
     'items[alfa_factoring].term.unlimited: must be true or false'),
    ('non-positive per-product amount', None, lambda p: p['products']['alfa_factoring'].update(amount_min_rub=0),
     'policy.products.alfa_factoring.amount_min_rub: must be a positive integer, got 0'),
    ('unknown per-product setting', None, lambda p: p['products']['alfa_factoring'].update(foo=1),
     'policy.products.alfa_factoring.foo: unknown setting'),
    # Fix round 1: malformed shapes are reported, never raised.
    ('non-numeric key rate', lambda c: c['params']['key_rate'].update(value_percent='abc'), None,
     'params.key_rate.value_percent: must be a number, got "abc"'),
    ('key rate below a basis point', lambda c: c['params']['key_rate'].update(value_percent=14.005), None,
     'params.key_rate.value_percent: 14.005 is not a whole number of basis points'),
    ('key rate not an object', lambda c: c['params'].update(key_rate=14), None, 'params.key_rate: must be an object'),
    ('key rate section missing', lambda c: drop(c['params'], 'key_rate'), None, 'params.key_rate: missing'),
    ('a card without an id', lambda c: drop(item(c, 'alfa_factoring'), 'id'), None, 'items[7].id: missing'),
    ('an item that is not an object', lambda c: c['items'].append('loan'), None, 'items[12]: must be an object'),
    ('items not a list', lambda c: c.update(items={}), None, 'items: must be a list'),
    ('enums not an object', lambda c: c.update(enums=[]), None, 'enums: must be an object'),
    ('enum values not a list', lambda c: c['enums'].update(kind='product'), None, 'enums.kind: must be a list'),
    ('enums missing', lambda c: drop(c, 'enums'), None, 'enums: missing'),
    ('items missing', lambda c: drop(c, 'items'), None, 'items: missing'),
    ('a display that is not an object', lambda c: item(c, 'alfa_factoring').update(display='card'), None,
     'items[alfa_factoring].display: must be an object'),
    ('a per-product setting that is not an object', None, lambda p: p['products'].update(alfa_factoring=5),
     'policy.products.alfa_factoring: must be an object'),
    ('a policy section of the wrong type', None, lambda p: p.update(defaults=[]), 'policy.defaults: must be an object'),
    ('a badge setting that is not an object', None, lambda p: p['overlay_badges'].update(zont_corpmsp='x'),
     'policy.overlay_badges.zont_corpmsp: must be an object'),
    ('slider bands that are not objects', None, lambda p: p['amount_slider'].update(snap=[1, 2]),
     'policy.amount_slider.snap: bands need ascending up_to_rub and positive step_rub'),
    ('malformed entry', lambda c: drop(item(c, 'alfa_factoring'), 'rate'), None, "items[alfa_factoring]: malformed entry (KeyError: 'rate')"),
    # Fix round 1: the remaining checker branches.
    ('rate type a card cannot use', lambda c: item(c, 'alfa_factoring')['rate'].update(type='schedule'), None,
     "items[alfa_factoring].rate.type: 'schedule' is not supported for a card product"),
    ('formula rate without a formula', lambda c: item(c, 'psk_invest_subsidy')['rate']['periods'][0].update(rate_formula=None), None,
     'items[psk_invest_subsidy].rate.periods[0].rate_formula: missing for a formula rate'),
    ('rate percent as a string', lambda c: item(c, 'alfa_term_loan_unsecured')['rate']['periods'][0].update(rate_percent='23.5'), None,
     'items[alfa_term_loan_unsecured].rate.periods[0].rate_percent: must be a number, got "23.5"'),
    ('negative rate', lambda c: item(c, 'alfa_term_loan_unsecured')['rate']['periods'][0].update(rate_percent=-1.0), None,
     'items[alfa_term_loan_unsecured].rate.periods[0].rate_percent: must not be negative, got -1.0'),
    ('preferential end as a string', lambda c: item(c, 'psk_working_capital')['rate']['periods'][0].update(to_month='12'), None,
     'items[psk_working_capital].rate.periods[0].to_month: must be a positive integer or null, got "12"'),
    ('formula not a text', lambda c: item(c, 'psk_borderline')['rate']['periods'][0].update(rate_formula=14), None,
     'items[psk_borderline].rate.periods[0].rate_formula: must be a text, got 14'),
    ('an overlay shown as a card', lambda c: item(c, 'zont_corpmsp')['display'].update(**{'as': 'card'}), None,
     'items[zont_corpmsp].display.as: an overlay renders as badge_on_card'),
    ('an overlay without badge text', lambda c: item(c, 'zont_corpmsp')['display'].update(headline=None), None,
     'items[zont_corpmsp].display.headline: missing badge text'),
    ('unknown applyable kind', None, lambda p: p['applyable_kinds'].append('loan'), "policy.applyable_kinds[2]: unknown kind 'loan'"),
    ('no applyable kind', None, lambda p: p.update(applyable_kinds=[]), 'policy.applyable_kinds: at least one kind is required'),
    ('no card products', lambda c: [entry['display'].update(**{'as': 'badge_on_card'}) for entry in c['items'] if entry['kind'] != 'overlay'],
     None, "items: no card product of the policy's applyable kinds"),
    ('missing required default', None, lambda p: drop(p['defaults'], 'low_risk_revenue_multiple'),
     'policy.defaults.low_risk_revenue_multiple: missing'),
    ('non-positive required default', None, lambda p: p['defaults'].update(collateral_ltv_bps=0),
     'policy.defaults.collateral_ltv_bps: must be a positive integer, got 0'),
    ('slider scale', None, lambda p: p['amount_slider'].update(scale='linear'), "policy.amount_slider.scale: unsupported value 'linear'"),
    ('slider minimum above its maximum', None, lambda p: p['amount_slider'].update(min_rub=3_000_000_000),
     'policy.amount_slider: min_rub and max_rub must be positive integers, min below max'),
    ('slider bands out of order', None, lambda p: p['amount_slider']['snap'].reverse(),
     'policy.amount_slider.snap: bands need ascending up_to_rub and positive step_rub'),
    ('slider preset out of range', None, lambda p: p['amount_slider']['presets_rub'].append(3_000_000_000),
     'policy.amount_slider.presets_rub[7]: 3000000000 is outside 300000–2000000000'),
    # Fix round 1: catalog vocabulary and eligibility shapes.
    ('status typo', lambda c: item(c, 'alfa_factoring').update(status='actve'), None, "items[alfa_factoring].status: unknown value 'actve'"),
    ('display typo', lambda c: item(c, 'alfa_factoring')['display'].update(**{'as': 'cards'}), None,
     "items[alfa_factoring].display.as: unknown value 'cards'"),
    ('missing name', lambda c: item(c, 'alfa_factoring').update(name=' '), None, 'items[alfa_factoring].name: missing'),
    ('no purposes', lambda c: item(c, 'alfa_factoring').update(purposes=[]), None,
     'items[alfa_factoring].purposes: at least one purpose is required'),
    ('collateral flag not a boolean', lambda c: item(c, 'alfa_factoring')['collateral'].update(required='no'), None,
     'items[alfa_factoring].collateral.required: must be true, false or null'),
    # Task 9: a JSON 1.0/0.0 parses as a Decimal equal to True/False; it is no boolean, and 1.0 must not let the policy
    # make a required pledge optional unnoticed.
    ('collateral flag 1.0', lambda c: item(c, 'alfa_term_loan_secured')['collateral'].update(required=1.0),
     lambda p: p['products']['alfa_term_loan_secured'].update(collateral_mode='optional'),
     'items[alfa_term_loan_secured].collateral.required: must be true, false or null'),
    ('collateral flag 0.0', lambda c: item(c, 'alfa_factoring')['collateral'].update(required=0.0), None,
     'items[alfa_factoring].collateral.required: must be true, false or null'),
    ('registry flag not a boolean', lambda c: item(c, 'alfa_goscredit_zont')['eligibility'].update(msp_registry_required='yes'), None,
     'items[alfa_goscredit_zont].eligibility.msp_registry_required: must be true or false'),
    ('regions not a list', lambda c: item(c, 'psk_borderline')['eligibility'].update(regions_allow='Курская область'), None,
     'items[psk_borderline].eligibility.regions_allow: must be a list of texts'),
    ('OKVED entries not texts', lambda c: item(c, 'alfa_goscredit_zont')['eligibility'].update(okved_deny_main=[64]), None,
     'items[alfa_goscredit_zont].eligibility.okved_deny_main: must be a list of texts'),
]


@pytest.mark.parametrize('description,edit_catalog,edit_policy,expected', CASES, ids=[case[0] for case in CASES])
def test_every_validation_rule_fails_with_its_path(tmp_path, description, edit_catalog, edit_policy, expected):
    catalog, policy = deepcopy(SOURCE_CATALOG), deepcopy(SOURCE_POLICY)
    if edit_catalog:
        edit_catalog(catalog)
    if edit_policy:
        edit_policy(policy)
    assert expected in errors_of(tmp_path, catalog, policy)


def test_unreadable_files_report_their_role(tmp_path):
    catalog_path, policy_path = write_pair(tmp_path)
    catalog_path.write_text('{not json', encoding='utf-8')
    with pytest.raises(ConfigError) as caught:
        load_config(catalog_path, policy_path)
    assert caught.value.errors[0].startswith('catalog: invalid JSON')
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path / 'absent.json', policy_path)
    assert caught.value.errors[0].startswith('catalog: cannot read')
    catalog_path.write_text('[]', encoding='utf-8')
    with pytest.raises(ConfigError) as caught:
        load_config(catalog_path, policy_path)
    assert caught.value.errors == ['catalog: the file must hold a JSON object']


@pytest.mark.parametrize('okved,expected', [('46.90', '46'), ('47', '47'), ('  25.62', '25'), ('4690', None), ('ОКВЭД 46', None),
                                            ('', None), (None, None)])
def test_a_company_okved_code_gives_its_two_digit_class(okved, expected):
    from app.products_config import okved_class  # the one helper the recommendation checks and badges share
    assert okved_class(okved) == expected


def test_every_error_is_collected_not_just_the_first(tmp_path):
    catalog, policy = deepcopy(SOURCE_CATALOG), deepcopy(SOURCE_POLICY)
    item(catalog, 'alfa_factoring').update(kind='loan')
    item(catalog, 'psk_invest_subsidy')['rate']['periods'][0]['rate_percent'] = 11.0
    del policy['defaults']['amount_max_rub_if_null']
    errors = errors_of(tmp_path, catalog, policy)
    assert "items[alfa_factoring].kind: unknown value 'loan'" in errors
    assert 'items[psk_invest_subsidy].rate.periods[0].rate_percent: 11.0 does not equal KEY_RATE - 3.5 = 10.5' in errors


def test_paths_default_to_the_data_files_and_follow_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv('CREDIT_CATALOG_PATH', raising=False)
    monkeypatch.delenv('DEMO_POLICY_PATH', raising=False)
    assert configured_paths() == (oracle.CATALOG_PATH, oracle.POLICY_PATH)
    monkeypatch.setenv('CREDIT_CATALOG_PATH', str(tmp_path / 'c.json'))
    monkeypatch.setenv('DEMO_POLICY_PATH', str(tmp_path / 'p.json'))
    assert configured_paths() == (tmp_path / 'c.json', tmp_path / 'p.json')


def run_python(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=BACKEND, capture_output=True, text=True, timeout=60,
                          env={**os.environ, **(env or {})})


def test_cli_checks_the_shipped_files():
    result = run_python('-m', 'app.products_config', 'check')
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith('OK: catalog 2026-10-25.1+') and '11 products, 1 overlay' in result.stdout


def test_cli_reports_every_error_with_its_path(tmp_path):
    catalog = deepcopy(SOURCE_CATALOG)
    item(catalog, 'psk_invest_subsidy')['rate']['periods'][0]['rate_percent'] = 11.0
    item(catalog, 'alfa_factoring')['display']['summary'] = ''
    catalog_path, policy_path = write_pair(tmp_path, catalog)
    result = run_python('-m', 'app.products_config', 'check', '--catalog', str(catalog_path), '--policy', str(policy_path))
    assert result.returncode == 1
    assert 'items[psk_invest_subsidy].rate.periods[0].rate_percent: 11.0 does not equal KEY_RATE - 3.5 = 10.5' in result.stdout
    assert 'items[alfa_factoring].display.summary: missing explanation text' in result.stdout


def test_the_app_refuses_to_start_with_a_broken_catalog(tmp_path):
    catalog = deepcopy(SOURCE_CATALOG)
    item(catalog, 'alfa_factoring')['amount']['min'] = 3_000_000_000
    catalog_path, _ = write_pair(tmp_path, catalog)
    result = run_python('-c', 'import app.main', env={'CREDIT_CATALOG_PATH': str(catalog_path)})
    assert result.returncode != 0
    assert 'items[alfa_factoring].amount: min 3000000000 is above max 2000000000' in result.stderr


def test_slider_presets_are_optional(tmp_path):
    policy = deepcopy(SOURCE_POLICY)
    del policy['amount_slider']['presets_rub']
    assert load_config(*write_pair(tmp_path, policy=policy)).amount_slider['presets_rub'] == []


BAD_VALUES = ['x', '', -1, 0, 1.5, None, {}, [], True, 10**15]
CATALOG_SCOPE = ('alfa_term_loan_unsecured', 'alfa_revolving_line_unsecured', 'alfa_universal_limit', 'alfa_factoring',
                 'psk_working_capital', 'zont_corpmsp')
SAMPLE_COMPANIES = [
    {'registry_status': 'active', 'entity_type': 'LLC', 'msp_registry': True, 'region': 'Москва', 'okved': '46.90'},
    {'registry_status': 'unknown', 'entity_type': 'IP', 'msp_registry': None, 'region': 'Курская область', 'okved': '47.11'},
]


def paths_of(value, path=()):
    """Every container and leaf path inside a JSON value (the value itself first)."""
    yield path
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from paths_of(inner, path + (key,))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from paths_of(inner, path + (index,))


def replaced(data, path, value):
    copy = deepcopy(data)
    target = copy
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return copy


@pytest.mark.parametrize('which', ['catalog', 'policy'])
def test_no_single_mistyped_value_passes_the_check_and_then_breaks_a_recommendation(tmp_path, which):
    """Each value of the policy, and of six representative catalog items and the key rate, replaced in turn by a
    mistyped one: the load either fails with ConfigError or gives a configuration that serialises and recommends."""
    from app.recommendations.service import recommend
    if which == 'catalog':
        indexes = [index for index, entry in enumerate(SOURCE_CATALOG['items']) if entry['id'] in CATALOG_SCOPE]
        paths = [('items', index) + inner for index in indexes for inner in paths_of(SOURCE_CATALOG['items'][index])]
        paths += [('params',) + inner for inner in paths_of(SOURCE_CATALOG['params'])]
    else:
        paths = [inner for inner in paths_of(SOURCE_POLICY) if inner]
    loaded = refused = 0
    for path in paths:
        for bad in BAD_VALUES:
            catalog = replaced(SOURCE_CATALOG, path, bad) if which == 'catalog' else None
            policy = replaced(SOURCE_POLICY, path, bad) if which == 'policy' else None
            try:
                config = load_config(*write_pair(tmp_path, catalog, policy))
            except ConfigError:
                refused += 1
                continue
            loaded += 1
            json.dumps(config.public())
            for company in SAMPLE_COMPANIES:
                for amount in (300_000, 25_000_000):
                    items = recommend(company, {'monthly_revenue_rub': 800_000}, {'requested_amount_rub': amount}, config)
                    json.dumps(items)
    assert refused > loaded > 0  # most mistyped values are refused; harmless ones (texts, notes) still load
