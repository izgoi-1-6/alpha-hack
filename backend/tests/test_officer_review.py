"""Officer review queue and preliminary decisions over HTTP + DB: staff-only routes, the queue and its filters, the
evidence detail, claims (one assignee), request-info, preapprove within the R12 bounds, preliminary and final
rejections, idempotent replays (one OfficerDecision), stale versions, lazy expiry and PostgreSQL races.

Amounts and bounds are the spec's literal numbers and application_oracle's exact arithmetic, never the code under
test. Information responses from the customer are covered in test_information_requests.py.
"""
from datetime import datetime, timezone
import json
import os
import threading
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app.main import app
from app.models import Company, IdempotencyRecord
import application_oracle as oracle
from application_helpers import (TERM, bki_calls, cancel, clock, draft, history, onboard, read, retry, rows, set_company,
                                 set_turnover, submitted)
from officer_helpers import (OFFICER_EMAIL, REASON, claim, claimed, decisions, detail, login, ok, officer, preapprove,
                             refused, reject, request_info, second_officer, set_status, staff_command, staff_url)
from test_identity_company import ORIGIN, client

pytestmark = pytest.mark.usefixtures('clock')
QUEUE = '/api/v1/officer/applications'
PRODUCT_MIN = 300_000  # both unsecured products (spec product table)
MEDIUM_LIMIT = 600_000  # acceptance: medium R600k scored limit 600k


def queue(session, **params) -> list[str]:
    response = session.get(QUEUE, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['total'] == len(body['items'])
    return [item['id'] for item in body['items']]


def medium_review(client, requested: int = 700_000) -> dict:
    """The medium fixture in MANUAL_REVIEW; 700,000 is above its 600,000 scored limit (R11)."""
    application = submitted(client, 'medium', requested_amount_rub=requested)
    assert (application['status'], application['scored_limit_rub']) == ('MANUAL_REVIEW', MEDIUM_LIMIT)
    return application


def history_rows(client, application):
    return sorted(rows(client, 'StatusHistory', application_id=application['id']), key=lambda row: row.sequence)


# --- roles, origin and ownership -------------------------------------------------------------------------------------

def test_staff_routes_are_for_officers_and_customer_commands_for_owners(client, officer):
    application = medium_review(client)
    body = {'version': application['version'], 'reason': REASON}
    commands = {'claim': {'version': application['version']}, 'request-info': {**body, 'requested_fields': ['seasonal']},
                'preapprove': {**body, 'amount_rub': PRODUCT_MIN}, 'reject': body}
    for path in (QUEUE, staff_url(application)):  # the owning customer cannot use staff reads
        assert refused(client.get(path), 403, 'OFFICER_REQUIRED')
    for name, payload in commands.items():
        response = client.post(staff_url(application, f'/{name}'), json=payload, headers={'Idempotency-Key': uuid4().hex})
        refused(response, 403, 'OFFICER_REQUIRED')
    for name, payload in commands.items():  # staff commands need the exact UI origin
        response = officer.post(staff_url(application, f'/{name}'), json=payload,
                                headers={'Idempotency-Key': uuid4().hex, 'origin': 'http://evil.test'})
        refused(response, 403, 'ORIGIN_FORBIDDEN')
    with TestClient(app, headers={'origin': ORIGIN}) as anonymous:
        assert anonymous.get(QUEUE).status_code == 401 and anonymous.get(staff_url(application)).status_code == 401
    # Staff cannot use the owner's commands to act as the customer.
    response = officer.post(f"/api/v1/applications/{application['id']}/respond-info", headers={'Idempotency-Key': uuid4().hex},
                            json={'version': application['version'], 'response': 'Ответ', 'answers': {}})
    refused(response, 403, 'CLIENT_REQUIRED')
    assert refused(officer.get(f"/api/v1/applications/{application['id']}"), 403, 'CLIENT_REQUIRED')
    absent = {'id': str(uuid4()), 'version': 1}
    refused(officer.get(staff_url(absent)), 404, 'APPLICATION_NOT_FOUND')
    refused(claim(officer, absent), 404, 'APPLICATION_NOT_FOUND')
    assert read(client, application) == application and rows(client, 'OfficerDecision') == []


def test_officer_commands_reject_unknown_and_server_owned_keys(client, officer):
    application = claimed(officer, medium_review(client))
    for name, body in [('claim', {'assignee_id': officer.user['id']}), ('reject', {'reason': REASON, 'status': 'APPROVED'}),
                       ('preapprove', {'amount_rub': PRODUCT_MIN, 'reason': REASON, 'phase': 'final'}),
                       ('preapprove', {'amount_rub': '300000', 'reason': REASON}),
                       ('preapprove', {'amount_rub': True, 'reason': REASON}), ('preapprove', {'reason': REASON}),
                       ('request-info', {'reason': REASON, 'requested_fields': ['seasonal'], 'kind': 'trusted_source'})]:
        refused(staff_command(officer, application, name, body), 422, 'VALIDATION_ERROR')
    response = officer.post(staff_url(application, '/reject'), json={'version': application['version'], 'reason': REASON})
    assert response.status_code == 422  # Idempotency-Key is required
    assert detail(officer, application)['application'] == application


# --- queue -----------------------------------------------------------------------------------------------------------

def test_queue_lists_submitted_applications_in_arrival_order_with_filters(client, officer, clock):
    company = onboard(client, 'strong')
    draft_only = draft(client, 'strong', company=company)
    never_submitted = ok(cancel(client, draft(client, 'strong', company=company)))  # cancelled as a draft
    clock.now = datetime(2026, 10, 24, 12, 0, 1, tzinfo=timezone.utc)
    preapproved = submitted(client, 'strong', company=company)  # auto-preapproved: unassigned, claimable later
    clock.now = datetime(2026, 10, 24, 12, 0, 2, tzinfo=timezone.utc)
    review = medium_review(client)
    clock.now = datetime(2026, 10, 24, 12, 0, 3, tzinfo=timezone.utc)
    rejected = submitted(client, 'high_risk')
    assert rejected['status'] == 'REJECTED'
    assert queue(officer) == [preapproved['id'], review['id'], rejected['id']]  # FIFO by submission; no drafts
    assert queue(officer, status='DRAFT') == [draft_only['id']]  # drafts only on explicit request
    assert never_submitted['status'] == 'CANCELLED' and queue(officer, status='CANCELLED') == []  # never reached the bank
    cancelled = ok(cancel(client, preapproved))  # a submitted application cancelled later is listed
    assert queue(officer, status='CANCELLED') == [cancelled['id']]
    assert queue(officer) == [preapproved['id'], review['id'], rejected['id']]
    assert queue(officer, status='MANUAL_REVIEW') == [review['id']]
    assert queue(officer, company_id=company) == [preapproved['id']]
    assert queue(officer, company_id=str(uuid4())) == []
    assert queue(officer, assignee='me') == []
    assert queue(officer, assignee='unassigned') == [preapproved['id'], review['id'], rejected['id']]
    claimed(officer, review)
    assert queue(officer, assignee='me') == [review['id']]
    assert queue(officer, assignee='unassigned') == [preapproved['id'], rejected['id']]
    assert queue(officer, assignee='me', status='MANUAL_REVIEW') == [review['id']]
    for params in ({'status': 'OFFERED'}, {'assignee': 'someone'}):
        assert officer.get(QUEUE, params=params).status_code == 422
    item = officer.get(QUEUE, params={'status': 'MANUAL_REVIEW'}).json()['items'][0]
    assert item['assignee'] == {'id': officer.user['id'], 'display_name': officer.user['display_name']}
    assert item['company']['inn'] and item['latest_evaluation']['risk'] == 'medium'
    assert item['allowed_actions'] == ['request_info', 'preapprove', 'reject']


@pytest.mark.parametrize('first', ['EXPIRED', 'PREAPPROVED'])
def test_queue_applies_lazy_expiry_before_the_status_filter(client, officer, clock, first):
    application = submitted(client, 'strong')
    clock.now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)  # preapproved_at + 14 days
    login(officer, OFFICER_EMAIL)  # the 12-hour session has ended
    expected = {'EXPIRED': [application['id']], 'PREAPPROVED': []}
    assert queue(officer, status=first) == expected[first]  # the first read after the deadline records the expiry
    second = 'PREAPPROVED' if first == 'EXPIRED' else 'EXPIRED'
    assert queue(officer, status=second) == expected[second]
    assert [row.to_status for row in history_rows(client, application)].count('EXPIRED') == 1


# --- evidence detail -------------------------------------------------------------------------------------------------

def test_detail_returns_evidence_evaluations_decisions_and_staff_history(client, officer):
    application = submitted(client, 'strong', answers={'previous_monthly_revenue_rub': 800_000})  # override → R5
    assert application['status'] == 'MANUAL_REVIEW'
    body = detail(officer, application)
    assert set(body) >= {'application', 'evaluations', 'source_evidence', 'decisions', 'documents', 'info_requests', 'history'}
    staff = body['application']
    assert staff['id'] == application['id'] and staff['assignee'] is None
    assert staff['allowed_actions'] == ['claim'] and staff['document_summary'] is None and body['documents'] == []
    assert staff['preapproval'] == {'amount_min_rub': PRODUCT_MIN, 'amount_max_rub': 2_000_000, 'blocked_by': None}
    (evaluation,) = body['evaluations']
    trusted = oracle.score(48, 800_000, 680_000, 160_000, 'clean')  # the source value is scored, not the override
    assert (evaluation['rule'], evaluation['outcome'], evaluation['score']) == ('R5', 'MANUAL_REVIEW', trusted)
    assert evaluation['factors']['credit_history'] == 'clean' and evaluation['review_flags'] == ['finance_override']
    assert evaluation['sources']['bki']['credit_history'] == 'clean'
    evidence = body['source_evidence']
    assert evidence['precheck']['previous_monthly_revenue_rub'] == 680_000
    assert evidence['submitted']['answers']['previous_monthly_revenue_rub'] == 800_000
    finance = evidence['finance']['previous_monthly_revenue_rub']
    assert (finance['answer'], finance['source'], finance['origin'], finance['submitted_answer']) == (800_000, 680_000, 'override', 800_000)
    assert [entry['evaluation_id'] for entry in evidence['bki']] == [evaluation['id']]
    assert evidence['bki'][0]['provider'] == 'demo_bki_mock' and evidence['bki'][0]['synthetic'] is True
    assert body['decisions'] == [] and body['info_requests'] == []
    customer = client.get('/api/v1/auth/me').json()['user']
    assert [(item['to_status'], item['actor_role']) for item in body['history']] == [
        ('DRAFT', 'client'), ('CHECKING', 'client'), ('MANUAL_REVIEW', 'system')]
    assert body['history'][0]['actor'] == {'id': customer['id'], 'display_name': customer['display_name']}
    assert body['history'][2]['actor'] is None


# --- claim -----------------------------------------------------------------------------------------------------------

def test_a_claim_assigns_once_without_a_status_transition(client, officer, second_officer):
    application = medium_review(client)
    response = claim(officer, application, key='claim-1')
    claimed_application = ok(response)
    assert claimed_application['status'] == 'MANUAL_REVIEW' and claimed_application['version'] == application['version'] + 1
    assert claimed_application['assignee'] == {'id': officer.user['id'], 'display_name': officer.user['display_name']}
    assert claimed_application['allowed_actions'] == ['request_info', 'preapprove', 'reject']
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.assignee_id == officer.user['id']
    assert len(history_rows(client, application)) == 3 and rows(client, 'OfficerDecision') == []  # no status, no decision
    assert len(rows(client, 'Notification', application_id=application['id'])) == 3
    assert claim(officer, application, key='claim-1').json() == response.json()  # exact replay
    again = ok(claim(officer, claimed_application))  # the current assignee: a no-op success
    assert again['version'] == claimed_application['version'] and again['assignee']['id'] == officer.user['id']
    refused(claim(second_officer, claimed_application), 409, 'ALREADY_ASSIGNED')  # no silent reassignment
    assert detail(second_officer, application)['application']['allowed_actions'] == []
    refused(claim(officer, claimed_application, version=application['version']), 409, 'VERSION_CONFLICT')
    (row,) = rows(client, 'Application', id=application['id'])
    assert (row.assignee_id, row.version) == (officer.user['id'], claimed_application['version'])
    # The customer never sees who holds the case.
    assert 'assignee' not in read(client, application) and officer.user['id'] not in json.dumps(read(client, application))


@pytest.mark.parametrize('fixture_id,status', [('medium', 'MANUAL_REVIEW'), ('bki_missing', 'NEED_INFO'), ('strong', 'PREAPPROVED')])
def test_claims_are_allowed_in_review_and_document_phases(client, officer, fixture_id, status):
    application = submitted(client, fixture_id)
    assert application['status'] == status
    assert detail(officer, application)['application']['allowed_actions'] == ['claim']
    result = ok(claim(officer, application))
    assert result['status'] == status and result['assignee']['id'] == officer.user['id']


@pytest.mark.parametrize('status', ['DOCS_UPLOADED', 'DOCS_REWORK'])
def test_claims_are_allowed_on_seeded_document_states(client, officer, status):
    application = submitted(client, 'strong')
    set_status(client, application, status)
    assert ok(claim(officer, application))['status'] == status


def test_claims_are_refused_outside_the_claimable_states(client, officer, bki_calls):
    application = draft(client, 'strong')
    refused(claim(officer, application), 409, 'INVALID_STATUS')
    rejected = submitted(client, 'high_risk')
    refused(claim(officer, rejected), 409, 'INVALID_STATUS')
    waiting = submitted(client, 'bki_unavailable')
    refused(claim(officer, waiting), 409, 'INVALID_STATUS')
    cancelled = ok(cancel(client, medium_review(client)))
    refused(claim(officer, cancelled), 409, 'INVALID_STATUS')
    assert all(row.assignee_id is None for row in rows(client, 'Application'))


# --- assignment and versions guard every decision --------------------------------------------------------------------

def test_decisions_need_the_assigned_officer(client, officer, second_officer):
    application = medium_review(client)
    for response in (request_info(officer, application, ['seasonal']), preapprove(officer, application, PRODUCT_MIN),
                     reject(officer, application)):
        refused(response, 409, 'ASSIGNMENT_REQUIRED')  # unassigned: claim first
    application = claimed(officer, application)
    for response in (request_info(second_officer, application, ['seasonal']), preapprove(second_officer, application, PRODUCT_MIN),
                     reject(second_officer, application)):
        refused(response, 409, 'ASSIGNMENT_REQUIRED')  # another officer's case
    assert rows(client, 'OfficerDecision') == [] and rows(client, 'InfoRequest') == []
    assert read(client, application)['status'] == 'MANUAL_REVIEW' and len(history_rows(client, application)) == 3


def test_a_stale_version_decision_is_refused(client, officer):
    application = medium_review(client)
    claimed_application = claimed(officer, application)
    for response in (preapprove(officer, claimed_application, PRODUCT_MIN, version=application['version']),
                     reject(officer, claimed_application, version=application['version']),
                     request_info(officer, claimed_application, ['seasonal'], version=application['version'])):
        refused(response, 409, 'VERSION_CONFLICT')
    assert rows(client, 'OfficerDecision') == [] and read(client, application)['status'] == 'MANUAL_REVIEW'


def test_a_replayed_decision_records_one_officer_decision(client, officer, bki_calls):
    application = claimed(officer, medium_review(client))
    first = preapprove(officer, application, MEDIUM_LIMIT, key='decide-once')
    again = preapprove(officer, application, MEDIUM_LIMIT, key='decide-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    refused(preapprove(officer, application, MEDIUM_LIMIT - 1, key='decide-once'), 409, 'IDEMPOTENCY_CONFLICT')
    refused(preapprove(officer, application, MEDIUM_LIMIT, key='decide-twice'), 409, 'VERSION_CONFLICT')
    refused(request_info(officer, ok(first), ['seasonal']), 409, 'INVALID_STATUS')  # no longer in MANUAL_REVIEW
    (decision,) = decisions(client, application)
    assert (decision.action, decision.amount_rub) == ('preapprove', MEDIUM_LIMIT)
    assert [row.to_status for row in history_rows(client, application)].count('PREAPPROVED') == 1
    with client.app.state.test_factory() as db:
        path = staff_url(application, '/preapprove')
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.path == path)) == 1
    assert len(bki_calls) == 1  # the submission only


# --- preapprove ------------------------------------------------------------------------------------------------------

def test_medium_risk_manual_preapproval_records_the_officer_decision(client, officer, bki_calls):
    application = claimed(officer, medium_review(client))
    staff = detail(officer, application)['application']
    assert staff['preapproval'] == {'amount_min_rub': PRODUCT_MIN, 'amount_max_rub': MEDIUM_LIMIT, 'blocked_by': None}
    response = preapprove(officer, application, MEDIUM_LIMIT, reason='  Средний риск: одобряю сумму в пределах лимита.  ')
    result = ok(response)
    assert result['status'] == 'PREAPPROVED' and result['version'] == application['version'] + 1
    assert (result['preapproved_amount_rub'], result['requested_amount_rub'], result['scored_limit_rub']) == (MEDIUM_LIMIT, 700_000, MEDIUM_LIMIT)
    assert (result['preapproved_at'], result['preapproval_expires_at']) == ('2026-10-24T12:00:00Z', '2026-11-07T12:00:00Z')
    assert result['allowed_actions'] == ['reject'] and result['preapproval'] is None
    (decision,) = decisions(client, application)
    (evaluation,) = rows(client, 'Evaluation', application_id=application['id'])
    assert (decision.officer_id, decision.phase, decision.action, decision.amount_rub) == (officer.user['id'], 'preliminary', 'preapprove', MEDIUM_LIMIT)
    assert decision.reason == 'Средний риск: одобряю сумму в пределах лимита.' and decision.evaluation_id == evaluation.id
    last = history_rows(client, application)[-1]
    assert (last.from_status, last.to_status, last.actor_id, last.reason_code) == ('MANUAL_REVIEW', 'PREAPPROVED', officer.user['id'], 'R12')
    assert last.reason_text == decision.reason and last.application_version == result['version']
    note = rows(client, 'Notification', status_history_id=last.id)[0]
    assert note.channel == 'demo_in_app' and '600 000' in note.message and '07.11.2026' in note.message
    assert 'UTC' not in note.message and 'не окончательное' in note.message
    customer = read(client, application)
    assert customer['status'] == 'PREAPPROVED' and customer['preapproved_amount_rub'] == MEDIUM_LIMIT
    assert customer['allowed_actions'] == ['upload_document', 'cancel'] and officer.user['id'] not in json.dumps(customer)
    assert len(bki_calls) == 1
    body = detail(officer, application)
    assert [(item['action'], item['phase'], item['amount_rub']) for item in body['decisions']] == [('preapprove', 'preliminary', MEDIUM_LIMIT)]
    assert body['decisions'][0]['officer'] == {'id': officer.user['id'], 'display_name': officer.user['display_name']}


# Inclusive bounds product_min <= amount <= min(request, scored limit) (spec R12; acceptance medium limit 600k).
@pytest.mark.parametrize('requested,amount,accepted', [
    (700_000, PRODUCT_MIN - 1, False), (700_000, PRODUCT_MIN, True), (700_000, MEDIUM_LIMIT, True), (700_000, MEDIUM_LIMIT + 1, False),
    (500_000, 500_000, True), (500_000, 500_001, False),  # the request bounds it below the scored limit
])
def test_officer_amounts_are_bounded_by_the_product_minimum_request_and_scored_limit(client, officer, requested, amount, accepted):
    application = claimed(officer, medium_review(client, requested=requested))
    response = preapprove(officer, application, amount)
    if accepted:
        assert ok(response)['preapproved_amount_rub'] == amount
        assert ok(response)['requested_amount_rub'] == requested  # never rewritten
    else:
        error = refused(response, 422, 'AMOUNT_OUT_OF_BOUNDS')
        assert set(error['fields']) == {'amount_rub'}
        assert error['details'] == {'amount_min_rub': PRODUCT_MIN, 'amount_max_rub': min(requested, MEDIUM_LIMIT)}
        assert read(client, application)['status'] == 'MANUAL_REVIEW' and decisions(client, application) == []


@pytest.mark.parametrize('name', ['preapprove', 'reject', 'request-info'])
@pytest.mark.parametrize('reason,valid', [('', False), ('   ', False), ('я' * 2001, False), ('я' * 2000, True), ('  Причина  ', True)])
def test_officer_reasons_are_required_after_trim_up_to_2000_characters(client, officer, name, reason, valid):
    application = claimed(officer, medium_review(client))
    body = {'reason': reason, 'amount_rub': PRODUCT_MIN} if name == 'preapprove' else {'reason': reason}
    if name == 'request-info':
        body['requested_fields'] = ['seasonal']
    response = staff_command(officer, application, name, body)
    if not valid:
        refused(response, 422, 'VALIDATION_ERROR')
        assert 'reason' in response.json()['error']['fields'] and decisions(client, application) == []
        return
    ok(response)
    (decision,) = decisions(client, application)
    assert decision.reason == reason.strip() and history_rows(client, application)[-1].reason_text == reason.strip()


def test_a_noncomputable_limit_cannot_be_preapproved(client, officer):
    company = onboard(client, 'strong')
    set_turnover(client, company, 0, 680_000)  # zero revenue: R5 without a score or limit
    application = claimed(officer, submitted(client, 'strong', company=company))
    assert (application['status'], application['scored_limit_rub'], application['latest_evaluation']['score']) == ('MANUAL_REVIEW', None, None)
    assert application['allowed_actions'] == ['request_info', 'reject']
    assert application['preapproval']['blocked_by']['code'] == 'LIMIT_NOT_COMPUTABLE'
    refused(preapprove(officer, application, PRODUCT_MIN), 409, 'LIMIT_NOT_COMPUTABLE')
    assert decisions(client, application) == [] and read(client, application)['status'] == 'MANUAL_REVIEW'
    assert ok(reject(officer, application))['status'] == 'REJECTED'


@pytest.mark.parametrize('case', ['score_below_50', 'limit_below_minimum'])
def test_mandatory_stops_refuse_preapproval_even_in_manual_review(client, officer, case):
    """R5 precedes R6/R7, so a reviewed application can carry an R6/R7 condition: the computed values decide."""
    if case == 'score_below_50':
        application = submitted(client, 'high_risk', answers={'tax_debt_rub': 1})
        assert application['latest_evaluation']['score'] == oracle.score(4, 300_000, 375_000, 180_000, 'minor_closed') == 10
    else:
        company = onboard(client, 'strong')
        set_turnover(client, company, 99_999, 99_999)  # low risk; 3 x 99,999 = 299,997 < 300,000
        application = submitted(client, 'strong', company=company, requested_amount_rub=PRODUCT_MIN,
                                answers={'monthly_debt_payment_rub': 0, 'tax_debt_rub': 1})
        assert application['scored_limit_rub'] == oracle.scored_limit(TERM, 'low', 99_999) == 299_997
    assert (application['status'], application['latest_evaluation']['rule']) == ('MANUAL_REVIEW', 'R5')
    application = claimed(officer, application)
    assert application['allowed_actions'] == ['request_info', 'reject']
    assert application['preapproval']['blocked_by']['code'] == 'MANDATORY_STOP'
    refused(preapprove(officer, application, PRODUCT_MIN), 409, 'MANDATORY_STOP')
    assert decisions(client, application) == []
    assert ok(reject(officer, application))['status'] == 'REJECTED'


def tamper_latest_evaluation(client, application, **changes):
    from app.applications.models import Evaluation
    with client.app.state.test_factory.begin() as db:
        row = db.scalars(select(Evaluation).where(Evaluation.application_id == application['id'])
                         .order_by(Evaluation.sequence.desc())).first()
        for key, value in changes.items():
            setattr(row, key, value(getattr(row, key)) if callable(value) else value)


@pytest.mark.parametrize('overdue,code', [(29, None), (30, 'MANDATORY_STOP')])
def test_a_stored_bki_overdue_of_thirty_days_refuses_preapproval(client, officer, overdue, code):
    application = claimed(officer, submitted(client, 'strong', answers={'tax_debt_rub': 1}))  # R5, score 100
    tamper_latest_evaluation(client, application, sources=lambda sources: {**sources, 'bki': {**sources['bki'], 'current_overdue_days': overdue}})
    response = preapprove(officer, application, 2_000_000)
    if code is None:
        assert ok(response)['status'] == 'PREAPPROVED'
    else:
        refused(response, 409, code)


def test_rule_labels_never_decide_and_a_company_now_inactive_is_a_mandatory_stop(client, officer):
    application = claimed(officer, submitted(client, 'strong', answers={'tax_debt_rub': 1}))
    tamper_latest_evaluation(client, application, rule='R6')  # a label alone neither blocks nor allows
    assert detail(officer, application)['application']['preapproval']['blocked_by'] is None
    set_company(client, application['company_id'], registry_status='inactive')
    refused(preapprove(officer, application, 2_000_000), 409, 'MANDATORY_STOP')


def test_an_automatic_preapproval_notice_gives_the_deadline_date_without_raw_utc(client):
    application = submitted(client, 'strong')
    message = history(client, application)[-1]['notification']['message']
    assert '2 000 000' in message and '07.11.2026' in message and 'не окончательное' in message
    assert 'UTC' not in message and '12:00' not in message


def test_trusted_source_recovery_with_an_r8_label_is_reviewed_and_preapprovable(client, officer, bki_calls):
    application = ok(retry(client, submitted(client, 'bki_missing')))
    evaluation = application['latest_evaluation']
    assert (application['status'], evaluation['rule'], evaluation['score'], evaluation['scored_limit_rub']) == ('MANUAL_REVIEW', 'R8', 100, 2_400_000)
    assert queue(officer, status='MANUAL_REVIEW') == [application['id']]
    application = claimed(officer, application)
    assert application['preapproval'] == {'amount_min_rub': PRODUCT_MIN, 'amount_max_rub': 1_000_000, 'blocked_by': None}
    assert ok(preapprove(officer, application, 1_000_000))['preapproved_amount_rub'] == 1_000_000
    assert len(bki_calls) == 2


def test_preapproval_is_only_from_manual_review(client, officer):
    application = claimed(officer, submitted(client, 'strong'))
    refused(preapprove(officer, application, 2_000_000), 409, 'INVALID_STATUS')
    need_info = claimed(officer, submitted(client, 'bki_missing'))
    refused(preapprove(officer, need_info, 1_000_000), 409, 'INVALID_STATUS')
    refused(request_info(officer, application, ['seasonal']), 409, 'INVALID_STATUS')
    refused(request_info(officer, need_info, ['seasonal']), 409, 'INVALID_STATUS')
    assert rows(client, 'OfficerDecision') == []


# --- reject ----------------------------------------------------------------------------------------------------------

def test_a_preliminary_rejection_from_manual_review(client, officer):
    application = claimed(officer, medium_review(client))
    result = ok(reject(officer, application, reason='Нагрузка по долгу высокая для запрошенной суммы.'))
    assert result['status'] == 'REJECTED' and result['allowed_actions'] == [] and result['preapproved_amount_rub'] is None
    (decision,) = decisions(client, application)
    (evaluation,) = rows(client, 'Evaluation', application_id=application['id'])
    assert (decision.phase, decision.action, decision.amount_rub, decision.evaluation_id) == ('preliminary', 'reject', None, evaluation.id)
    last = history_rows(client, application)[-1]
    assert (last.from_status, last.to_status, last.actor_id, last.reason_code) == ('MANUAL_REVIEW', 'REJECTED', officer.user['id'], 'R12')
    note = rows(client, 'Notification', status_history_id=last.id)[0]
    assert note.message and 'UTC' not in note.message
    customer_history = history(client, application)
    assert customer_history[-1]['reason_text'] == 'Нагрузка по долгу высокая для запрошенной суммы.'
    assert customer_history[-1]['actor_role'] == 'officer' and 'actor_id' not in customer_history[-1]
    refused(reject(officer, result), 409, 'INVALID_STATUS')
    refused(claim(officer, result), 409, 'INVALID_STATUS')


@pytest.mark.parametrize('status', ['PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK'])
def test_a_final_phase_rejection_needs_no_documents(client, officer, status):
    application = submitted(client, 'strong')  # auto-preapproved, unassigned
    if status != 'PREAPPROVED':
        set_status(client, application, status)  # document commands are Task 6; the state is seeded directly
    application = claimed(officer, application)
    assert application['allowed_actions'] == ['reject']
    result = ok(reject(officer, application, reason='Финальная проверка: отказ.'))
    assert result['status'] == 'REJECTED' and result['preapproved_amount_rub'] == 2_000_000  # kept as evidence
    (decision,) = decisions(client, application)
    assert (decision.phase, decision.action) == ('final', 'reject')
    last = history_rows(client, application)[-1]
    assert (last.from_status, last.to_status, last.reason_code) == (status, 'REJECTED', 'FINAL_REJECTED')


def test_a_replayed_rejection_records_one_decision_and_one_history_row(client, officer):
    application = claimed(officer, medium_review(client))
    first = reject(officer, application, key='reject-once')
    again = reject(officer, application, key='reject-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    refused(reject(officer, application, reason='Другая причина', key='reject-once'), 409, 'IDEMPOTENCY_CONFLICT')
    refused(reject(officer, application, key='reject-twice'), 409, 'VERSION_CONFLICT')
    assert [row.action for row in decisions(client, application)] == ['reject']
    assert [row.to_status for row in history_rows(client, application)].count('REJECTED') == 1
    assert len(rows(client, 'Notification', application_id=application['id'])) == 4


def test_rejection_is_refused_while_waiting_for_information(client, officer):
    application = claimed(officer, submitted(client, 'bki_missing'))
    refused(reject(officer, application), 409, 'INVALID_STATUS')
    assert read(client, application)['status'] == 'NEED_INFO' and rows(client, 'OfficerDecision') == []


def test_an_officer_command_after_the_deadline_records_the_expiry_and_is_refused(client, officer, clock):
    application = claimed(officer, submitted(client, 'strong'))
    clock.now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)  # preapproved_at + 14 days
    login(officer, OFFICER_EMAIL)
    refused(reject(officer, application), 409, 'APPLICATION_EXPIRED')
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.status == 'EXPIRED' and row.version == application['version'] + 1
    assert [entry.to_status for entry in history_rows(client, application)].count('EXPIRED') == 1
    assert rows(client, 'OfficerDecision') == []
    refused(claim(officer, {**application, 'version': row.version}), 409, 'INVALID_STATUS')
    assert detail(officer, application)['application']['status'] == 'EXPIRED'


def test_the_database_admits_one_preapproval_and_one_rejection_per_application(client, officer):
    from sqlalchemy.exc import IntegrityError
    from app.applications.models import OfficerDecision
    application = claimed(officer, medium_review(client))

    def decision(sequence, action, amount=None, phase='preliminary'):
        return OfficerDecision(application_id=application['id'], sequence=sequence, officer_id=officer.user['id'], phase=phase,
                               action=action, amount_rub=amount, reason=REASON, created_at=datetime(2026, 10, 24, tzinfo=timezone.utc))

    def recorded():  # information requests repeat next to one preapprove and one (final) reject
        return [decision(1, 'request_info'), decision(2, 'request_info'), decision(3, 'preapprove', 300_000),
                decision(4, 'reject', phase='final')]

    with client.app.state.test_factory() as db:
        db.add_all(recorded())
        db.flush()
        db.rollback()
    for duplicate in (decision(5, 'preapprove', 400_000), decision(5, 'reject'), decision(5, 'request_info', 1),
                      decision(5, 'approve', 300_000, phase='preliminary'), decision(4, 'request_info')):
        with client.app.state.test_factory() as db:
            db.add_all(recorded() + [duplicate])
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()


# --- PostgreSQL races ------------------------------------------------------------------------------------------------

pg_only = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='concurrent commands need PostgreSQL row locks')


def race(client, application, calls):
    """Runs the calls concurrently while the company row is locked, so all of them queue on the same lock."""
    outcome = [None] * len(calls)

    def run(index, cookies, send):
        with TestClient(app, headers={'origin': ORIGIN}, cookies=cookies) as worker:
            outcome[index] = send(worker)

    with client.app.state.test_factory() as blocker:
        blocker.execute(select(Company).where(Company.id == application['company_id']).with_for_update())
        workers = [threading.Thread(target=run, args=(index, cookies, send)) for index, (cookies, send) in enumerate(calls)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=1)
        assert all(worker.is_alive() for worker in workers), 'every command must wait for the row lock'
        blocker.commit()
    for worker in workers:
        worker.join(timeout=30)
    assert not any(worker.is_alive() for worker in workers)
    return outcome


@pg_only
def test_two_officers_racing_to_claim_leave_exactly_one_assignee(client, officer, second_officer):
    application = medium_review(client)
    outcome = race(client, application, [(session.cookies, lambda worker, key=key: claim(worker, application, key=key))
                                         for key, session in (('race-a', officer), ('race-b', second_officer))])
    assert sorted(response.status_code for response in outcome) == [200, 409]
    loser = next(response for response in outcome if response.status_code == 409)
    assert loser.json()['error']['code'] == 'ALREADY_ASSIGNED'
    winner = next(response for response in outcome if response.status_code == 200).json()['application']
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.assignee_id == winner['assignee']['id'] in {officer.user['id'], second_officer.user['id']}
    assert row.version == application['version'] + 1 and len(history_rows(client, application)) == 3


@pg_only
def test_competing_decisions_on_one_version_record_exactly_one(client, officer):
    application = claimed(officer, medium_review(client))
    outcome = race(client, application, [(officer.cookies, lambda worker: preapprove(worker, application, MEDIUM_LIMIT)),
                                         (officer.cookies, lambda worker: reject(worker, application))])
    assert sorted(response.status_code for response in outcome) == [200, 409]
    assert next(response for response in outcome if response.status_code == 409).json()['error']['code'] == 'VERSION_CONFLICT'
    winner = next(response for response in outcome if response.status_code == 200).json()['application']
    (decision,) = decisions(client, application)
    assert {'preapprove': 'PREAPPROVED', 'reject': 'REJECTED'}[decision.action] == winner['status'] == read(client, application)['status']
    assert len(history_rows(client, application)) == 4


@pg_only
def test_a_concurrently_replayed_decision_records_one_officer_decision(client, officer):
    application = claimed(officer, medium_review(client))
    send = lambda worker: preapprove(worker, application, MEDIUM_LIMIT, key='replayed-decision')  # noqa: E731
    outcome = race(client, application, [(officer.cookies, send), (officer.cookies, send)])
    assert [response.status_code for response in outcome] == [200, 200] and outcome[0].json() == outcome[1].json()
    assert len(decisions(client, application)) == 1 and len(history_rows(client, application)) == 4
