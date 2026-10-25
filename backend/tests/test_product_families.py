"""One end-to-end submission per product family over HTTP + DB (term loan, revolving line, secured loan, universal limit
with and without its optional pledge, factoring, gov programs with `gov_manufacturer`), the officer's preapproval and
final bounds per product, the documents of the pinned list, R7 against effective minimums and the limit edges of the
universal limit, factoring and the medium-risk cap on gov programs.

Every expected score, limit, rule, amount and document comes from application_oracle (exact fractions, its own reading
of the data files) and is cross-checked with a literal number where the acceptance document states one.
"""
from datetime import date
import pytest
import application_oracle as oracle
from application_helpers import (FIXED_DATE, LINE, SECURED, TERM, bki_calls, clock, declared_collateral, need_of, onboard,
                                 rows, set_turnover, submitted)
from document_helpers import accept_all, checklist, completed, storage, upload_all
from officer_helpers import claimed, detail, officer, ok, preapprove, refused
from recommendation_oracle import FIXTURES, PRODUCTS
from test_identity_company import client

pytestmark = pytest.mark.usefixtures('clock')
GOSCREDIT, UNIVERSAL, FACTORING = 'alfa_goscredit_zont', 'alfa_universal_limit', 'alfa_factoring'
PSK_INVEST, PSK_WORKING, PSK_BORDER = 'psk_invest_subsidy', 'psk_working_capital', 'psk_borderline'
MANUFACTURER = 'gov_manufacturer'
PLEDGE = declared_collateral(10_000_000, type='real_estate', description='Производственный цех')
TAX_DEBT = {'tax_debt_rub': 1}  # a declared tax debt routes the case to review (R5)

# family: (fixture, product, stage-2 changes to the fixture's need)
FAMILIES = {
    'term': ('strong', TERM, {}),
    'line': ('medium', LINE, {}),
    'secured': ('secured_investment', SECURED, {}),
    'universal': (MANUFACTURER, UNIVERSAL, {'purpose': 'working_capital', 'requested_amount_rub': 25_000_000}),
    'universal_pledged': (MANUFACTURER, UNIVERSAL, {'purpose': 'working_capital', 'requested_amount_rub': 25_000_000,
                                                    'collateral': PLEDGE}),
    'factoring': ('strong', FACTORING, {}),
    'gov_border': (MANUFACTURER, PSK_BORDER, {}),
    'gov_invest': (MANUFACTURER, PSK_INVEST, {'requested_amount_rub': 30_000_000}),
    'gov_working_pledged': (MANUFACTURER, PSK_WORKING, {'purpose': 'working_capital', 'requested_amount_rub': 10_000_000,
                                                        'collateral': PLEDGE}),
}


def expected(fixture_id: str, product_id: str, need: dict, *, revenue: int | None = None, debt: int | None = None) -> dict:
    """The oracle's view of a submitted case: score, band, secured, limit, rule, status and preapproved amount."""
    fixture = FIXTURES[fixture_id]
    revenue = fixture['monthly_revenue_rub'] if revenue is None else revenue
    previous = fixture['previous_monthly_revenue_rub'] if revenue == fixture['monthly_revenue_rub'] else revenue
    months = oracle.completed_months(date.fromisoformat(fixture['registered_at']), FIXED_DATE)
    total = oracle.score(months, revenue, previous, fixture['monthly_debt_payment_rub'] if debt is None else debt,
                         fixture['credit_history'])
    collateral = need.get('collateral')
    secured = oracle.is_secured(product_id, collateral)
    value = (collateral or {}).get('declared_value_rub')
    limit = oracle.scored_limit(product_id, oracle.risk(total), revenue, value, secured=secured)
    rule, status, amount = oracle.outcome(product_id, total, limit, need['requested_amount_rub'])
    return {'score': total, 'risk': oracle.risk(total), 'secured': secured, 'limit': limit, 'rule': rule, 'status': status,
            'amount': amount, 'documents': oracle.required_documents(secured)}


@pytest.mark.parametrize('family', list(FAMILIES))
def test_one_submission_per_product_family(client, bki_calls, storage, family):
    fixture_id, product_id, changes = FAMILIES[family]
    need = need_of(fixture_id, product_id, **changes)
    want = expected(fixture_id, product_id, need)
    application = submitted(client, fixture_id, product=product_id, **changes)
    evaluation = application['latest_evaluation']
    assert (evaluation['score'], evaluation['risk'], evaluation['rule'], application['status']) == \
           (want['score'], want['risk'], want['rule'], want['status'])
    assert application['scored_limit_rub'] == evaluation['scored_limit_rub'] == want['limit']
    assert application['preapproved_amount_rub'] == want['amount'] and application['requested_amount_rub'] == need['requested_amount_rub']
    assert application['answers']['term_months'] == need.get('term_months')
    product = application['product']
    assert (product['id'], product['secured'], product['required_documents']) == (product_id, want['secured'], want['documents'])
    assert (product['collateral_mode'], product['payment_model']) == (PRODUCTS[product_id]['collateral_mode'], PRODUCTS[product_id]['payment_model'])
    (row,) = rows(client, 'Application', id=application['id'])
    assert (row.submitted_input_snapshot['secured'], row.submitted_input_snapshot['required_documents']) == (want['secured'], want['documents'])
    assert (row.status, row.scored_limit_rub, row.preapproved_amount_rub) == (want['status'], want['limit'], want['amount'])
    (saved,) = rows(client, 'Evaluation', application_id=application['id'])
    assert (saved.rule, saved.scored_limit_rub, saved.input_snapshot['secured']) == (want['rule'], want['limit'], want['secured'])
    assert len(bki_calls) == 1
    if want['status'] == 'PREAPPROVED':
        assert [item['document_type'] for item in checklist(client, application)['requirements']] == want['documents']
        assert application['document_summary']['required_total'] == len(want['documents'])


def test_the_family_outcomes_agree_with_the_literal_numbers():
    """Hand-derived anchors for the oracle: limits by min(max, 3R or the medium cap, unsecured cap [+ 70% of V])."""
    literal = {'term': ('R8', 2_400_000), 'line': ('R10', 600_000), 'secured': ('R8', 4_500_000),
               'universal': ('R9', 20_000_000), 'universal_pledged': ('R8', 27_000_000), 'factoring': ('R8', 2_400_000),
               'gov_border': ('R8', 30_000_000), 'gov_invest': ('R8', 36_000_000), 'gov_working_pledged': ('R8', 36_000_000)}
    for family, (fixture_id, product_id, changes) in FAMILIES.items():
        want = expected(fixture_id, product_id, need_of(fixture_id, product_id, **changes))
        assert (want['rule'], want['limit']) == literal[family], family


# --- officer bounds per product --------------------------------------------------------------------------------------

REVIEWED = ['secured', 'universal', 'universal_pledged', 'factoring', 'gov_invest', 'gov_working_pledged']


@pytest.mark.parametrize('family', REVIEWED)
def test_officer_preapproval_bounds_follow_the_pinned_product(client, officer, family):
    fixture_id, product_id, changes = FAMILIES[family]
    need = need_of(fixture_id, product_id, **changes)
    want = expected(fixture_id, product_id, need)
    application = claimed(officer, submitted(client, fixture_id, product=product_id, answers=TAX_DEBT, **changes))
    assert (application['status'], application['latest_evaluation']['rule']) == ('MANUAL_REVIEW', 'R5')
    low, high = PRODUCTS[product_id]['amount_min_rub'], min(need['requested_amount_rub'], want['limit'])
    assert application['preapproval'] == {'amount_min_rub': low, 'amount_max_rub': high, 'blocked_by': None}
    for amount in (low - 1, high + 1):
        error = refused(preapprove(officer, application, amount), 422, 'AMOUNT_OUT_OF_BOUNDS')
        assert error['details'] == {'amount_min_rub': low, 'amount_max_rub': high}
    assert ok(preapprove(officer, application, high))['preapproved_amount_rub'] == high


# (family, verified valuation for a secured case)
FINAL = [('term', None), ('secured', 5_000_000), ('universal', None), ('universal_pledged', 5_000_000),
         ('factoring', None), ('gov_border', None), ('gov_invest', None), ('gov_working_pledged', 1_000_000)]


@pytest.mark.parametrize('family,valuation', FINAL)
def test_final_bounds_and_documents_follow_the_pinned_product(client, officer, storage, family, valuation):
    fixture_id, product_id, changes = FAMILIES[family]
    need = need_of(fixture_id, product_id, **changes)
    want = expected(fixture_id, product_id, need)
    application = submitted(client, fixture_id, product=product_id, **changes)
    assert application['status'] == 'PREAPPROVED'
    application, documents = upload_all(client, application)
    assert list(documents) == want['documents']
    application = accept_all(officer, claimed(officer, completed(client, application)), documents, valuation=valuation)
    revenue = FIXTURES[fixture_id]['monthly_revenue_rub']
    verified = oracle.scored_limit(product_id, want['risk'], revenue, valuation, secured=want['secured'])
    final = detail(officer, application)['application']['final_approval']
    assert final == {'amount_min_rub': PRODUCTS[product_id]['amount_min_rub'], 'amount_max_rub': min(want['amount'], verified),
                     'verified_limit_rub': verified, 'blocked_by': None}


def test_the_universal_limit_final_bound_adds_the_verified_pledge_to_its_unsecured_cap():
    """Literal anchors: 20m + 70% of a verified 5m = 23.5m below the 25m preapproval; a pledged working-capital PSK
    loan keeps its 500m cap, so its verified value never binds."""
    assert oracle.scored_limit(UNIVERSAL, 'low', 12_000_000, 5_000_000, secured=True) == 23_500_000
    assert oracle.scored_limit(UNIVERSAL, 'low', 12_000_000, secured=False) == 20_000_000
    assert oracle.scored_limit(PSK_WORKING, 'low', 12_000_000, 1_000_000, secured=True) == 36_000_000
    assert oracle.scored_limit(SECURED, 'low', 1_500_000, 5_000_000) == 3_500_000


# --- limit edges -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('declared,requested,limit,rule', [
    (None, 20_000_000, 20_000_000, 'R8'), (None, 20_000_001, 20_000_000, 'R9'),
    (22_857_142, 36_000_000, 35_999_999, 'R9'),  # 20m + floor(70% of 22,857,142) = 35,999,999
    (22_857_143, 36_000_000, 36_000_000, 'R8'),  # 20m + 16,000,000: the turnover limit 3 x 12m binds
])
def test_the_universal_limit_lends_its_unsecured_cap_plus_the_pledge(client, declared, requested, limit, rule):
    collateral = None if declared is None else declared_collateral(declared)
    changes = {'purpose': 'working_capital', 'requested_amount_rub': requested, 'collateral': collateral}
    assert oracle.scored_limit(UNIVERSAL, 'low', 12_000_000, declared, secured=declared is not None) == limit
    application = submitted(client, MANUFACTURER, product=UNIVERSAL, **changes)
    assert (application['latest_evaluation']['rule'], application['scored_limit_rub']) == (rule, limit)
    assert application['preapproved_amount_rub'] == min(requested, limit)
    assert application['product']['secured'] is (declared is not None)


@pytest.mark.parametrize('requested,rule,amount', [(2_400_000, 'R8', 2_400_000), (2_400_001, 'R9', 2_400_000)])
def test_factoring_capacity_is_bounded_by_turnover(client, requested, rule, amount):
    """Ruling: factoring has no catalog maximum (2b fallback); its limit is the turnover limit, 3 x 800k."""
    assert oracle.scored_limit(FACTORING, 'low', 800_000) == 2_400_000
    application = submitted(client, 'strong', product=FACTORING, requested_amount_rub=requested)
    assert (application['latest_evaluation']['rule'], application['preapproved_amount_rub']) == (rule, amount)
    assert application['scored_limit_rub'] == 2_400_000


@pytest.mark.parametrize('product_id,requested,rule,status', [
    (PSK_WORKING, 500_000, 'R10', 'MANUAL_REVIEW'), (PSK_WORKING, 600_001, 'R11', 'MANUAL_REVIEW'),
    (PSK_INVEST, 25_000_000, 'R7', 'REJECTED'),
])
def test_the_medium_risk_cap_applies_to_gov_programs(client, product_id, requested, rule, status):
    """Ruling: medium risk is min(max, 1m, R) for every product, so a 25m-minimum program needs low risk."""
    limit = oracle.scored_limit(product_id, 'medium', 600_000)
    assert limit == 600_000 and oracle.outcome(product_id, 65, limit, requested)[:2] == (rule, status)
    application = submitted(client, 'medium', product=product_id, requested_amount_rub=requested,
                            purpose=PRODUCTS[product_id]['purposes'][0])
    evaluation = application['latest_evaluation']
    assert (evaluation['score'], evaluation['risk'], evaluation['rule'], application['status']) == (65, 'medium', rule, status)
    assert application['scored_limit_rub'] == 600_000


@pytest.mark.parametrize('product_id,revenue,requested,rule', [
    (PSK_INVEST, 8_333_333, 25_000_000, 'R7'), (PSK_INVEST, 8_333_334, 25_000_000, 'R8'),  # catalog minimum 25m
    (GOSCREDIT, 99_999, 300_000, 'R7'), (GOSCREDIT, 100_000, 300_000, 'R8'),  # the policy's fallback minimum 300k
])
def test_r7_compares_the_scored_limit_with_the_effective_minimum(client, product_id, revenue, requested, rule):
    debt = 0 if product_id == GOSCREDIT else None
    changes = {'requested_amount_rub': requested, 'purpose': PRODUCTS[product_id]['purposes'][0]}
    want = expected(MANUFACTURER, product_id, need_of(MANUFACTURER, product_id, **changes), revenue=revenue, debt=debt)
    assert (want['rule'], want['risk']) == (rule, 'low') and (want['limit'] < requested) is (rule == 'R7')
    company = onboard(client, MANUFACTURER)
    set_turnover(client, company, revenue, revenue)
    answers = {} if debt is None else {'monthly_debt_payment_rub': debt}
    application = submitted(client, MANUFACTURER, product=product_id, company=company, answers=answers, **changes)
    assert (application['latest_evaluation']['rule'], application['scored_limit_rub']) == (rule, want['limit'])
    assert application['status'] == ('REJECTED' if rule == 'R7' else 'PREAPPROVED')
