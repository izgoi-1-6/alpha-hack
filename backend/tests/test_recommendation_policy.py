"""Pure recommendation policy: the ranking key, the application gates, config-driven numbers, badges and the
exact-arithmetic payment oracles.

No HTTP and no database. Inputs are the shipped runtime products, copied and changed per test; expected orders are
derived by hand from the plan's key (status, known shortfall with unknown capacity counted as the whole request,
collateral burden, rate certainty, rate or 0, policy priority, id) and payments come from the exact oracle, never from
the service under test. A "closed" product (its program no longer accepts applications) is does_not_fit whatever its
numbers, which isolates the later parts of the key.
"""
from copy import deepcopy
from dataclasses import replace
import random
import pytest
from app.recommendations.catalog import CONFIG
from app.recommendations.service import recommend
from recommendation_oracle import annuity_rub, collateral_cap_rub, full_utilization_interest_rub

TERM, LINE, SECURED = 'alfa_term_loan_unsecured', 'alfa_revolving_line_unsecured', 'alfa_term_loan_secured'
COMPANY = {'registry_status': 'active', 'entity_type': 'LLC', 'msp_registry': True, 'region': 'Москва', 'okved': '46.90'}
RICH = {'monthly_revenue_rub': 300_000_000}  # three times turnover is above every unsecured cap
CLOSED = {'applyable': False}
GATES = ('company_active', 'entity_type', 'msp_registry', 'region', 'okved', 'program_status', 'amount_min', 'catalog_max')


def synthetic(product_id: str, template: str = TERM, **changes) -> dict:
    product = deepcopy(CONFIG.product(template))
    product.update(id=product_id, **changes)
    return product


def evaluate(products, *, company=COMPANY, precheck=RICH, amount=1_000_000, **config_changes):
    return recommend(company, precheck, {'requested_amount_rub': amount}, replace(CONFIG, products=tuple(products), **config_changes))


def order(products, **kwargs) -> list[str]:
    result = evaluate(products, **kwargs)
    assert [item['rank'] for item in result] == list(range(1, len(products) + 1))
    return [item['product_id'] for item in result]


def one(product_id=TERM, template=None, *, changes=None, **kwargs) -> dict:
    return evaluate([synthetic(product_id, template or product_id, **(changes or {}))], **kwargs)[0]


def results(item) -> dict:
    return {c['code']: c['result'] for c in item['checks']}


def texts(item) -> list[str]:
    return [item['payment_note'], *item['reasons'], *item['alternatives'], *[c['text'] for c in item['checks']],
            *[badge['text'] for badge in item['badges']]]


def test_status_precedes_shortfall_burden_and_price():
    cheap_unfit = synthetic('a_cheap_unfit', amount_min_rub=5_000_000, annual_rate_bps=100)
    needs_info = synthetic('m_needs_info', SECURED)  # no collateral stated
    fits = synthetic('z_fits')
    assert order([cheap_unfit, needs_info, fits]) == ['z_fits', 'm_needs_info', 'a_cheap_unfit']


def test_smaller_known_shortfall_ranks_first():
    larger = synthetic('z_cap_700k', unsecured_cap_rub=700_000)  # 300k short of 1m
    smaller = synthetic('a_cap_500k', unsecured_cap_rub=500_000)  # 500k short
    assert order([smaller, larger]) == ['z_cap_700k', 'a_cap_500k']


def test_unknown_capacity_counts_as_the_whole_request():
    unknown = synthetic('a_unknown', SECURED, **CLOSED)  # no collateral stated: no limit
    known = synthetic('z_known', unsecured_cap_rub=700_000, **CLOSED)  # 300k short
    result = evaluate([unknown, known])
    assert [(item['product_id'], item['status'], item['indicative_limit_rub']) for item in result] == \
           [('z_known', 'does_not_fit', 700_000), ('a_unknown', 'does_not_fit', None)]


def test_shortfall_precedes_collateral_burden():
    burdened = synthetic('z_optional_no_shortfall', collateral_mode='optional', **CLOSED)
    short = synthetic('a_short', unsecured_cap_rub=600_000, **CLOSED)
    ranking = {**CONFIG.ranking, 'collateral_burden': {'none': 0, 'optional': 1, 'required': 1}}
    assert order([short, burdened], ranking=ranking) == ['z_optional_no_shortfall', 'a_short']


def test_collateral_burden_precedes_rate_certainty_and_price():
    burdened = synthetic('a_optional_full', collateral_mode='optional', annual_rate_bps=1000)
    undisclosed = synthetic('z_none_undisclosed', rate_certainty='undisclosed', annual_rate_bps=None)
    ranking = {**CONFIG.ranking, 'collateral_burden': {'none': 0, 'optional': 1, 'required': 1}}
    assert order([burdened, undisclosed], ranking=ranking) == ['z_none_undisclosed', 'a_optional_full']


def test_rate_certainty_precedes_a_lower_preferential_rate():
    preferential = synthetic('a_preferential_cheap', rate_certainty='preferential', rate_preferential_months=12, annual_rate_bps=1000)
    full = synthetic('z_full_dear', annual_rate_bps=3000)
    undisclosed = synthetic('m_undisclosed', rate_certainty='undisclosed', annual_rate_bps=None)
    assert order([undisclosed, preferential, full]) == ['z_full_dear', 'a_preferential_cheap', 'm_undisclosed']


def test_rate_then_policy_priority_then_id_break_the_remaining_ties():
    assert order([synthetic('a_dear', annual_rate_bps=2500, priority=1), synthetic('z_cheap', annual_rate_bps=2000, priority=99)]) == \
           ['z_cheap', 'a_dear']
    assert order([synthetic('a_later', priority=20), synthetic('z_sooner', priority=10)]) == ['z_sooner', 'a_later']
    assert order([synthetic('z_same'), synthetic('a_same')]) == ['a_same', 'z_same']
    undisclosed = {'rate_certainty': 'undisclosed', 'annual_rate_bps': None}
    assert order([synthetic('a_u', priority=7, **undisclosed), synthetic('z_u', priority=3, **undisclosed)]) == ['z_u', 'a_u']


def test_headroom_above_the_request_never_reorders_fitting_products():
    cheaper_smaller = synthetic('z_cheaper', unsecured_cap_rub=1_500_000, annual_rate_bps=2000)  # 500k of headroom
    dearer_larger = synthetic('a_dearer', unsecured_cap_rub=3_000_000, annual_rate_bps=2500)  # 2m of headroom
    result = evaluate([dearer_larger, cheaper_smaller])
    assert [(item['product_id'], item['status']) for item in result] == [('z_cheaper', 'fits'), ('a_dearer', 'fits')]


@pytest.mark.parametrize('company,revenue,amount', [
    (COMPANY, 800_000, 2_000_000), (COMPANY, 800_000, 300_000), (COMPANY, None, 1_000_000),
    ({**COMPANY, 'msp_registry': None, 'registry_status': 'unknown'}, 800_000, 25_000_000),
    ({**COMPANY, 'region': 'Курская область', 'okved': '47.11'}, 12_000_000, 20_000_000),
])
def test_input_order_never_changes_the_ranking(company, revenue, amount):
    products = list(CONFIG.products)
    expected = order(products, company=company, precheck={'monthly_revenue_rub': revenue}, amount=amount)
    shuffler = random.Random(20261025)
    for _ in range(30):
        shuffled = products[:]
        shuffler.shuffle(shuffled)
        assert order(shuffled, company=company, precheck={'monthly_revenue_rub': revenue}, amount=amount) == expected


@pytest.mark.parametrize('estimate,months', [(1, 12), (12, 12), (36, 36), (60, 60), (120, 60)])
def test_term_loan_payment_is_the_exact_annuity_over_the_estimate_term_clamped_to_the_product(estimate, months):
    for amount in (300_000, 333_333, 1_000_000, 1_234_567, 29_999_999, 30_000_000):
        item = one(TERM, amount=amount, payment_estimate_term_months=estimate)
        assert item['estimated_payment_rub'] == annuity_rub(amount, 2350, months), (amount, estimate)
        # Money in server texts keeps its digit groups and the sign together: non-breaking spaces (U+00A0).
        money = f'{amount:,}'.replace(',', '\u00a0')
        assert item['payment_note'].startswith(f'Расчёт на сумму {money}\u00a0₽, срок {months} мес. ')


def test_revolving_payment_is_the_ceiling_of_full_utilization_interest():
    for amount in (300_000, 333_333, 1_000_000, 2_999_999, 30_000_000):
        item = one(LINE, amount=amount)
        assert item['estimated_payment_rub'] == full_utilization_interest_rub(amount, 2350), amount
        assert 'основной долг' in item['payment_note'].lower() and 'срок' not in item['payment_note'].split('.')[0]
    line_23 = synthetic('line_23', LINE, annual_rate_bps=2300)  # 23% a year is a repeating decimal per month
    for amount in (360_000, 600_000, 1_200_000):
        assert evaluate([line_23], amount=amount)[0]['estimated_payment_rub'] == amount * 23 // 1200 == \
               full_utilization_interest_rub(amount, 2300)


def test_an_interest_free_rate_repays_the_amount_in_equal_parts():
    item = one('free', TERM, changes={'annual_rate_bps': 0}, amount=1_000_000)
    assert item['estimated_payment_rub'] == annuity_rub(1_000_000, 0, 36) == 27_778  # 1m / 36, half up
    line = one('free_line', LINE, changes={'annual_rate_bps': 0})
    assert line['estimated_payment_rub'] == 0


def test_a_preferential_rate_labels_its_payment_with_the_period():
    item = one('psk_working_capital', amount=2_000_000)
    assert item['estimated_payment_rub'] == annuity_rub(2_000_000, 1700, 36)
    assert item['payment_label'] == 'в льготный период 12 мес.' and 'льготн' in item['payment_note']
    assert one(TERM)['payment_label'] is None


def test_the_oracle_is_anchored_to_published_examples():
    assert annuity_rub(1_000_000, 2350, 12) == 94_318  # acceptance.md: 1m / 12 months / 23.50%
    assert full_utilization_interest_rub(1_000_000, 2400) == 20_000  # acceptance.md: 1m at 24%
    assert collateral_cap_rub(714_285, 7000) == 499_999 and collateral_cap_rub(714_286, 7000) == 500_000


def test_estimates_follow_the_config_not_code_constants():
    turnover = {'monthly_revenue_rub': 1_000_000}
    assert one(TERM, precheck=turnover)['indicative_limit_rub'] == 3_000_000  # min(30m, 3 × 1m, 30m)
    assert one('two_x', TERM, changes={'low_risk_revenue_multiple': 2}, precheck=turnover)['indicative_limit_rub'] == 2_000_000
    assert one('capped', TERM, changes={'unsecured_cap_rub': 1_200_000}, precheck=turnover)['indicative_limit_rub'] == 1_200_000
    assert one('universal', 'alfa_universal_limit', precheck=RICH)['indicative_limit_rub'] == 20_000_000  # its unsecured cap
    assert one('repriced', TERM, changes={'annual_rate_bps': 3000})['estimated_payment_rub'] == annuity_rub(1_000_000, 3000, 36)
    assert one(TERM, payment_estimate_term_months=24)['estimated_payment_rub'] == annuity_rub(1_000_000, 2350, 24)


def test_credit_history_inputs_never_change_recommendations():
    plain = evaluate(CONFIG.products, precheck={'monthly_revenue_rub': 800_000})
    noisy_company = {**COMPANY, 'credit_history': 'serious', 'current_overdue_days': 90, 'bki_source_status': 'unavailable'}
    noisy_precheck = {'monthly_revenue_rub': 800_000, 'credit_history': 'serious', 'score': 0, 'risk': 'high', 'approval_probability': 0.01}
    assert evaluate(CONFIG.products, company=noisy_company, precheck=noisy_precheck) == plain
    assert not any(key in item for item in plain for key in ('score', 'risk', 'approval_probability'))


@pytest.mark.parametrize('gate,company,changes,amount', [
    ('company_active', {**COMPANY, 'registry_status': 'unknown'}, {}, 1_000_000),
    ('company_active', {**COMPANY, 'registry_status': 'inactive'}, {}, 1_000_000),
    ('entity_type', {**COMPANY, 'entity_type': 'IP'}, {'entity_types': ['LLC']}, 1_000_000),
    ('msp_registry', {**COMPANY, 'msp_registry': False}, {'eligibility': {'msp_registry_required': True, 'regions_allow': [], 'okved_denied_classes': []}}, 1_000_000),
    ('msp_registry', {**COMPANY, 'msp_registry': None}, {'eligibility': {'msp_registry_required': True, 'regions_allow': [], 'okved_denied_classes': []}}, 1_000_000),
    ('region', COMPANY, {'eligibility': {'msp_registry_required': False, 'regions_allow': ['Курская область'], 'okved_denied_classes': []}}, 1_000_000),
    ('okved', COMPANY, {'eligibility': {'msp_registry_required': False, 'regions_allow': [], 'okved_denied_classes': ['46']}}, 1_000_000),
    ('okved', {**COMPANY, 'okved': None}, {'eligibility': {'msp_registry_required': False, 'regions_allow': [], 'okved_denied_classes': ['46']}}, 1_000_000),
    ('program_status', COMPANY, CLOSED, 1_000_000),
    ('amount_min', COMPANY, {}, 299_999),
    ('catalog_max', COMPANY, {}, 30_000_001),
])
def test_every_application_gate_blocks_can_apply(gate, company, changes, amount):
    item = one('gated', TERM, changes=changes, company=company, amount=amount)
    assert results(item)[gate] != 'passed' and item['can_apply'] is False
    others = [code for code in GATES if code != gate]
    assert all(results(item)[code] == 'passed' for code in others), results(item)


@pytest.mark.parametrize('revenue,template,amount', [(None, TERM, 1_000_000), (0, TERM, 1_000_000), (800_000, TERM, 5_000_000),
                                                     (800_000, SECURED, 1_000_000), (99_999, TERM, 300_000)])
def test_capacity_turnover_and_collateral_gaps_never_block_a_draft(revenue, template, amount):
    item = one('draftable', template, precheck={'monthly_revenue_rub': revenue}, amount=amount)
    assert item['status'] != 'fits' and item['can_apply'] is True


def test_a_closed_program_is_shown_but_cannot_be_applied_for():
    item = one('exhausted', TERM, changes={'applyable': False, 'limit_status': 'exhausted'})
    assert results(item)['program_status'] == 'failed' and item['status'] == 'does_not_fit' and item['can_apply'] is False
    assert item['estimated_payment_rub'] is None


def test_missing_payment_always_explains_why():
    inactive = one(company={**COMPANY, 'registry_status': 'inactive'})
    assert inactive['estimated_payment_rub'] is None and 'не действует' in inactive['payment_note']
    elsewhere = one('psk_borderline', amount=2_000_000)  # a Moscow company and a Kursk-region program
    assert elsewhere['estimated_payment_rub'] is None and 'не соответствуют условиям продукта' in elsewhere['payment_note']
    factoring = one('alfa_factoring')
    assert factoring['estimated_payment_rub'] is None and 'заказчик' in factoring['payment_note']
    undisclosed = one('alfa_universal_limit')
    assert undisclosed['estimated_payment_rub'] is None and undisclosed['payment_note'].startswith('Ставка уточняется')
    no_turnover = one(precheck={'monthly_revenue_rub': None})
    assert no_turnover['estimated_payment_rub'] is None
    assert 'личный лимит пока неизвестен' in no_turnover['payment_note'] and 'обороте' in no_turnover['payment_note']
    no_collateral = one(SECURED)
    assert no_collateral['estimated_payment_rub'] is None
    assert 'залоге' in no_collateral['payment_note'] and 'обороте' not in no_collateral['payment_note']
    below_minimum = one(precheck={'monthly_revenue_rub': 99_999}, amount=300_000)
    assert below_minimum['estimated_payment_rub'] is None and 'ниже минимальной суммы' in below_minimum['payment_note']


def test_unconfirmed_registry_keeps_indicative_numbers_but_blocks_application():
    unknown = one(company={**COMPANY, 'registry_status': 'unknown'})
    assert unknown['status'] == 'needs_info' and unknown['can_apply'] is False
    assert unknown['indicative_limit_rub'] == 30_000_000 and unknown['estimated_payment_rub'] == annuity_rub(1_000_000, 2350, 36)
    assert any('Повторите проверку реестра' in text for text in unknown['alternatives'])
    inactive = one(company={**COMPANY, 'registry_status': 'inactive'})
    assert inactive['status'] == 'does_not_fit' and inactive['can_apply'] is False
    assert inactive['alternatives'] == ['Заявка недоступна для неактивной компании: выберите действующую компанию.']


def test_capacity_below_the_minimum_is_not_described_as_a_smaller_amount_to_consider():
    item = one(precheck={'monthly_revenue_rub': 99_999}, amount=300_000)
    capacity = next(c for c in item['checks'] if c['code'] == 'amount_capacity')
    assert item['indicative_limit_rub'] == 299_997 and capacity['result'] == 'failed' and item['status'] == 'does_not_fit'
    assert 'минимальной суммы' in capacity['text']
    assert not any('меньшей суммы' in text for text in [capacity['text'], *item['reasons']])
    assert any('минимальной суммы' in text for text in item['alternatives'])


def test_a_shortfall_within_range_suggests_the_supported_amount():
    item = one(precheck={'monthly_revenue_rub': 800_000}, amount=2_500_000)
    capacity = next(c for c in item['checks'] if c['code'] == 'amount_capacity')
    assert item['indicative_limit_rub'] == 2_400_000 and 'меньшей суммы' in capacity['text']
    assert any('до 2\u00a0400\u00a0000\u00a0₽' in text for text in item['alternatives'])


def test_an_eligibility_failure_points_to_other_products():
    item = one('psk_borderline', amount=2_000_000)
    assert results(item)['region'] == 'failed'
    assert any('другие продукты' in text for text in item['alternatives'])
    assert any('Курская область' in c['text'] for c in item['checks'] if c['code'] == 'region')


def test_a_fitting_product_still_says_the_decision_comes_after_submission():
    item = one()
    assert item['status'] == 'fits'
    assert any('Решение принимается после отправки заявки' in text for text in item['reasons'])
    assert any('не предодобрение' in text for text in item['reasons'])


@pytest.mark.parametrize('company,revenue,amount', [
    (COMPANY, 800_000, 2_000_000), (COMPANY, 800_000, 25_000_000), (COMPANY, None, 1_000_000), (COMPANY, 99_999, 300_000),
    ({**COMPANY, 'registry_status': 'inactive'}, 800_000, 1_000_000),
    ({**COMPANY, 'registry_status': 'unknown', 'msp_registry': None, 'region': None, 'okved': None}, 800_000, 1),
    ({**COMPANY, 'region': 'Курская область', 'okved': '47.11'}, 12_000_000, 2_000_000_000),
])
def test_texts_are_clean_russian_sentences_that_never_promise_approval(company, revenue, amount):
    promises = ('вероятност', 'гарантир', 'будет одобрен', 'одобрено', 'шанс', 'демо', 'имитац')
    for item in evaluate(CONFIG.products, company=company, precheck={'monthly_revenue_rub': revenue}, amount=amount):
        for text in texts(item):
            assert text == text.strip() and '  ' not in text and ' ,' not in text and text, (item['product_id'], text)
            assert not any(word in text.lower() for word in promises), (item['product_id'], text)


def test_badges_need_the_registry_and_an_allowed_main_okved():
    products = [CONFIG.product(pid) for pid in (TERM, SECURED, 'psk_borderline', 'alfa_universal_limit')]
    overlay = CONFIG.overlays[0]
    shown = {item['product_id']: [badge['text'] for badge in item['badges']] for item in evaluate(products)}
    assert shown == {TERM: [overlay['badge_text']], SECURED: [overlay['badge_text_collateral_required']],
                     'psk_borderline': [overlay['badge_text']], 'alfa_universal_limit': []}
    assert all(not item['badges'] for item in evaluate(products, company={**COMPANY, 'msp_registry': None}))
    retail = evaluate(products, company={**COMPANY, 'okved': '47.11'})
    assert [item['product_id'] for item in retail if item['badges']] == ['psk_borderline']  # exempt from the 47 rule
    assert [item['product_id'] for item in evaluate(products, company={**COMPANY, 'okved': None}) if item['badges']] == ['psk_borderline']


def test_money_in_server_texts_uses_non_breaking_spaces():
    """A server text never wraps inside an amount: digit groups and the ruble sign are joined by U+00A0, wherever the
    shared helper writes money (cards, scoring reasons, notifications, officer bounds)."""
    from app.recommendations.service import rub
    assert rub(500) == '500\u00a0₽'
    assert rub(1_000_000) == '1\u00a0000\u00a0000\u00a0₽'
    assert rub(2_000_000_000) == '2\u00a0000\u00a0000\u00a0000\u00a0₽'
    item = one(precheck={'monthly_revenue_rub': 800_000}, amount=2_500_000)
    for text in [item['payment_note'], *item['alternatives'], *(check['text'] for check in item['checks'])]:
        assert ' ₽' not in text and not any(f'{d} {e}' in text for d in '0123456789' for e in '0123456789'), text
