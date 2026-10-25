"""Submission checks over HTTP + DB: consents, R1-R11, fixture outcomes, exact numerical boundaries, BKI calls and
source recovery.

Scores, limits and rules come from application_oracle (exact fractions and calendar stepping, no application code)
and the literal numbers of docs/test-scenarios/acceptance.md; fixture labels are only cross-checked against the oracle.
"""
from datetime import date
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from app.main import app
from app.models import Company, Consent, IdempotencyRecord
import application_oracle as oracle
from application_helpers import (CONSENTS, FIXED_DATE, FIXED_NOW, LINE, SECURED, TERM, bki_calls, clock, complete,
                                 declared_collateral, draft, history, onboard, patch_answers, read, retry, rows,
                                 set_company, set_turnover, submit, submitted)
from app.recommendations.catalog import CONFIG
from recommendation_oracle import FIXTURES, PRODUCTS
from test_identity_company import ORIGIN, client

pytestmark = pytest.mark.usefixtures('clock')
PUBLIC_EVALUATION = {'id', 'rule', 'outcome', 'score', 'risk', 'scored_limit_rub', 'reasons', 'created_at'}


def evaluations(client, application):
    return sorted(rows(client, 'Evaluation', application_id=application['id']), key=lambda row: row.sequence)


def granted(client, application):
    with client.app.state.test_factory() as db:
        return sorted((row.code, row.text_version) for row in
                      db.scalars(select(Consent).where(Consent.application_id == application['id'])))


def use_bki(monkeypatch, fixture_id='strong', **values):
    """Changes what the local BKI simulator reports for a fixture INN (the mock's own data, restored afterwards)."""
    from app import companies
    inn = FIXTURES[fixture_id]['inn']
    monkeypatch.setitem(companies.SOURCES, inn, {**companies.SOURCES[inn], **values})


def finance_fields(client, application):
    dialog = client.get(f"/api/v1/applications/{application['id']}/dialog").json()
    return {field['name']: field for field in dialog['stages'][2]['fields']}


def test_oracle_constants_match_the_policy_file():
    for product in PRODUCTS.values():
        assert (product['low_multiple'], product['medium_multiple'], product['medium_cap_rub']) == \
               (oracle.LOW_MULTIPLE, oracle.MEDIUM_MULTIPLE, oracle.MEDIUM_CAP_RUB)
    assert PRODUCTS[SECURED]['ltv'] == oracle.LTV == oracle.Fraction(7, 10)


NO_CONSENT = {
    'none': [], 'processing only': [CONSENTS[0]], 'bki only': [CONSENTS[1]],
    'old version': [{**consent, 'version': 'demo-consent-v1'} for consent in CONSENTS],
    'unchecked': [{**consent, 'accepted': False} for consent in CONSENTS],
    'extra code': CONSENTS + [{'code': 'ONBOARDING_PROCESSING', 'version': CONSENTS[0]['version'], 'accepted': True}],
    'duplicate': [CONSENTS[0], CONSENTS[0]],
}


@pytest.mark.parametrize('consents', list(NO_CONSENT.values()) + [None], ids=list(NO_CONSENT) + ['omitted'])
def test_submission_needs_both_current_explicit_consents_and_never_calls_bki(client, bki_calls, consents):
    application = complete(client, draft(client, 'strong'))
    body = {'version': application['version']} if consents is None else {'version': application['version'], 'consents': consents}
    response = client.post(f"/api/v1/applications/{application['id']}/submit", json=body, headers={'Idempotency-Key': uuid4().hex})
    assert response.status_code == 422 and response.json()['error']['code'] == 'NEED_INFO', response.text
    assert 'consents' in response.json()['error']['fields']
    assert bki_calls == [] and read(client, application) == application
    assert evaluations(client, application) == [] and granted(client, application) == []
    assert len(history(client, application)) == 1


def test_consent_acceptance_must_be_a_literal_true(client, bki_calls):
    application = complete(client, draft(client, 'strong'))
    response = submit(client, application, consents=[{**consent, 'accepted': 1} for consent in CONSENTS])
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert bki_calls == [] and read(client, application)['status'] == 'DRAFT'


def test_raw_missing_turnover_submission_lists_the_missing_answers_without_bki(client, bki_calls):
    application = draft(client, 'missing_turnover')
    assert application['answers']['monthly_revenue_rub'] is None and application['indicative_limit_rub'] is None
    raw = submit(client, application)
    assert raw.status_code == 422 and raw.json()['error']['code'] == 'NEED_INFO'
    assert {'monthly_revenue_rub', 'previous_monthly_revenue_rub', 'monthly_debt_payment_rub', 'accuracy_confirmed'} <= set(raw.json()['error']['fields'])
    application = complete(client, application)  # every stage except the turnover the source does not know
    response = submit(client, application)
    assert response.status_code == 422 and set(response.json()['error']['fields']) == {'monthly_revenue_rub', 'previous_monthly_revenue_rub'}
    assert bki_calls == [] and read(client, application)['status'] == 'DRAFT' and granted(client, application) == []


# The catalog's bounds (test_products_config.GOLDEN): unsecured 300k–30m over 12–60 months, the revolving line without a
# term (a term given for it is a correction), secured 500k–150m over 12–120 months. The questionnaire takes amounts up to
# the policy maximum (2b) and terms of 1–120 months, so the secured term maximum is reached as an inclusive bound below
# and its overflow is refused by input validation before R1. Every product's edges: test_application_products.py.
CORRECTIONS = [
    (TERM, {'term_months': 11}, 'term_months'), (TERM, {'term_months': 61}, 'term_months'),
    (TERM, {'requested_amount_rub': 299_999}, 'requested_amount_rub'), (TERM, {'requested_amount_rub': 30_000_001}, 'requested_amount_rub'),
    (TERM, {'purpose': 'investment'}, 'purpose'), (TERM, {'collateral': declared_collateral()}, 'collateral'),
    (LINE, {'purpose': 'refinancing'}, 'purpose'), (LINE, {'term_months': 12}, 'term_months'),
    (SECURED, {'requested_amount_rub': 499_999}, 'requested_amount_rub'), (SECURED, {'purpose': 'investment'}, 'purpose'),
    (SECURED, {'term_months': 11}, 'term_months'), (SECURED, {'requested_amount_rub': 150_000_001}, 'requested_amount_rub'),
]


@pytest.mark.parametrize('product,changes,field', CORRECTIONS)
def test_unsupported_parameters_need_correction_before_any_check(client, bki_calls, product, changes, field):
    application = complete(client, draft(client, 'strong', product=product), **changes)
    for consents in (CONSENTS, []):  # R1 comes before the consent gate
        response = submit(client, application, consents=consents)
        assert response.status_code == 422 and response.json()['error']['code'] == 'CORRECTION_REQUIRED', response.text
        assert field in response.json()['error']['fields']
    assert bki_calls == [] and read(client, application)['status'] == 'DRAFT' and evaluations(client, application) == []


@pytest.mark.parametrize('product,changes', [
    (TERM, {'term_months': 12}), (TERM, {'term_months': 60}), (TERM, {'requested_amount_rub': 300_000}),
    (TERM, {'requested_amount_rub': 30_000_000}), (LINE, {'requested_amount_rub': 300_000}), (LINE, {'requested_amount_rub': 30_000_000}),
    (SECURED, {'term_months': 12}), (SECURED, {'term_months': 120}), (SECURED, {'requested_amount_rub': 500_000}),
    (SECURED, {'requested_amount_rub': 150_000_000}),
])
def test_inclusive_product_bounds_reach_the_check(client, bki_calls, product, changes):
    application = submitted(client, 'strong', product=product, answers=changes)
    assert application['status'] == 'PREAPPROVED' and len(bki_calls) == 1


@pytest.mark.parametrize('collateral,paths', [
    (None, {'collateral'}), ({'status': 'unknown'}, {'collateral'}), ({'status': 'none'}, {'collateral'}),
    ({'status': 'declared', 'type': 'equipment'}, {'collateral.declared_value_rub', 'collateral.description'}),
])
def test_secured_submission_needs_a_declared_collateral(client, bki_calls, collateral, paths):
    application = draft(client, 'secured_investment', collateral=None)
    if collateral is not None:
        application = patch_answers(client, application, collateral=collateral).json()['application']
    response = submit(client, complete(client, application))
    assert response.status_code == 422 and response.json()['error']['code'] == 'NEED_INFO'
    assert paths <= set(response.json()['error']['fields']) and bki_calls == []


# The acceptance table, plus the gov-program fixture: low risk, min(30m border-program maximum, 3 × 12m) = 30m.
SPEC_LIMITS = {'strong': 2_400_000, 'medium': 600_000, 'high_risk': None, 'secured_investment': 4_500_000,
               'gov_manufacturer': 30_000_000}


@pytest.mark.parametrize('fixture_id', list(SPEC_LIMITS))
def test_fixture_submission_outcomes_match_the_independent_oracle(client, bki_calls, fixture_id):
    fixture = FIXTURES[fixture_id]
    label = fixture['expected_check_outcome']
    product = label['product_id']
    months = oracle.completed_months(date.fromisoformat(fixture['registered_at']), FIXED_DATE)
    total = oracle.score(months, fixture['monthly_revenue_rub'], fixture['previous_monthly_revenue_rub'],
                         fixture['monthly_debt_payment_rub'], fixture['credit_history'])
    band = oracle.risk(total)
    limit = oracle.scored_limit(product, band, fixture['monthly_revenue_rub'], fixture['collateral_value_rub'] if product == SECURED else None)
    requested = fixture['need']['requested_amount_rub']
    rule, status, amount = oracle.outcome(product, total, limit, requested)
    assert (total, band, status, amount) == (label['score'], label['risk'], label['status'], label['preapproved_amount_rub'])
    assert limit == SPEC_LIMITS[fixture_id]
    application = submitted(client, fixture_id)
    evaluation = application['latest_evaluation']
    assert set(evaluation) == PUBLIC_EVALUATION and evaluation['reasons']
    assert (evaluation['score'], evaluation['risk'], evaluation['rule'], evaluation['outcome']) == (total, band, rule, status)
    assert application['status'] == status and application['scored_limit_rub'] == evaluation['scored_limit_rub'] == limit
    assert application['preapproved_amount_rub'] == amount and application['requested_amount_rub'] == requested
    assert application['submitted_at'] == '2026-10-24T12:00:00Z' and application['final_amount_rub'] is None
    assert [call['attempt'] for call in bki_calls] == [1]
    assert granted(client, application) == [('APPLICATION_PROCESSING', 'demo-consent-v2'), ('BKI', 'demo-consent-v2')]
    assert [(item['from_status'], item['to_status']) for item in history(client, application)][1:] == [('DRAFT', 'CHECKING'), ('CHECKING', status)]
    saved = evaluations(client, application)
    assert len(saved) == 1 and saved[0].sources['bki']['credit_history'] == fixture['credit_history']


def test_known_inactive_company_is_rejected_through_checking_without_bki(client, bki_calls):
    application = complete(client, draft(client, 'strong'))
    set_company(client, application['company_id'], registry_status='inactive')  # the status changed after creation
    response = submit(client, application)
    assert response.status_code == 200, response.text
    result = response.json()['application']
    assert result['status'] == 'REJECTED' and result['scored_limit_rub'] is None
    evaluation = result['latest_evaluation']
    assert (evaluation['rule'], evaluation['outcome'], evaluation['score'], evaluation['risk']) == ('R2', 'REJECTED', None, None)
    assert [(item['from_status'], item['to_status']) for item in history(client, application)][1:] == [('DRAFT', 'CHECKING'), ('CHECKING', 'REJECTED')]
    assert bki_calls == [] and len(granted(client, application)) == 2


def test_inactive_fixture_draft_is_rejected_even_with_missing_answers(client, bki_calls):
    application = draft(client, 'inactive')  # direct API creation is possible; the UI keeps it read-only
    assert 'submit' not in application['allowed_actions']
    response = submit(client, application)  # known inactive overrides the missing finance answers
    assert response.status_code == 200 and response.json()['application']['status'] == 'REJECTED'
    assert response.json()['application']['latest_evaluation']['rule'] == 'R2' and bki_calls == []


@pytest.mark.parametrize('overdue,status,rule', [(29, 'PREAPPROVED', 'R8'), (30, 'REJECTED', 'R2')])
def test_current_bki_overdue_of_thirty_days_is_a_stop_factor(client, bki_calls, monkeypatch, overdue, status, rule):
    use_bki(monkeypatch, current_overdue_days=overdue)
    application = submitted(client, 'strong')
    evaluation = application['latest_evaluation']
    assert (application['status'], evaluation['rule']) == (status, rule) and len(bki_calls) == 1
    if rule == 'R2':
        assert evaluation['score'] is None and application['preapproved_amount_rub'] is None


def test_unavailable_registry_waits_without_bki_and_one_retry_recovers_to_preapproval(client, bki_calls):
    application = submitted(client, 'registry_unavailable')
    assert (application['status'], application['latest_evaluation']['rule']) == ('WAIT_EXTERNAL', 'R4')
    assert application['allowed_actions'] == ['retry_check', 'cancel'] and bki_calls == []
    company_url = f"/api/v1/companies/{application['company_id']}"
    assert client.get(company_url).json()['company']['version'] == 1
    response = retry(client, application, key='registry-retry')
    assert response.status_code == 200, response.text
    result = response.json()['application']
    assert (result['status'], result['latest_evaluation']['rule'], result['preapproved_amount_rub']) == ('PREAPPROVED', 'R8', 1_000_000)
    assert len(bki_calls) == 1  # one recovery lookup through the precheck path, then exactly one BKI request
    source = client.get(company_url).json()
    assert source['company']['registry_status'] == 'active' and source['company']['version'] == 2
    assert source['precheck']['registry_source_status'] == 'available'
    assert [item['to_status'] for item in history(client, application)] == ['DRAFT', 'CHECKING', 'WAIT_EXTERNAL', 'CHECKING', 'PREAPPROVED']
    assert [(row.rule, row.outcome) for row in evaluations(client, application)] == [('R4', 'WAIT_EXTERNAL'), ('R8', 'PREAPPROVED')]
    replay = retry(client, application, key='registry-retry')
    assert replay.json() == response.json() and len(bki_calls) == 1
    assert client.get(company_url).json()['company']['version'] == 2 and len(evaluations(client, application)) == 2


def test_unavailable_bki_waits_and_one_retry_call_recovers_to_preapproval(client, bki_calls):
    application = submitted(client, 'bki_unavailable')
    assert (application['status'], application['latest_evaluation']['rule']) == ('WAIT_EXTERNAL', 'R4')
    assert [call['attempt'] for call in bki_calls] == [1]
    response = retry(client, application)
    assert response.status_code == 200, response.text
    result = response.json()['application']
    assert (result['status'], result['latest_evaluation']['rule'], result['preapproved_amount_rub']) == ('PREAPPROVED', 'R8', 1_000_000)
    assert result['latest_evaluation']['score'] == oracle.score(48, 800_000, 680_000, 160_000, 'clean') == 100
    assert [call['attempt'] for call in bki_calls] == [1, 2]
    assert client.get(f"/api/v1/companies/{application['company_id']}").json()['company']['version'] == 1  # no registry lookup
    first, second = evaluations(client, application)
    assert first.sources['bki']['status'] == 'unavailable' and second.sources['bki']['status'] == 'available'


def test_missing_bki_category_needs_a_trusted_source_retry_that_survives_a_restart(client, bki_calls):
    application = submitted(client, 'bki_missing')
    assert application['status'] == 'NEED_INFO'
    assert (application['latest_evaluation']['rule'], application['latest_evaluation']['score']) == ('R3', None)
    request = application['open_info_request']
    assert (request['kind'], request['source'], request['requested_fields'], request['requested_by']) == ('trusted_source', 'bki', [], 'system')
    assert request['question'] and request['resolved_at'] is None and request['response'] is None
    assert application['allowed_actions'] == ['retry_check', 'cancel'] and application['missing_fields'] == []
    (saved,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert saved.officer_id is None
    assert patch_answers(client, application, credit_history='clean').status_code == 422  # BKI data is never client-set
    assert patch_answers(client, application, actual_address='Новый адрес').status_code == 409
    bki_calls.clear()  # a restart loses process memory; recovery is indexed by persisted evaluations
    with TestClient(app, headers={'origin': ORIGIN}, cookies=client.cookies) as restarted:
        response = retry(restarted, application, key='trusted-retry')
        replay = retry(restarted, application, key='trusted-retry')
    assert response.status_code == 200, response.text
    result = response.json()['application']
    evaluation = result['latest_evaluation']
    assert result['id'] == application['id'] and result['status'] == 'MANUAL_REVIEW'
    assert (evaluation['score'], evaluation['scored_limit_rub'], evaluation['outcome']) == (100, 2_400_000, 'MANUAL_REVIEW')
    assert evaluation['score'] == oracle.score(48, 800_000, 680_000, 160_000, FIXTURES['bki_missing']['recovery']['retry_credit_history'])
    assert evaluation['scored_limit_rub'] == oracle.scored_limit(TERM, 'low', 800_000) == FIXTURES['bki_missing']['recovery']['expected_scored_limit_rub']
    assert result['preapproved_amount_rub'] is None and result['open_info_request'] is None
    assert replay.json() == response.json() and [call['attempt'] for call in bki_calls] == [2]
    (saved,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert saved.resolved_at is not None and saved.officer_id is None
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.assignee_id is None
    first, second = evaluations(client, application)
    assert (first.rule, first.outcome, first.sources['bki']['credit_history']) == ('R3', 'NEED_INFO', None)  # old evidence kept
    assert (second.outcome, second.sources['bki']['credit_history']) == ('MANUAL_REVIEW', 'clean')
    assert [item['to_status'] for item in history(client, application)][-3:] == ['NEED_INFO', 'CHECKING', 'MANUAL_REVIEW']


def test_an_unavailable_bki_during_trusted_source_recovery_keeps_the_request_and_the_review_rule(client, bki_calls, monkeypatch):
    from app import companies
    inn = FIXTURES['bki_missing']['inn']
    recovery = companies.SOURCES[inn]['recovery']
    application = submitted(client, 'bki_missing')
    use_bki(monkeypatch, 'bki_missing', recovery={'retry_bki_source_status': 'unavailable'})
    waiting = retry(client, application).json()['application']
    assert (waiting['status'], waiting['latest_evaluation']['rule']) == ('WAIT_EXTERNAL', 'R4')
    assert waiting['open_info_request']['kind'] == 'trusted_source' and waiting['allowed_actions'] == ['retry_check', 'cancel']
    use_bki(monkeypatch, 'bki_missing', recovery=recovery)
    reviewed = retry(client, waiting).json()['application']  # the request is still open: recovery returns to review
    assert (reviewed['status'], reviewed['latest_evaluation']['score'], reviewed['open_info_request']) == ('MANUAL_REVIEW', 100, None)
    assert [call['attempt'] for call in bki_calls] == [1, 2, 3]
    assert [item['to_status'] for item in history(client, application)][-5:] == ['NEED_INFO', 'CHECKING', 'WAIT_EXTERNAL', 'CHECKING', 'MANUAL_REVIEW']
    (request,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert request.resolved_at is not None


def test_a_category_missing_again_keeps_the_same_trusted_source_request(client, bki_calls, monkeypatch):
    application = submitted(client, 'bki_missing')
    use_bki(monkeypatch, 'bki_missing', recovery={'retry_bki_source_status': 'missing'})
    again = retry(client, application).json()['application']
    assert (again['status'], again['latest_evaluation']['rule']) == ('NEED_INFO', 'R3')
    assert again['open_info_request']['id'] == application['open_info_request']['id']
    assert len(rows(client, 'InfoRequest', application_id=application['id'])) == 1 and len(bki_calls) == 2


def test_an_unavailable_turnover_source_waits_and_the_retry_recovers_it(client, bki_calls):
    from app.models import Precheck
    from sqlalchemy import update
    company = onboard(client, 'strong')
    with client.app.state.test_factory.begin() as db:
        db.execute(update(Precheck).where(Precheck.company_id == company).values(turnover_source_status='unavailable'))
    application = submitted(client, 'strong', company=company)
    assert (application['status'], application['latest_evaluation']['rule'], bki_calls) == ('WAIT_EXTERNAL', 'R4', [])
    result = retry(client, application).json()['application']
    assert (result['status'], result['latest_evaluation']['rule']) == ('PREAPPROVED', 'R8') and len(bki_calls) == 1
    source = client.get(f'/api/v1/companies/{company}').json()
    assert source['precheck']['turnover_source_status'] == 'available' and source['company']['version'] == 2


def test_declared_turnover_goes_to_manual_review_and_keeps_its_source_tag(client, bki_calls):
    application = draft(client, 'missing_turnover')
    finance = finance_fields(client, application)
    assert finance['monthly_revenue_rub']['source'] == {'name': 'turnover', 'status': 'missing', 'value': None}
    assert finance['monthly_revenue_rub']['origin'] is None
    # The source still reports the period end; the prefilled value is the source's, not a client declaration.
    assert finance['financial_period_end']['source']['value'] == '2026-09-30' and finance['financial_period_end']['origin'] == 'source'
    application = complete(client, application, monthly_revenue_rub=800_000, previous_monthly_revenue_rub=680_000)
    assert finance_fields(client, application)['monthly_revenue_rub']['origin'] == 'declared'
    response = submit(client, application)
    assert response.status_code == 200, response.text
    result = response.json()['application']
    evaluation = result['latest_evaluation']
    assert (result['status'], evaluation['rule']) == ('MANUAL_REVIEW', 'R5')
    assert evaluation['score'] == oracle.score(48, 800_000, 680_000, 160_000, 'clean') and evaluation['risk'] == 'low'
    assert any('заявлены клиентом' in reason for reason in evaluation['reasons']) and len(bki_calls) == 1
    (saved,) = evaluations(client, application)
    assert saved.input_snapshot['finance']['monthly_revenue_rub']['origin'] == 'declared'


def test_overriding_a_known_source_value_routes_manual_review_and_keeps_the_original(client, bki_calls):
    application = complete(client, draft(client, 'strong'), previous_monthly_revenue_rub=800_000)
    assert finance_fields(client, application)['previous_monthly_revenue_rub']['origin'] == 'override'
    result = submit(client, application).json()['application']
    assert (result['status'], result['latest_evaluation']['rule']) == ('MANUAL_REVIEW', 'R5')
    # Scoring keeps the trusted source value (growth from 680k), not the client's 800k.
    trusted = oracle.score(48, 800_000, 680_000, 160_000, 'clean')
    assert result['latest_evaluation']['score'] == trusted != oracle.score(48, 800_000, 800_000, 160_000, 'clean')
    (saved,) = evaluations(client, application)
    evidence = saved.input_snapshot['finance']['previous_monthly_revenue_rub']
    assert (evidence['answer'], evidence['source'], evidence['origin']) == (800_000, 680_000, 'override')
    assert client.get(f"/api/v1/companies/{application['company_id']}/precheck").json()['precheck']['previous_monthly_revenue_rub'] == 680_000


@pytest.mark.parametrize('fixture_id,answers,phrase', [
    ('strong', {'tax_debt_rub': 1}, 'налоговая задолженность'),
    ('strong', {'legal_proceedings': True}, 'судебные'),
    ('secured_investment', {'collateral': {'encumbered': True}}, 'залог'),
    ('secured_investment', {'collateral': {'owner_confirmed': False}}, 'залог'),
])
def test_tax_legal_and_collateral_concerns_route_manual_review(client, bki_calls, fixture_id, answers, phrase):
    application = submitted(client, fixture_id, answers=answers)
    evaluation = application['latest_evaluation']
    assert (application['status'], evaluation['rule'], evaluation['score']) == ('MANUAL_REVIEW', 'R5', 100)
    assert any(phrase in reason.lower() for reason in evaluation['reasons']) and len(bki_calls) == 1


@pytest.mark.parametrize('revenue,previous', [(0, 680_000), (800_000, 0)])
def test_zero_turnover_routes_manual_review_without_a_score_or_limit(client, bki_calls, revenue, previous):
    company = onboard(client, 'strong')
    set_turnover(client, company, revenue, previous)
    application = submitted(client, 'strong', company=company)
    evaluation = application['latest_evaluation']
    assert (application['status'], evaluation['rule'], evaluation['score'], evaluation['risk']) == ('MANUAL_REVIEW', 'R5', None, None)
    assert application['scored_limit_rub'] is None and application['preapproved_amount_rub'] is None


@pytest.mark.parametrize('requested,rule,amount', [(2_399_999, 'R8', 2_399_999), (2_400_000, 'R8', 2_400_000),
                                                   (2_400_001, 'R9', 2_400_000), (3_000_000, 'R9', 2_400_000)])
def test_low_risk_request_is_compared_with_the_scored_limit(client, requested, rule, amount):
    assert oracle.outcome(TERM, 100, oracle.scored_limit(TERM, 'low', 800_000), requested) == (rule, 'PREAPPROVED', amount)
    application = submitted(client, 'strong', requested_amount_rub=requested)
    evaluation = application['latest_evaluation']
    assert (application['status'], evaluation['rule'], application['preapproved_amount_rub']) == ('PREAPPROVED', rule, amount)
    assert application['requested_amount_rub'] == requested and application['scored_limit_rub'] == 2_400_000
    if rule == 'R9':
        assert any('2 400 000' in reason for reason in evaluation['reasons'])


@pytest.mark.parametrize('requested,rule', [(600_000, 'R10'), (600_001, 'R11')])
def test_medium_risk_goes_to_manual_review_with_the_possible_amount(client, requested, rule):
    assert oracle.outcome(LINE, 65, oracle.scored_limit(LINE, 'medium', 600_000), requested) == (rule, 'MANUAL_REVIEW', None)
    application = submitted(client, 'medium', requested_amount_rub=requested)
    evaluation = application['latest_evaluation']
    assert (application['status'], evaluation['rule'], evaluation['score']) == ('MANUAL_REVIEW', rule, 65)
    assert application['scored_limit_rub'] == 600_000 and application['preapproved_amount_rub'] is None
    if rule == 'R11':
        assert any('600 000' in reason for reason in evaluation['reasons'])


@pytest.mark.parametrize('revenue,rule,status', [(99_999, 'R7', 'REJECTED'), (100_000, 'R8', 'PREAPPROVED')])
def test_a_scored_limit_below_the_product_minimum_rejects(client, revenue, rule, status):
    total = oracle.score(48, revenue, revenue, 0, 'clean')
    limit = oracle.scored_limit(TERM, oracle.risk(total), revenue)
    assert (limit, oracle.outcome(TERM, total, limit, 300_000)[:2]) == (3 * revenue, (rule, status))
    company = onboard(client, 'strong')
    set_turnover(client, company, revenue, revenue)
    application = submitted(client, 'strong', company=company, requested_amount_rub=300_000, answers={'monthly_debt_payment_rub': 0})
    assert (application['status'], application['latest_evaluation']['rule'], application['scored_limit_rub']) == (status, rule, limit)


@pytest.mark.parametrize('declared,requested,limit', [(714_285, 500_000, 499_999), (714_286, 500_000, 500_000),
                                                      (1_000_000, 700_000, 700_000), (1_000_000, 800_000, 700_000)])
def test_secured_scored_limit_applies_the_declared_collateral_cap(client, declared, requested, limit):
    assert oracle.scored_limit(SECURED, 'low', 800_000, declared) == limit  # acceptance values agree with exact arithmetic
    rule, status, amount = oracle.outcome(SECURED, 100, limit, requested)
    application = submitted(client, 'strong', product=SECURED, requested_amount_rub=requested, collateral=declared_collateral(declared))
    assert (application['status'], application['latest_evaluation']['rule']) == (status, rule)
    assert (application['scored_limit_rub'], application['preapproved_amount_rub']) == (limit, amount)


@pytest.mark.parametrize('registered_at,previous,debt,credit_history,total', [
    ('2022-10-24', 800_000, 400_001, 'minor_closed', 45),
    ('2025-10-24', 800_000, 320_000, 'minor_closed', 50),
    ('2022-10-24', 680_000, 320_000, 'minor_closed', 70),
    ('2022-10-24', 800_000, 320_000, 'clean', 75),
])
def test_attainable_score_band_boundaries(client, monkeypatch, registered_at, previous, debt, credit_history, total):
    months = oracle.completed_months(date.fromisoformat(registered_at), FIXED_DATE)
    assert oracle.score(months, 800_000, previous, debt, credit_history) == total
    band = oracle.risk(total)
    rule, status, _ = oracle.outcome(TERM, total, oracle.scored_limit(TERM, band, 800_000), 500_000)
    use_bki(monkeypatch, credit_history=credit_history)
    company = onboard(client, 'strong')
    set_company(client, company, registered_at=date.fromisoformat(registered_at))
    set_turnover(client, company, 800_000, previous)
    application = submitted(client, 'strong', company=company, requested_amount_rub=500_000, answers={'monthly_debt_payment_rub': debt})
    evaluation = application['latest_evaluation']
    assert (evaluation['score'], evaluation['risk'], evaluation['rule'], application['status']) == (total, band, rule, status)


@pytest.mark.parametrize('registered_at,months,total', [('2026-04-24', 6, 90), ('2026-04-25', 5, 80),
                                                        ('2024-10-24', 24, 100), ('2024-10-25', 23, 90)])
def test_business_age_counts_completed_calendar_months_on_the_business_date(client, registered_at, months, total):
    assert oracle.completed_months(date.fromisoformat(registered_at), FIXED_DATE) == months
    assert oracle.score(months, 800_000, 680_000, 160_000, 'clean') == total
    company = onboard(client, 'strong')
    set_company(client, company, registered_at=date.fromisoformat(registered_at))
    assert submitted(client, 'strong', company=company)['latest_evaluation']['score'] == total


@pytest.mark.parametrize('revenue,previous,debt,total', [
    (89_999, 100_000, 0, 75), (90_000, 100_000, 0, 90), (110_000, 100_000, 0, 90), (110_001, 100_000, 0, 100),
    (100_000, 100_000, 30_000, 90), (100_000, 100_000, 30_001, 75), (100_000, 100_000, 50_000, 75), (100_000, 100_000, 50_001, 60),
])
def test_revenue_growth_and_debt_burden_boundaries(client, revenue, previous, debt, total):
    assert oracle.score(48, revenue, previous, debt, 'clean') == total
    company = onboard(client, 'strong')
    set_turnover(client, company, revenue, previous)
    application = submitted(client, 'strong', company=company, requested_amount_rub=300_000, answers={'monthly_debt_payment_rub': debt})
    assert application['latest_evaluation']['score'] == total


def test_a_replayed_submission_returns_the_original_result_once(client, bki_calls):
    application = complete(client, draft(client, 'strong'))
    first = submit(client, application, key='submit-once')
    again = submit(client, application, key='submit-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    assert len(bki_calls) == 1 and len(evaluations(client, application)) == 1 and len(history(client, application)) == 3
    changed = submit(client, application, key='submit-once', version=application['version'] + 1)
    assert changed.status_code == 409 and changed.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    stale = submit(client, application, key='submit-new')  # the version the draft had before submission
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'
    assert len(bki_calls) == 1
    with client.app.state.test_factory() as db:
        path = f"/api/v1/applications/{application['id']}/submit"
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.path == path)) == 1


def test_retry_check_is_only_for_waiting_or_trusted_source_cases(client, bki_calls):
    application = draft(client, 'strong')
    response = retry(client, application)
    assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_STATUS'
    preapproved = submitted(client, 'strong', company=application['company_id'])
    response = retry(client, preapproved)
    assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_STATUS'
    medium = submitted(client, 'medium')
    assert retry(client, medium).status_code == 409
    assert len(bki_calls) == 2


def test_a_retry_needs_the_stored_submission_bki_consent(client, bki_calls):
    application = submitted(client, 'bki_unavailable')
    with client.app.state.test_factory.begin() as db:
        db.execute(delete(Consent).where(Consent.application_id == application['id'], Consent.code == 'BKI'))
    response = retry(client, application)
    assert response.status_code == 409 and response.json()['error']['code'] == 'CONSENT_REQUIRED'
    assert len(bki_calls) == 1 and read(client, application)['status'] == 'WAIT_EXTERNAL'


def test_an_internal_check_reports_a_client_answer_gap_as_a_client_answers_request(client, bki_calls):
    """The defensive check outcome for a source gap that reaches the check without the submit gate (acceptance note)."""
    from app.applications import checks
    from app.applications.lifecycle import ApplicationChange
    from app.applications.models import Application
    from app.applications.products import terms_for
    application = draft(client, 'missing_turnover')
    with client.app.state.test_factory.begin() as db:
        row = db.get(Application, application['id'])
        change = ApplicationChange(db, row, actor_id=None, now=FIXED_NOW)
        change.move('CHECKING', reason_code='SUBMITTED', reason_text='Проверка без шлюза анкеты')
        checks.run_check(db, change, db.get(Company, row.company_id), terms_for(CONFIG.product(TERM), None))
    result = read(client, application)
    assert (result['status'], result['latest_evaluation']['rule']) == ('NEED_INFO', 'R3')
    request = result['open_info_request']
    assert (request['kind'], request['source'], request['requested_by']) == ('client_answers', None, 'system')
    assert {'monthly_revenue_rub', 'previous_monthly_revenue_rub'} <= set(request['requested_fields'])
    assert result['missing_fields'] == request['requested_fields'] and result['allowed_actions'] == ['respond_info', 'cancel']
    assert bki_calls == []
