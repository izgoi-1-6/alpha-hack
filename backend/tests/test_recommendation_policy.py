"""Pure recommendation policy: ordering, policy-driven numbers and exact-arithmetic payment oracles.

No HTTP and no database. Expected orders are derived by hand from the spec's sort tuple
(status, purpose mismatch, pattern mismatch, amount shortfall, collateral requirement, rate, id) and expected
payments come from the exact rational oracle, never from the service under test.
"""
from copy import deepcopy
from itertools import permutations
import pytest
from app.recommendations.service import recommend
from recommendation_oracle import PRODUCTS, annuity_rub, collateral_cap_rub, full_utilization_interest_rub

TERM, LINE, SECURED = 'alfa_term_loan_unsecured', 'alfa_revolving_line_unsecured', 'alfa_term_loan_secured'
ACTIVE = {'registry_status': 'active', 'entity_type': 'LLC'}
RICH = {'monthly_revenue_rub': 30_000_000}  # three times turnover never binds below any ceiling
NEED = {'purpose': 'working_capital', 'funding_pattern': 'one_time', 'requested_amount_rub': 1_000_000,
        'term_months': 12, 'collateral': None}
DECLARED = {'status': 'declared', 'type': 'equipment', 'declared_value_rub': 10_000_000,
            'description': 'Демо оборудование', 'owner_confirmed': True, 'encumbered': False}


def synthetic(product_id, template=TERM, **changes):
    product = deepcopy(PRODUCTS[template])
    product.update(id=product_id, **changes)
    return product


def evaluate(products, *, company=ACTIVE, precheck=RICH, **need):
    return recommend(company, precheck, {**NEED, **need}, products)


def order(products, **kwargs):
    result = evaluate(products, **kwargs)
    assert [i['rank'] for i in result] == list(range(1, len(products) + 1))
    return [i['product_id'] for i in result]


def one(product_id, template=TERM, *, company=ACTIVE, precheck=RICH, **need):
    """The single evaluated item for a (possibly modified) product."""
    return evaluate([synthetic(product_id, template)], company=company, precheck=precheck, **need)[0]


def test_status_precedes_price_and_identifier():
    cheap_unfit = synthetic('a_cheap_unfit', purposes=['investment'], annual_rate_bps=100)
    needs_info = synthetic('m_needs_info', SECURED)  # no collateral stated
    fits = synthetic('z_fits')
    assert order([cheap_unfit, needs_info, fits]) == ['z_fits', 'm_needs_info', 'a_cheap_unfit']


def test_purpose_mismatch_precedes_pattern_mismatch_within_a_status():
    wrong_purpose = synthetic('a_wrong_purpose', purposes=['investment'])
    wrong_term_and_pattern = synthetic('z_wrong_term', preferred_funding_pattern='repeated',
                                       term_min_months=24, term_max_months=36)
    assert order([wrong_purpose, wrong_term_and_pattern]) == ['z_wrong_term', 'a_wrong_purpose']


def test_pattern_mismatch_precedes_amount_shortfall():
    short = synthetic('z_short', amount_max_rub=600_000)  # 1m asked: shortfall 400k, pattern preferred
    off_pattern = synthetic('a_off_pattern', preferred_funding_pattern='repeated', term_min_months=24,
                            term_max_months=36)  # shortfall 0 but the other funding pattern
    assert order([off_pattern, short]) == ['z_short', 'a_off_pattern']


def test_smaller_known_shortfall_ranks_first():
    larger_limit = synthetic('z_limit_700k', amount_max_rub=700_000)  # shortfall 300k
    smaller_limit = synthetic('a_limit_500k', amount_max_rub=500_000)  # shortfall 500k
    assert order([smaller_limit, larger_limit]) == ['z_limit_700k', 'a_limit_500k']


def test_unknown_capacity_counts_as_the_whole_request_when_ranking_shortfalls():
    unknown_capacity = synthetic('a_unknown', SECURED, term_min_months=24, term_max_months=36)  # no collateral stated
    known_shortfall = synthetic('z_known', amount_max_rub=700_000)  # 300k short of the 1m asked
    result = evaluate([unknown_capacity, known_shortfall])
    by_id = {i['product_id']: i for i in result}
    assert by_id['a_unknown']['status'] == by_id['z_known']['status'] == 'does_not_fit'
    assert by_id['a_unknown']['indicative_limit_rub'] is None and by_id['z_known']['indicative_limit_rub'] == 700_000
    assert [i['product_id'] for i in result] == ['z_known', 'a_unknown']


def test_shortfall_precedes_collateral_requirement_and_price():
    secured_wrong_term = synthetic('z_secured', SECURED, annual_rate_bps=1000, term_min_months=24,
                                   term_max_months=36)  # shortfall 0, needs collateral, cheapest
    unsecured_short = synthetic('a_unsecured_short', amount_max_rub=600_000)  # shortfall 400k
    assert order([unsecured_short, secured_wrong_term], collateral=DECLARED) == ['z_secured', 'a_unsecured_short']


def test_unsecured_precedes_cheaper_secured_when_both_fit():
    cheaper_secured = synthetic('a_secured', SECURED, annual_rate_bps=1000)
    unsecured = synthetic('z_unsecured')
    result = evaluate([cheaper_secured, unsecured], collateral=DECLARED)
    assert [(i['product_id'], i['status']) for i in result] == [('z_unsecured', 'fits'), ('a_secured', 'fits')]


def test_headroom_above_the_request_never_reorders_fitting_products():
    cheaper_smaller_limit = synthetic('z_cheaper', amount_max_rub=1_500_000, annual_rate_bps=2000)  # 500k of headroom
    dearer_larger_limit = synthetic('a_dearer', amount_max_rub=3_000_000, annual_rate_bps=2500)  # 2m of headroom
    result = evaluate([dearer_larger_limit, cheaper_smaller_limit])
    assert [i['status'] for i in result] == ['fits', 'fits']  # shortfall is max(0, request - limit): zero for both
    assert [i['product_id'] for i in result] == ['z_cheaper', 'a_dearer']


def test_a_product_that_cannot_accept_applications_never_offers_one():
    informational = evaluate([synthetic('research_only', can_apply=False)])[0]
    assert informational['status'] == 'fits' and informational['can_apply'] is False


def test_lower_rate_then_product_id_break_remaining_ties():
    assert order([synthetic('a_dear', annual_rate_bps=2500), synthetic('z_cheap', annual_rate_bps=2000)]) == ['z_cheap', 'a_dear']
    assert order([synthetic('z_same'), synthetic('a_same')]) == ['a_same', 'z_same']


@pytest.mark.parametrize('need', [
    {},
    {'funding_pattern': 'repeated', 'requested_amount_rub': 500_000, 'collateral': DECLARED},
    {'purpose': 'investment', 'term_months': 36, 'requested_amount_rub': 4_000_000, 'collateral': DECLARED},
    {'requested_amount_rub': 2_500_000, 'term_months': 40},
])
def test_input_order_never_changes_the_ranking(need):
    products = list(PRODUCTS.values())
    expected = order(products, **need)
    assert all(order(list(shuffled), **need) == expected for shuffled in permutations(products))


@pytest.mark.parametrize('product_id,amounts,terms', [
    (TERM, [300_000, 333_333, 1_000_000, 1_234_567, 2_999_999, 3_000_000], [6, 7, 12, 24, 36]),
    (SECURED, [500_000, 777_777, 1_500_000, 4_000_000, 6_000_000], [12, 13, 36, 60]),
])
def test_term_loan_payment_matches_exact_rational_annuity(product_id, amounts, terms):
    product = PRODUCTS[product_id]
    for amount in amounts:
        for months in terms:
            item = one(product_id, product_id, requested_amount_rub=amount, term_months=months, collateral=DECLARED)
            assert item['estimated_payment_rub'] == annuity_rub(amount, product['annual_rate_bps'], months), (amount, months)


def test_revolving_payment_is_ceiling_of_full_utilization_interest():
    for amount in [300_000, 333_333, 1_000_000, 2_999_999, 3_000_000]:
        item = one(LINE, LINE, funding_pattern='repeated', requested_amount_rub=amount, term_months=12)
        assert item['estimated_payment_rub'] == full_utilization_interest_rub(amount, 2400), amount
        assert 'основной долг' in item['payment_note'].lower()


def test_revolving_interest_is_exact_when_the_total_is_a_whole_ruble_amount():
    # 23% a year is a repeating decimal per month; a rounded monthly rate must not push an exact total up a ruble.
    line = synthetic('line_23', LINE, annual_rate_bps=2300)
    for amount in (360_000, 600_000, 1_200_000):
        item = evaluate([line], funding_pattern='repeated', requested_amount_rub=amount)[0]
        assert item['estimated_payment_rub'] == full_utilization_interest_rub(amount, 2300) == amount * 23 // 1200, amount


def test_oracle_is_anchored_to_the_specs_published_examples():
    assert annuity_rub(1_000_000, 2350, 12) == 94_318  # acceptance.md: 1m / 12 months / 23.50%
    assert full_utilization_interest_rub(1_000_000, 2400) == 20_000  # acceptance.md: 1m at 24%
    assert collateral_cap_rub(714_285, 7000) == 499_999 and collateral_cap_rub(714_286, 7000) == 500_000


def test_credit_history_inputs_never_change_recommendations():
    plain = evaluate(list(PRODUCTS.values()), collateral=DECLARED)
    noisy_company = {**ACTIVE, 'credit_history': 'serious', 'current_overdue_days': 90, 'bki_source_status': 'unavailable'}
    noisy_precheck = {**RICH, 'credit_history': 'serious', 'score': 0, 'risk': 'high', 'approval_probability': 0.01}
    assert evaluate(list(PRODUCTS.values()), company=noisy_company, precheck=noisy_precheck, collateral=DECLARED) == plain
    assert not any(key in item for item in plain for key in ('score', 'risk', 'approval_probability'))


def test_estimates_follow_the_policy_config_not_code_constants():
    turnover = {'monthly_revenue_rub': 1_000_000}
    assert one('three_x', precheck=turnover)['indicative_limit_rub'] == 3_000_000  # min(3m ceiling, 3 x 1m)
    two_x = evaluate([synthetic('two_x', low_risk_revenue_multiple=2)], precheck=turnover)[0]
    assert two_x['indicative_limit_rub'] == 2_000_000
    half = evaluate([synthetic('half_ltv', SECURED, collateral_ltv_bps=5000)], collateral={**DECLARED, 'declared_value_rub': 1_000_000},
                    requested_amount_rub=500_000)[0]
    assert half['indicative_limit_rub'] == 500_000 and half['status'] == 'fits'
    repriced = evaluate([synthetic('repriced', annual_rate_bps=3000)])[0]
    assert repriced['estimated_payment_rub'] == annuity_rub(1_000_000, 3000, 12)


def test_revolving_note_states_the_configured_draw_and_renewal_assumptions():
    line = synthetic('custom_line', LINE)
    line['revolving_assumptions'] = {**line['revolving_assumptions'], 'minimum_draw_rub': 75_000, 'auto_renewal': True}
    note = evaluate([line], funding_pattern='repeated')[0]['payment_note']
    assert '75 000 ₽' in note and '50 000' not in note and 'с автопродлением' in note and 'без автопродления' not in note
    default = one('default_line', LINE, funding_pattern='repeated')['payment_note']
    assert '50 000 ₽' in default and 'без автопродления' in default


def test_texts_are_clean_russian_sentences_with_money_formatting():
    item = one('clean', requested_amount_rub=1_500_000)
    assert item['payment_note'].startswith('Расчёт на сумму 1 500 000 ₽, срок 12 мес. ')
    for product in PRODUCTS:
        for result in evaluate([PRODUCTS[product]], collateral=DECLARED):
            texts = [result['payment_note'], *result['reasons'], *result['alternatives'], *[c['text'] for c in result['checks']]]
            assert all(text == text.strip() and '  ' not in text and ' ,' not in text for text in texts), texts


def test_a_fitting_product_still_says_the_decision_comes_after_submission():
    item = one('fitting')
    assert item['status'] == 'fits'
    assert any('Решение принимается после отправки заявки' in text for text in item['reasons'])
    assert any('не предодобрение' in text for text in item['reasons'])


def test_no_text_promises_approval_or_states_a_probability():
    promises = ('вероятност', 'гарантир', 'будет одобрен', 'одобрено', 'шанс')
    for need in ({}, {'collateral': DECLARED}, {'requested_amount_rub': 5_000_000}, {'purpose': 'investment'}):
        for item in evaluate(list(PRODUCTS.values()), **need):
            text = ' '.join([item['payment_note'], *item['reasons'], *item['alternatives'], *[c['text'] for c in item['checks']]]).lower()
            assert not any(word in text for word in promises), (need, item['product_id'], text)


def test_capacity_below_product_minimum_is_not_described_as_a_smaller_amount_to_consider():
    item = one('tiny', precheck={'monthly_revenue_rub': 99_999}, requested_amount_rub=300_000)
    capacity = next(c for c in item['checks'] if c['code'] == 'amount_capacity')
    assert item['indicative_limit_rub'] == 299_997 and capacity['result'] == 'failed' and item['status'] == 'does_not_fit'
    assert 'минимальной суммы' in capacity['text']
    assert not any('меньшей суммы' in text for text in [capacity['text'], *item['reasons']])
    assert any('минимальной суммы' in text for text in item['alternatives'])
    assert item['can_apply'] is True  # a draft may still be started and rejected by the later rules


def test_shortfall_within_range_suggests_the_supported_amount():
    item = one('short', precheck={'monthly_revenue_rub': 800_000}, requested_amount_rub=2_500_000)
    capacity = next(c for c in item['checks'] if c['code'] == 'amount_capacity')
    assert item['indicative_limit_rub'] == 2_400_000 and 'меньшей суммы' in capacity['text']
    assert any('до 2 400 000 ₽' in text for text in item['alternatives'])


def test_missing_payment_always_explains_why():
    inactive = one('inactive', company={'registry_status': 'inactive', 'entity_type': 'LLC'})
    assert inactive['estimated_payment_rub'] is None and 'не действует' in inactive['payment_note']
    incompatible = one('long_term', term_months=120)
    assert incompatible['estimated_payment_rub'] is None and 'не соответствуют условиям продукта' in incompatible['payment_note']
    no_turnover = one('no_turnover', precheck={'monthly_revenue_rub': None})
    assert no_turnover['estimated_payment_rub'] is None
    assert 'личный лимит пока неизвестен' in no_turnover['payment_note'] and 'обороте' in no_turnover['payment_note']
    no_collateral = one('no_collateral', SECURED)
    assert no_collateral['estimated_payment_rub'] is None
    assert 'залоге' in no_collateral['payment_note'] and 'обороте' not in no_collateral['payment_note']
    below_minimum = one('below_min', precheck={'monthly_revenue_rub': 99_999}, requested_amount_rub=300_000)
    assert below_minimum['estimated_payment_rub'] is None and 'ниже минимальной суммы' in below_minimum['payment_note']


def test_unconfirmed_registry_keeps_indicative_numbers_but_blocks_application():
    unknown = one('registry_unknown', company={'registry_status': 'unknown', 'entity_type': 'LLC'})
    assert unknown['status'] == 'needs_info' and unknown['can_apply'] is False
    assert unknown['indicative_limit_rub'] == 3_000_000  # turnover is known: min(3m ceiling, 3 x 30m)
    assert unknown['estimated_payment_rub'] == annuity_rub(1_000_000, 2350, 12)
    assert any('Повторите проверку реестра' in text for text in unknown['alternatives'])
    inactive = one('inactive', company={'registry_status': 'inactive', 'entity_type': 'LLC'})
    assert inactive['status'] == 'does_not_fit' and inactive['can_apply'] is False
    assert any('действующ' in text for text in inactive['alternatives'])
    assert not any('измените параметры потребности' in text for text in inactive['alternatives'])
