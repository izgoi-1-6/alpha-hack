"""Recommendation HTTP contract: the amount-only need, every catalog card product, machine-checked eligibility,
estimates, badges, saved snapshots, version staleness and no BKI or scoring inputs.

Expected values come from recommendation_oracle (its own reading of the raw data files, exact arithmetic) and a few
literal numbers written out below, never from the recommendation code under test.
"""
from copy import deepcopy
import json
import os
import threading
from uuid import uuid4
import pytest
from sqlalchemy import select, update
from app.models import Company, Precheck
from test_identity_company import client, register, add
import catalog_oracle
import recommendation_oracle as oracle

TERM, LINE, SECURED = 'alfa_term_loan_unsecured', 'alfa_revolving_line_unsecured', 'alfa_term_loan_secured'
GOSCREDIT, UNIVERSAL, FACTORING = 'alfa_goscredit_zont', 'alfa_universal_limit', 'alfa_factoring'
PSK_INVEST, PSK_WORKING, PSK_BORDER = 'psk_invest_subsidy', 'psk_working_capital', 'psk_borderline'
ITEM_KEYS = {'product_id', 'rank', 'status', 'can_apply', 'indicative_limit_rub', 'catalog_max_rub', 'requested_amount_rub',
             'checks', 'reasons', 'alternatives', 'estimated_payment_rub', 'payment_note', 'payment_label', 'badges',
             'conditions_to_confirm'}
NOTICE = 'Предварительная оценка по обороту, не предодобрение. БКИ не запрашивалось.'


def setup(client, fixture_id='strong'):
    register(client)
    response = add(client, oracle.FIXTURES[fixture_id]['inn'])
    assert response.status_code == 201, response.text
    return response.json()['company']['id']


def recommend(client, company, amount=2_000_000, **extra):
    return client.post(f'/api/v1/companies/{company}/recommendations', json={'requested_amount_rub': amount, **extra})


def body(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def items(response) -> dict:
    return {item['product_id']: item for item in body(response)['items']}


def check(item, code):
    return next(c for c in item['checks'] if c['code'] == code)


def set_revenue(client, company, revenue):
    with client.app.state.test_factory.begin() as db:
        db.execute(update(Precheck).where(Precheck.company_id == company).values(monthly_revenue_rub=revenue))


def set_company(client, company, **values):
    with client.app.state.test_factory.begin() as db:
        db.execute(update(Company).where(Company.id == company).values(**values))


def test_catalog_serves_every_card_product_with_explanations_and_no_research_items(client):
    response = client.get('/api/v1/catalog')  # public, read-only reference data
    assert response.status_code == 200
    catalog = response.json()
    assert set(catalog) == {'catalog_version', 'rules_version', 'key_rate', 'amount_slider', 'products', 'overlays'}
    assert 'research_items' not in catalog
    assert catalog['catalog_version'].startswith('2026-10-25.1+') and catalog['rules_version'].startswith('rules-v2+')
    assert catalog['key_rate']['value_bps'] == 1400
    assert (catalog['amount_slider']['min_rub'], catalog['amount_slider']['max_rub'], catalog['amount_slider']['default_rub']) == \
           (300_000, 2_000_000_000, 2_000_000)
    assert [product['id'] for product in catalog['products']] == catalog_oracle.CARD_IDS and len(catalog['products']) == 11
    assert [overlay['id'] for overlay in catalog['overlays']] == ['zont_corpmsp']
    for product in catalog['products']:
        expected = catalog_oracle.PRODUCTS[product['id']]
        assert (product['amount_min_rub'], product['amount_max_rub'], product['term_min_months'], product['term_max_months'],
                product['collateral_mode'], product['annual_rate_bps'], product['rate_certainty'], product['payment_model']) == \
               (expected['amount_min_rub'], expected['amount_max_rub'], expected['term_min_months'], expected['term_max_months'],
                expected['collateral_mode'], expected['annual_rate_bps'], expected['rate_certainty'], expected['payment_model'])
        assert product['display']['summary'] and product['display']['best_for'] and 3 <= len(product['display']['features']) <= 5
        assert isinstance(product['conditions_to_confirm'], list) and set(product['eligibility']) == \
               {'msp_registry_required', 'regions_allow', 'okved_denied_classes'}
        assert 'can_apply' not in product and product['applyable'] is True


@pytest.mark.parametrize('payload', [
    {'requested_amount_rub': 0}, {'requested_amount_rub': -1}, {'requested_amount_rub': True}, {'requested_amount_rub': 1.1},
    {'requested_amount_rub': '1500000'}, {'requested_amount_rub': 2_000_000_001}, {},
    {'requested_amount_rub': 1_000_000, 'purpose': 'working_capital'},
    {'requested_amount_rub': 1_000_000, 'funding_pattern': 'one_time'},
    {'requested_amount_rub': 1_000_000, 'term_months': 12},
    {'requested_amount_rub': 1_000_000, 'collateral': {'status': 'none'}},
    {'requested_amount_rub': 1_000_000, 'annual_rate_bps': 100}, {'requested_amount_rub': 1_000_000, 'products': []},
    {'requested_amount_rub': 1_000_000, 'msp_registry': True}, {'requested_amount_rub': 1_000_000, 'credit_history': 'clean'},
])
def test_the_need_is_only_a_positive_whole_amount_up_to_the_slider_maximum(client, payload):
    company = setup(client)
    assert client.post(f'/api/v1/companies/{company}/recommendations', json=payload).status_code == 422


@pytest.mark.parametrize('amount', [1, 300_000, 2_000_000_000])
def test_amounts_from_one_ruble_to_the_slider_maximum_are_compared(client, amount):
    company = setup(client)
    result = items(recommend(client, company, amount))
    assert len(result) == 11 and all(item['requested_amount_rub'] == amount for item in result.values())


def test_snapshot_and_item_contract_shape(client):
    company = setup(client)
    snapshot = body(recommend(client, company))
    assert set(snapshot) == {'snapshot_id', 'catalog_version', 'rules_version', 'items', 'created_at'}
    catalog = client.get('/api/v1/catalog').json()
    assert (snapshot['catalog_version'], snapshot['rules_version']) == (catalog['catalog_version'], catalog['rules_version'])
    assert snapshot['created_at'].endswith('Z')
    assert [item['rank'] for item in snapshot['items']] == list(range(1, 12))
    for item in snapshot['items']:
        assert set(item) == ITEM_KEYS
        assert [c['code'] for c in item['checks']] == oracle.CHECK_CODES
        assert all(c['result'] in ('passed', 'failed', 'unknown') and c['text'] for c in item['checks'])
        assert item['status'] in ('fits', 'needs_info', 'does_not_fit') and item['requested_amount_rub'] == 2_000_000
        assert item['catalog_max_rub'] == catalog_oracle.PRODUCTS[item['product_id']]['amount_max_rub']
        assert NOTICE in item['reasons'] and isinstance(item['alternatives'], list)
        assert all(set(badge) == {'overlay_id', 'name', 'text'} for badge in item['badges'])
        assert all(set(entry) == {'kind', 'text'} for entry in item['conditions_to_confirm'])


@pytest.mark.parametrize('amount', [300_000, 2_000_000, 25_000_000])
@pytest.mark.parametrize('fixture_id', list(oracle.FIXTURES))
def test_statuses_ranking_limits_payments_and_badges_match_the_independent_oracle(client, fixture_id, amount):
    fixture = oracle.FIXTURES[fixture_id]
    company = setup(client, fixture_id)
    actual = body(recommend(client, company, amount))['items']
    expected = oracle.expected(oracle.company_of(fixture), fixture['monthly_revenue_rub'], amount)
    assert [item['product_id'] for item in actual] == [row['product_id'] for row in expected]
    for item, row in zip(actual, expected):
        assert {c['code']: c['result'] for c in item['checks']} == row['checks'], item['product_id']
        assert (item['status'], item['can_apply'], item['indicative_limit_rub'], item['estimated_payment_rub']) == \
               (row['status'], row['can_apply'], row['indicative_limit_rub'], row['estimated_payment_rub']), item['product_id']
        assert [badge['overlay_id'] for badge in item['badges']] == row['badges'], item['product_id']


def test_strong_company_at_two_million_literal_order_and_payments(client):
    """Hand-derived: full-certainty rates first (23.50% term loan before the 23.50% line by policy priority, then
    24.00%), the 17% preferential PSK rate after them, undisclosed rates last among the fits."""
    company = setup(client)
    ranked = body(recommend(client, company))['items']
    assert [item['product_id'] for item in ranked if item['status'] == 'fits'] == [TERM, LINE, GOSCREDIT, PSK_WORKING, UNIVERSAL, FACTORING]
    assert [item['product_id'] for item in ranked if item['status'] == 'needs_info'] == \
           [SECURED, 'alfa_nonrevolving_line_secured', 'alfa_revolving_line_secured']
    assert [item['product_id'] for item in ranked if item['status'] == 'does_not_fit'] == [PSK_INVEST, PSK_BORDER]
    result = {item['product_id']: item for item in ranked}
    assert oracle.annuity_rub(2_000_000, 2350, 36) == 77_942 and result[TERM]['estimated_payment_rub'] == 77_942
    assert result[TERM]['payment_note'].startswith('Расчёт на сумму 2\u00a0000\u00a0000\u00a0₽, срок 36 мес. ')
    assert result[TERM]['payment_label'] is None and 'комисси' in result[TERM]['payment_note'].lower()
    assert result[LINE]['estimated_payment_rub'] == 39_167  # ceil(2,000,000 × 23.5% / 12)
    assert 'основной долг' in result[LINE]['payment_note'].lower()
    assert result[PSK_WORKING]['estimated_payment_rub'] == oracle.annuity_rub(2_000_000, 1700, 36) == 71_305
    assert result[PSK_WORKING]['payment_label'] == 'в льготный период 12 мес.'
    assert result[UNIVERSAL]['estimated_payment_rub'] is None and 'Ставка уточняется' in result[UNIVERSAL]['payment_note']
    assert result[FACTORING]['estimated_payment_rub'] is None and 'заказчик' in result[FACTORING]['payment_note']
    assert result[UNIVERSAL]['indicative_limit_rub'] == 2_400_000  # min(70m, 3 × 800k, 20m unsecured)


CERTAINTY = catalog_oracle.POLICY['ranking']['rate_certainty']


@pytest.mark.parametrize('fixture_id', list(oracle.FIXTURES))
@pytest.mark.parametrize('amount', [500_000, 2_000_000, 10_000_000])
def test_a_preferential_or_undisclosed_rate_never_tops_a_stated_full_rate_among_the_fits(client, fixture_id, amount):
    """Among fitting products (no shortfall, no required collateral) rate certainty orders first, so the sequence of
    certainties down the ranking never decreases: a preferential PSK rate never tops a full-rate product."""
    company = setup(client, fixture_id)
    fits = [item['product_id'] for item in body(recommend(client, company, amount))['items'] if item['status'] == 'fits']
    certainties = [CERTAINTY[catalog_oracle.PRODUCTS[product_id]['rate_certainty']] for product_id in fits]
    assert certainties == sorted(certainties), fits


def test_the_certainty_order_is_exercised_by_a_preferential_rate_that_fits(client):
    fits = [item['product_id'] for item in body(recommend(client, setup(client), 2_000_000))['items'] if item['status'] == 'fits']
    assert {TERM, LINE, GOSCREDIT, PSK_WORKING} <= set(fits)
    assert fits.index(PSK_WORKING) > max(fits.index(product_id) for product_id in (TERM, LINE, GOSCREDIT))


def product_edges() -> list[tuple[str, int]]:
    """Every product's inclusive amount edges (min-1, min, max, max+1) within the slider's 1 … maximum."""
    edges = set()
    for product in catalog_oracle.PRODUCTS.values():
        for amount in (product['amount_min_rub'] - 1, product['amount_min_rub'], product['amount_max_rub'], product['amount_max_rub'] + 1):
            if 1 <= amount <= catalog_oracle.POLICY['amount_slider']['max_rub']:
                edges.add(amount)
    return sorted(edges)


@pytest.mark.parametrize('amount', product_edges())
@pytest.mark.parametrize('fixture_id', ['strong', 'gov_manufacturer'])
def test_every_product_amount_edge_matches_the_independent_oracle(client, fixture_id, amount):
    """Restored inclusive coverage: e.g. 499,999/500,000 for the secured products, 24,999,999/25,000,000 for the
    investment subsidy, 30,000,000/30,000,001 for the unsecured loans; statuses, gates, limits, payments, badges."""
    fixture = oracle.FIXTURES[fixture_id]
    company = setup(client, fixture_id)
    actual = body(recommend(client, company, amount))['items']
    expected = oracle.expected(oracle.company_of(fixture), fixture['monthly_revenue_rub'], amount)
    assert [item['product_id'] for item in actual] == [row['product_id'] for row in expected]
    for item, row in zip(actual, expected):
        assert {c['code']: c['result'] for c in item['checks']} == row['checks'], item['product_id']
        assert (item['status'], item['can_apply'], item['indicative_limit_rub'], item['estimated_payment_rub']) == \
               (row['status'], row['can_apply'], row['indicative_limit_rub'], row['estimated_payment_rub']), item['product_id']
        assert [badge['overlay_id'] for badge in item['badges']] == row['badges'], item['product_id']


def test_the_edges_include_the_named_boundaries():
    assert {499_999, 500_000, 24_999_999, 25_000_000, 30_000_000, 30_000_001, 150_000_000, 150_000_001} <= set(product_edges())


OVERLAY_EDITS = {
    'inactive': lambda overlay: overlay.update(status='inactive'),
    'exhausted': lambda overlay: overlay.update(limit_status='exhausted'),
    'ip_only': lambda overlay: overlay['eligibility'].update(entity_types=['ИП']),
    'kursk_only': lambda overlay: overlay['eligibility'].update(regions_allow=['  курская   ОБЛАСТЬ ']),
}


@pytest.mark.parametrize('fixture_id', ['strong', 'medium', 'gov_manufacturer'])
@pytest.mark.parametrize('edit', list(OVERLAY_EDITS))
def test_overlay_status_entity_and_region_rules_match_the_oracle(client, monkeypatch, tmp_path, edit, fixture_id):
    from app.products_config import load_config
    from app.recommendations import catalog
    edited = json.loads(catalog_oracle.CATALOG_PATH.read_text(encoding='utf-8'))
    overlay = next(entry for entry in edited['items'] if entry['id'] == 'zont_corpmsp')
    OVERLAY_EDITS[edit](overlay)
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(catalog, 'CONFIG', load_config(path, catalog_oracle.POLICY_PATH))
    fixture = oracle.FIXTURES[fixture_id]
    company = oracle.company_of(fixture)
    shown = {pid: [badge['overlay_id'] for badge in item['badges']] for pid, item in items(recommend(client, setup(client, fixture_id))).items()}
    for product_id, product in catalog_oracle.PRODUCTS.items():
        assert shown[product_id] == oracle.badges(product, company, {'zont_corpmsp': overlay}), (product_id, edit)
    shipped = {pid: oracle.badges(product, company) for pid, product in catalog_oracle.PRODUCTS.items()}
    keeps = {'inactive': False, 'exhausted': False, 'ip_only': company['entity_type'] == 'IP',
             'kursk_only': fixture['region'] == 'Курская область'}[edit]
    assert any(shipped.values())  # the shipped overlay shows on this company's cards
    assert any(shown.values()) is keeps


def test_universal_limit_is_capped_by_its_unsecured_maximum(client):
    company = setup(client, 'gov_manufacturer')  # 3 × 12m = 36m of turnover capacity
    result = items(recommend(client, company, 30_000_000))
    assert result[UNIVERSAL]['indicative_limit_rub'] == 20_000_000 and result[UNIVERSAL]['status'] == 'does_not_fit'
    assert result[UNIVERSAL]['can_apply'] is True  # the amount is within 300k–70m; collateral can be declared later
    assert result[GOSCREDIT]['indicative_limit_rub'] == 36_000_000 and result[GOSCREDIT]['status'] == 'fits'


def test_gov_manufacturer_is_eligible_for_the_border_region_program(client):
    company = setup(client, 'gov_manufacturer')
    border = items(recommend(client, company, 20_000_000))[PSK_BORDER]
    assert {c['code']: c['result'] for c in border['checks']} == dict.fromkeys(oracle.CHECK_CODES, 'passed')
    assert border['status'] == 'fits' and border['can_apply'] is True and border['indicative_limit_rub'] == 30_000_000
    assert border['estimated_payment_rub'] == oracle.annuity_rub(20_000_000, 1400, 36)
    assert border['payment_label'] == 'в льготный период 12 мес.'
    assert [badge['overlay_id'] for badge in border['badges']] == ['zont_corpmsp']


@pytest.mark.parametrize('okved,result', [('64.19', 'failed'), ('92.11', 'failed'), ('05.10', 'failed'), ('09.90', 'failed'),
                                          ('55.10', 'passed'), ('56.10', 'passed'), ('63.11', 'passed'), ('67.00', 'passed'),
                                          (None, 'unknown'), ('xx', 'unknown')])
def test_only_leading_okved_codes_and_ranges_block_and_free_text_never_does(client, okved, result):
    company = setup(client)
    set_company(client, company, okved=okved)
    goscredit = items(recommend(client, company))[GOSCREDIT]
    assert check(goscredit, 'okved')['result'] == result
    assert goscredit['can_apply'] is (result == 'passed')
    assert goscredit['status'] == {'passed': 'fits', 'failed': 'does_not_fit', 'unknown': 'needs_info'}[result]
    assert {'kind': 'okved', 'text': 'производство и продажа подакцизных товаров (кроме ОКВЭД 55, 56)'} in goscredit['conditions_to_confirm']


@pytest.mark.parametrize('region,result', [('Курская область', 'passed'), ('  курская   ОБЛАСТЬ ', 'passed'),
                                           ('брянская область', 'passed'), ('Орловская область', 'failed'),
                                           ('Москва', 'failed'), (None, 'unknown')])
def test_region_rule_normalises_both_sides(client, region, result):
    company = setup(client, 'gov_manufacturer')
    set_company(client, company, region=region)
    border = items(recommend(client, company, 20_000_000))[PSK_BORDER]
    assert check(border, 'region')['result'] == result and border['can_apply'] is (result == 'passed')
    assert check(items(recommend(client, company, 20_000_000))[TERM], 'region')['result'] == 'passed'  # no region rule


@pytest.mark.parametrize('flag,result', [(True, 'passed'), (False, 'failed'), (None, 'unknown')])
def test_msp_registry_flag_gates_registry_only_programs(client, flag, result):
    company = setup(client)
    set_company(client, company, msp_registry=flag)
    result_items = items(recommend(client, company))
    for product_id in (GOSCREDIT, PSK_WORKING):
        assert check(result_items[product_id], 'msp_registry')['result'] == result
        assert result_items[product_id]['can_apply'] is (result == 'passed')
    assert check(result_items[TERM], 'msp_registry')['result'] == 'passed' and result_items[TERM]['can_apply'] is True
    assert bool(result_items[TERM]['badges']) is (flag is True)  # the umbrella guarantee needs the registry


def test_overlay_badges_follow_applies_to_registry_and_okved_with_softer_text_on_secured_cards(client):
    company = setup(client)
    result = items(recommend(client, company))
    headline = catalog_oracle.ITEMS['zont_corpmsp']['display']['headline']
    applies_to = catalog_oracle.ITEMS['zont_corpmsp']['display']['applies_to']
    for product_id, item in result.items():
        expected = [] if product_id not in applies_to else [{
            'overlay_id': 'zont_corpmsp', 'name': catalog_oracle.ITEMS['zont_corpmsp']['name'],
            'text': catalog_oracle.POLICY['overlay_badges']['zont_corpmsp']['text_collateral_required']
            if catalog_oracle.PRODUCTS[product_id]['collateral_mode'] == 'required' else headline}]
        assert item['badges'] == expected, product_id
    assert 'Залог не нужен' not in result[SECURED]['badges'][0]['text'] and 'Залог не нужен' in result[TERM]['badges'][0]['text']
    retail = setup(client, 'high_risk')  # main OKVED 47.11: retail is outside the umbrella, except the border program
    assert [pid for pid, item in items(recommend(client, retail)).items() if item['badges']] == [PSK_BORDER]


def test_conditions_to_confirm_are_shown_but_never_block_or_force_review(client):
    company = setup(client)
    result = items(recommend(client, company))
    assert result[GOSCREDIT]['status'] == 'fits' and result[GOSCREDIT]['conditions_to_confirm']
    catalog = {product['id']: product for product in client.get('/api/v1/catalog').json()['products']}
    assert all(result[pid]['conditions_to_confirm'] == catalog[pid]['conditions_to_confirm'] for pid in result)
    assert result[PSK_WORKING]['status'] == 'fits' and any(c['kind'] == 'category' for c in result[PSK_WORKING]['conditions_to_confirm'])
    assert result[TERM]['conditions_to_confirm'] == []


def test_payment_is_calculated_on_the_personal_limit_when_the_request_is_higher(client):
    company = setup(client)
    term = items(recommend(client, company, 2_500_000))[TERM]
    assert term['status'] == 'does_not_fit' and term['can_apply'] is True and term['indicative_limit_rub'] == 2_400_000
    assert term['estimated_payment_rub'] == oracle.annuity_rub(2_400_000, 2350, 36)
    assert 'Расчёт на сумму 2\u00a0400\u00a0000\u00a0₽' in term['payment_note']
    assert any('до 2\u00a0400\u00a0000\u00a0₽' in text for text in term['alternatives'])


def test_turnover_below_the_product_minimum_is_explained_and_can_still_draft(client):
    company = setup(client)
    set_revenue(client, company, 99_999)  # three times turnover: 299,997, just under the 300k minimum
    term = items(recommend(client, company, 300_000))[TERM]
    assert term['indicative_limit_rub'] == 299_997 and term['status'] == 'does_not_fit' and term['can_apply'] is True
    assert term['estimated_payment_rub'] is None and 'ниже минимальной суммы' in term['payment_note']
    set_revenue(client, company, 100_000)  # exactly 300,000: the minimum itself
    term = items(recommend(client, company, 300_000))[TERM]
    assert term['indicative_limit_rub'] == 300_000 and term['status'] == 'fits'
    assert term['estimated_payment_rub'] == oracle.annuity_rub(300_000, 2350, 36)


@pytest.mark.parametrize('revenue', [None, 0])
def test_unknown_or_zero_turnover_never_invents_capacity(client, revenue):
    company = setup(client)
    set_revenue(client, company, revenue)
    for item in items(recommend(client, company)).values():
        assert item['indicative_limit_rub'] is None and item['estimated_payment_rub'] is None
        assert item['status'] in ('needs_info', 'does_not_fit') and check(item, 'turnover')['result'] == 'unknown'


def test_secured_products_wait_for_collateral_from_the_questionnaire(client):
    company = setup(client)
    secured = items(recommend(client, company))[SECURED]
    assert secured['status'] == 'needs_info' and secured['can_apply'] is True and secured['indicative_limit_rub'] is None
    assert check(secured, 'collateral')['result'] == 'unknown' and check(secured, 'amount_capacity')['result'] == 'unknown'
    assert secured['estimated_payment_rub'] is None and 'залоге' in secured['payment_note']
    assert any('поручител' in text.lower() for text in secured['reasons'])
    assert any('залог' in text.lower() for text in secured['alternatives'])


@pytest.mark.parametrize('registry,status', [('inactive', 'does_not_fit'), ('unknown', 'needs_info')])
def test_registry_gates_application(client, registry, status):
    company = setup(client)
    set_company(client, company, registry_status=registry)
    term = items(recommend(client, company))[TERM]
    assert term['status'] == status and term['can_apply'] is False


def test_inactive_fixture_gives_read_only_results_with_a_failure_reason(client):
    company = setup(client, 'inactive')
    for item in items(recommend(client, company, 1_000_000)).values():
        assert item['status'] == 'does_not_fit' and item['can_apply'] is False and item['estimated_payment_rub'] is None
        assert check(item, 'company_active')['result'] == 'failed'
        assert any('прекращена' in text for text in item['reasons'])
        assert item['alternatives'] == ['Заявка недоступна для неактивной компании: выберите действующую компанию.']


def test_unavailable_registry_fixture_has_no_fit_until_retry_recovers_it(client):
    company = setup(client, 'registry_unavailable')
    before = body(recommend(client, company))
    result = {item['product_id']: item for item in before['items']}
    assert not any(item['status'] == 'fits' or item['can_apply'] for item in result.values())
    assert all(check(item, 'company_active')['result'] == 'unknown' for item in result.values())
    assert check(result[GOSCREDIT], 'msp_registry')['result'] == 'unknown' and not result[TERM]['badges']
    assert result[TERM]['status'] == 'needs_info' and result[TERM]['indicative_limit_rub'] == 2_400_000  # turnover is known
    assert any('Повторите проверку реестра' in text for text in result[TERM]['alternatives'])
    retried = client.post(f'/api/v1/companies/{company}/precheck/retry', json={'version': 1}, headers={'Idempotency-Key': 'recover'})
    assert retried.status_code == 200 and retried.json()['company']['msp_registry'] is True
    after = items(recommend(client, company))
    assert after[TERM]['status'] == 'fits' and after[TERM]['can_apply'] is True and after[TERM]['badges']
    assert check(after[GOSCREDIT], 'msp_registry')['result'] == 'passed' and after[GOSCREDIT]['status'] == 'fits'
    assert client.get(f'/api/v1/companies/{company}/recommendations/{before["snapshot_id"]}').json() == before


def test_missing_turnover_fixture_keeps_every_card_with_null_limits_and_allows_a_draft(client):
    company = setup(client, 'missing_turnover')
    before = body(recommend(client, company, 1_000_000))
    for item in before['items']:
        assert item['indicative_limit_rub'] is None and item['estimated_payment_rub'] is None
        if item['product_id'] not in (PSK_INVEST, PSK_BORDER):  # 25m minimum; Kursk-region program
            assert item['status'] == 'needs_info' and item['can_apply'] is True and item['alternatives']
            assert any('Оборот неизвестен' in text for text in item['reasons'])
    retried = client.post(f'/api/v1/companies/{company}/precheck/retry', json={'version': 1}, headers={'Idempotency-Key': 'recover'})
    assert retried.status_code == 200
    after = items(recommend(client, company, 1_000_000))
    assert after[TERM]['indicative_limit_rub'] == 2_400_000 and after[TERM]['status'] == 'fits'
    assert client.get(f'/api/v1/companies/{company}/recommendations/{before["snapshot_id"]}').json() == before


def test_high_risk_fixture_estimate_is_blind_to_credit_history(client):
    company = setup(client, 'high_risk')
    term = items(recommend(client, company, 300_000))[TERM]
    assert term['indicative_limit_rub'] == 900_000 and term['status'] == 'fits'  # BKI risk is unknown before submission
    assert not any(key in term for key in ('score', 'risk', 'approval_probability'))


def test_same_amount_returns_identical_ranked_items_in_distinct_snapshots(client):
    company = setup(client)
    first, second = body(recommend(client, company)), body(recommend(client, company))
    assert first['items'] == second['items'] and first['snapshot_id'] != second['snapshot_id']


def test_snapshots_are_owned_immutable_and_do_not_include_bki(client):
    company = setup(client)
    payload = deepcopy(body(recommend(client, company)))
    url = f'/api/v1/companies/{company}/recommendations/{payload["snapshot_id"]}'
    assert client.get(url).json() == payload
    recommend(client, company, 400_000)
    client.post(f'/api/v1/companies/{company}/precheck/retry', json={'version': 1}, headers={'Idempotency-Key': 'refresh'})
    assert client.get(url).json() == payload
    from app.recommendations.models import RecommendationSnapshot
    with client.app.state.test_factory() as db:
        row = db.get(RecommendationSnapshot, payload['snapshot_id'])
        assert row.precheck_id and row.need == {'requested_amount_rub': 2_000_000}
        assert row.input_snapshot['company']['msp_registry'] is True
        raw = json.dumps(row.input_snapshot, ensure_ascii=False).lower()
        assert 'bki' not in raw and 'credit_history' not in raw and 'score' not in raw
    client.post('/api/v1/auth/logout', json={})
    assert client.get(url).status_code == 401 and recommend(client, company).status_code == 401
    register(client, 'other@example.test')
    assert client.get(url).status_code == 404 and recommend(client, company).status_code == 404


def test_a_config_edit_without_a_version_bump_gives_new_versions_and_keeps_old_snapshots(client, monkeypatch, tmp_path):
    from app.products_config import load_config
    from app.recommendations import catalog
    company = setup(client)
    first = body(recommend(client, company, 1_000_000))
    url = f'/api/v1/companies/{company}/recommendations/{first["snapshot_id"]}'
    edited = json.loads(catalog_oracle.CATALOG_PATH.read_text(encoding='utf-8'))
    next(entry for entry in edited['items'] if entry['id'] == TERM)['rate']['periods'][0]['rate_percent'] = 30.0
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(catalog, 'CONFIG', load_config(path, catalog_oracle.POLICY_PATH))
    second = body(recommend(client, company, 1_000_000))
    assert second['catalog_version'].split('+')[0] == first['catalog_version'].split('+')[0] == '2026-10-25.1'
    assert second['catalog_version'] != first['catalog_version'] and second['rules_version'] == first['rules_version']
    term = next(item for item in second['items'] if item['product_id'] == TERM)
    assert term['estimated_payment_rub'] == oracle.annuity_rub(1_000_000, 3000, 36)
    assert client.get(url).json() == first  # served from the saved snapshot, never recomputed from live config
    assert client.get('/api/v1/catalog').json()['catalog_version'] == second['catalog_version']


def test_recommendations_never_access_bki_source_or_score(client, monkeypatch):
    company = setup(client)
    from app import companies
    from app.applications import bki

    class ForbiddenSource:
        def __getitem__(self, key):
            pytest.fail('Recommendations must not query external/source fixtures (including BKI)')

        def get(self, *args):
            pytest.fail('Recommendations must use the persisted precheck only')
    monkeypatch.setattr(companies, 'SOURCES', ForbiddenSource())
    bki.CALLS.clear()
    for amount in (300_000, 2_000_000, 25_000_000):
        result = items(recommend(client, company, amount))
        assert all(NOTICE in item['reasons'] for item in result.values())
        assert not any('score' in item or 'approval_probability' in item for item in result.values())
    assert bki.CALLS == []  # the BKI simulator's call log: no request before a consented submission


def test_snapshot_company_scope_role_and_origin(client):
    first = setup(client)
    second = add(client, oracle.FIXTURES['inactive']['inn']).json()['company']['id']
    snapshot = body(recommend(client, first))['snapshot_id']
    assert client.get(f'/api/v1/companies/{second}/recommendations/{snapshot}').status_code == 404
    missing = client.get(f'/api/v1/companies/{first}/recommendations/{uuid4()}')
    assert missing.status_code == 404 and missing.json()['error']['code'] == 'RECOMMENDATION_NOT_FOUND'
    assert client.post(f'/api/v1/companies/{first}/recommendations', json={'requested_amount_rub': 1_000_000},
                       headers={'origin': 'http://evil.test'}).status_code == 403
    from app.seed import seed_demo
    with client.app.state.test_factory.begin() as db:
        seed_demo(db, demo_mode=True)
    client.post('/api/v1/auth/login', json={'email': 'officer@demo.local', 'password': 'DemoCredit2026!'})
    assert recommend(client, first).status_code == 403
    assert client.get(f'/api/v1/companies/{first}/recommendations/{snapshot}').status_code == 403


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='row locking needs the PostgreSQL integration database')
def test_calculation_waits_for_a_concurrent_source_update_and_uses_the_new_precheck(client):
    company = setup(client)
    outcome = {}
    with client.app.state.test_factory() as updater:
        # A retry in progress: it holds the company row lock before it appends the new source data.
        updater.execute(select(Company).where(Company.id == company).with_for_update())
        worker = threading.Thread(target=lambda: outcome.update(response=recommend(client, company)))
        worker.start()
        worker.join(timeout=1)
        assert worker.is_alive(), 'the calculation must wait for the company row lock'
        updater.execute(update(Precheck).where(Precheck.company_id == company).values(monthly_revenue_rub=300_000))
        updater.commit()
    worker.join(timeout=15)
    assert not worker.is_alive()
    # Reading the source before taking the lock would still report the old 800k turnover (2.4m).
    assert items(outcome['response'])[TERM]['indicative_limit_rub'] == 900_000
