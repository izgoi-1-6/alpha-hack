"""Information requests over HTTP + DB: the officer's request-info, the owner's respond-info on the same application,
the re-check from the revised answers with the stored BKI evidence (no new BKI request), the return to the same
officer, trusted-source refusals, the customer's view of officer actions and terminal audit rows.

Scores and limits come from application_oracle and the spec's literal numbers, not from the code under test.
"""
import json
import pytest
import application_oracle as oracle
from application_helpers import (FIXED_NOW, LINE, TERM, bki_calls, cancel, clock, draft, history, read, rows, set_company,
                                 submitted)
from officer_helpers import (claim, claimed, decisions, detail, ok, officer, preapprove, refused, request_info, respond,
                             second_officer, staff_url)
from test_identity_company import client, register

pytestmark = pytest.mark.usefixtures('clock')
NOW = '2026-10-24T12:00:00Z'
MEDIUM_LIMIT = 600_000


def evaluations(client, application):
    return sorted(rows(client, 'Evaluation', application_id=application['id']), key=lambda row: row.sequence)


def history_rows(client, application):
    return sorted(rows(client, 'StatusHistory', application_id=application['id']), key=lambda row: row.sequence)


def asked(client, officer, fixture_id: str, fields: list[str], *, reason: str = 'Уточните сведения анкеты.', **submit_options) -> dict:
    """A claimed MANUAL_REVIEW application of the fixture, moved to NEED_INFO by the officer's request."""
    application = submitted(client, fixture_id, **submit_options)
    assert application['status'] == 'MANUAL_REVIEW', application['latest_evaluation']
    return ok(request_info(officer, claimed(officer, application), fields, reason=reason))


# --- request-info ----------------------------------------------------------------------------------------------------

def test_request_info_records_an_officer_request_a_decision_and_need_info(client, officer, bki_calls):
    application = claimed(officer, submitted(client, 'medium', requested_amount_rub=700_000))
    result = ok(request_info(officer, application, ['monthly_debt_payment_rub', 'obligations_note'],
                             reason='  Уточните платежи по действующим кредитам и лизингу.  '))
    assert result['status'] == 'NEED_INFO' and result['version'] == application['version'] + 1
    assert result['allowed_actions'] == [] and result['assignee']['id'] == officer.user['id']
    (request,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert (request.kind, request.source, request.officer_id) == ('client_answers', None, officer.user['id'])
    assert request.requested_fields == ['monthly_debt_payment_rub', 'obligations_note']
    assert request.question == 'Уточните платежи по действующим кредитам и лизингу.'
    assert (request.response, request.responded_at, request.resolved_at) == (None, None, None)
    (decision,) = decisions(client, application)
    (evaluation,) = evaluations(client, application)
    assert (decision.action, decision.phase, decision.amount_rub, decision.officer_id) == ('request_info', 'preliminary', None, officer.user['id'])
    assert decision.reason == request.question and decision.evaluation_id == evaluation.id
    last = history_rows(client, application)[-1]
    assert (last.from_status, last.to_status, last.actor_id, last.reason_code) == ('MANUAL_REVIEW', 'NEED_INFO', officer.user['id'], 'INFO_REQUESTED')
    assert last.reason_text == request.question and last.application_version == result['version']
    (note,) = rows(client, 'Notification', status_history_id=last.id)
    assert note.channel == 'demo_in_app' and note.message and 'UTC' not in note.message
    customer = read(client, application)
    assert customer['status'] == 'NEED_INFO' and customer['allowed_actions'] == ['respond_info', 'cancel']
    assert customer['missing_fields'] == ['monthly_debt_payment_rub', 'obligations_note']
    shown = customer['open_info_request']
    assert (shown['kind'], shown['requested_by'], shown['question']) == ('client_answers', 'officer', request.question)
    assert officer.user['id'] not in json.dumps(customer) and officer.user['id'] not in json.dumps(history(client, application))
    staff_request = detail(officer, application)['info_requests'][0]
    assert staff_request['officer'] == {'id': officer.user['id'], 'display_name': officer.user['display_name']}
    assert staff_request['open'] is True and len(bki_calls) == 1


@pytest.mark.parametrize('fields', [
    [], ['credit_history'], ['current_overdue_days'], ['inn'], ['company'], ['registry_status'], ['consents'], ['BKI'],
    ['score'], ['status'], ['product_id'], ['collateral.guarantor_consent'], ['collateral.'], ['unknown'],
    ['employees', 'employees'], [3],
])
def test_requested_fields_must_be_questionnaire_answer_paths(client, officer, fields):
    application = claimed(officer, submitted(client, 'medium'))
    error = refused(request_info(officer, application, fields), 422, 'VALIDATION_ERROR')
    assert any(path.startswith('requested_fields') for path in error['fields'])
    assert rows(client, 'InfoRequest') == [] and decisions(client, application) == []
    assert read(client, application)['status'] == 'MANUAL_REVIEW'


@pytest.mark.parametrize('fields', [['collateral'], ['collateral.declared_value_rub'], ['seasonal'], ['accuracy_confirmed', 'employees']])
def test_questionnaire_answers_outside_the_need_can_be_requested(client, officer, fields):
    application = claimed(officer, submitted(client, 'medium'))
    assert ok(request_info(officer, application, fields))['status'] == 'NEED_INFO'
    assert read(client, application)['missing_fields'] == fields


# The stage-2 need (purpose, funding pattern, amount, term) is fixed once submitted: a smaller amount is a smaller
# preapproval and a different need is a new application (controller ruling; spec: the request is never rewritten).
NEED = ['purpose', 'funding_pattern', 'requested_amount_rub', 'term_months']


@pytest.mark.parametrize('fields', [[name] for name in NEED] + [['accuracy_confirmed', 'term_months'], NEED])
def test_an_officer_cannot_request_the_need_fields(client, officer, fields):
    application = claimed(officer, submitted(client, 'medium'))
    error = refused(request_info(officer, application, fields), 422, 'NEED_FIELDS_LOCKED')
    assert set(error['fields']) == {'requested_fields'} and error['fields']['requested_fields']
    assert error['details'] == {'fields': [name for name in fields if name in NEED]}
    assert rows(client, 'InfoRequest') == [] and decisions(client, application) == []
    assert read(client, application)['status'] == 'MANUAL_REVIEW'


def test_request_info_is_refused_while_another_request_is_open(client, officer):
    from app.applications.models import InfoRequest
    application = claimed(officer, submitted(client, 'medium'))
    with client.app.state.test_factory.begin() as db:  # a request left open in review (no 4a path leaves one)
        db.add(InfoRequest(application_id=application['id'], kind='trusted_source', source='bki', requested_fields=[],
                           question='Открытый запрос', created_at=FIXED_NOW))
    refused(request_info(officer, application, ['employees']), 409, 'INFO_REQUEST_OPEN')
    assert len(rows(client, 'InfoRequest', application_id=application['id'])) == 1 and decisions(client, application) == []
    assert read(client, application)['status'] == 'MANUAL_REVIEW'


def test_a_replayed_request_info_records_one_request_and_one_decision(client, officer):
    application = claimed(officer, submitted(client, 'medium'))
    first = request_info(officer, application, ['employees'], key='ask-once')
    again = request_info(officer, application, ['employees'], key='ask-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    refused(request_info(officer, application, ['seasonal'], key='ask-once'), 409, 'IDEMPOTENCY_CONFLICT')
    refused(request_info(officer, application, ['employees'], key='ask-twice'), 409, 'VERSION_CONFLICT')
    assert len(rows(client, 'InfoRequest', application_id=application['id'])) == 1
    assert [row.action for row in decisions(client, application)] == ['request_info']
    assert [row.to_status for row in history_rows(client, application)].count('NEED_INFO') == 1


# --- respond-info ----------------------------------------------------------------------------------------------------

def test_the_owner_answers_on_the_same_application_and_returns_to_the_same_officer(client, officer, bki_calls):
    application = asked(client, officer, 'medium', ['monthly_debt_payment_rub', 'obligations_note'], requested_amount_rub=700_000)
    (before,) = rows(client, 'Application', id=application['id'])
    first_evaluation = evaluations(client, application)[0]
    response = respond(client, application, {'monthly_debt_payment_rub': 240_000, 'obligations_note': '  Лизинг до 2027 года  '},
                       response='  Платёж по лизингу 240 000 ₽ в месяц, договор до 2027 года.  ', key='answer-once')
    answered = ok(response)
    assert answered['id'] == application['id'] and answered['status'] == 'MANUAL_REVIEW'
    assert answered['version'] == application['version'] + 1 and answered['open_info_request'] is None
    assert answered['allowed_actions'] == ['cancel'] and answered['missing_fields'] == []
    assert answered['answers']['obligations_note'] == 'Лизинг до 2027 года'
    (request,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert request.response == 'Платёж по лизингу 240 000 ₽ в месяц, договор до 2027 года.'
    assert request.responded_at is not None and request.resolved_at is not None
    assert (detail(officer, application)['info_requests'][0]['responded_at'], detail(officer, application)['info_requests'][0]['resolved_at']) == (NOW, NOW)
    # A re-check from the revised answers and the stored BKI report: one new evaluation, no BKI request.
    assert len(bki_calls) == 1
    first, second = evaluations(client, application)
    assert (first.id, first.rule, first.score, first.input_snapshot) == (first_evaluation.id, 'R11', 65, first_evaluation.input_snapshot)
    expected = oracle.score(18, 600_000, 600_000, 240_000, 'clean')
    assert (second.score, second.risk, second.scored_limit_rub, second.rule, second.outcome) == (expected, 'medium', MEDIUM_LIMIT, 'R11', 'MANUAL_REVIEW')
    assert second.sources['bki']['credit_history'] == 'clean' and second.sources['bki']['attempt'] == 1
    (after,) = rows(client, 'Application', id=application['id'])
    assert after.submitted_input_snapshot == before.submitted_input_snapshot  # the submission snapshot is never rewritten
    assert after.assignee_id == before.assignee_id == officer.user['id']  # back to the same officer
    last = history_rows(client, application)[-1]
    me = client.get('/api/v1/auth/me').json()['user']['id']
    assert (last.from_status, last.to_status, last.actor_id, last.reason_code) == ('NEED_INFO', 'MANUAL_REVIEW', me, 'INFO_PROVIDED')
    assert last.reason_text == request.response
    (note,) = rows(client, 'Notification', status_history_id=last.id)
    assert note.message and 'UTC' not in note.message
    replay = respond(client, application, {'monthly_debt_payment_rub': 240_000, 'obligations_note': '  Лизинг до 2027 года  '},
                     response='  Платёж по лизингу 240 000 ₽ в месяц, договор до 2027 года.  ', key='answer-once')
    assert replay.json() == response.json() and len(evaluations(client, application)) == 2 and len(bki_calls) == 1
    # The same officer continues: the case is in the queue as theirs, and a decision within the bounds succeeds.
    staff = detail(officer, answered)['application']
    assert staff['assignee']['id'] == officer.user['id'] and staff['allowed_actions'] == ['request_info', 'preapprove', 'reject']
    refused(preapprove(officer, staff, MEDIUM_LIMIT + 1), 422, 'AMOUNT_OUT_OF_BOUNDS')
    decided = ok(preapprove(officer, staff, MEDIUM_LIMIT, reason='Ответ клиента подтверждает нагрузку; одобряю 600 000 ₽.'))
    assert (decided['status'], decided['preapproved_amount_rub'], decided['requested_amount_rub']) == ('PREAPPROVED', MEDIUM_LIMIT, 700_000)
    assert [row.action for row in decisions(client, application)] == ['request_info', 'preapprove']
    assert decisions(client, application)[1].evaluation_id == second.id
    # The customer timeline names roles only.
    items = history(client, application)
    assert [(item['to_status'], item['actor_role']) for item in items] == [
        ('DRAFT', 'client'), ('CHECKING', 'client'), ('MANUAL_REVIEW', 'system'), ('NEED_INFO', 'officer'),
        ('MANUAL_REVIEW', 'client'), ('PREAPPROVED', 'officer')]
    assert all('actor_id' not in item for item in items)
    assert officer.user['id'] not in json.dumps(items) and officer.user['id'] not in json.dumps(read(client, application))


def test_a_response_is_rescored_without_an_automatic_low_risk_shortcut(client, officer, bki_calls):
    application = asked(client, officer, 'medium', ['monthly_debt_payment_rub'], requested_amount_rub=700_000)
    answered = ok(respond(client, application, {'monthly_debt_payment_rub': 120_000}))
    total = oracle.score(18, 600_000, 600_000, 120_000, 'clean')
    limit = oracle.scored_limit(LINE, oracle.risk(total), 600_000)
    assert (total, oracle.risk(total), limit) == (80, 'low', 1_800_000)
    evaluation = answered['latest_evaluation']
    assert (evaluation['score'], evaluation['risk'], evaluation['scored_limit_rub'], evaluation['outcome']) == (total, 'low', limit, 'MANUAL_REVIEW')
    assert evaluation['rule'] == 'R8'  # what the rules alone would decide; the officer still reviews the answer
    assert (answered['status'], answered['scored_limit_rub'], answered['preapproved_amount_rub']) == ('MANUAL_REVIEW', limit, None)
    staff = detail(officer, answered)['application']
    assert staff['preapproval'] == {'amount_min_rub': 300_000, 'amount_max_rub': 700_000, 'blocked_by': None}
    assert len(bki_calls) == 1


def test_null_finance_becomes_preapprovable_once_the_answers_make_the_limit_computable(client, officer, bki_calls):
    application = submitted(client, 'missing_turnover', answers={'monthly_revenue_rub': 0, 'previous_monthly_revenue_rub': 0})
    assert (application['status'], application['latest_evaluation']['rule'], application['scored_limit_rub']) == ('MANUAL_REVIEW', 'R5', None)
    application = claimed(officer, application)
    refused(preapprove(officer, application, 1_000_000), 409, 'LIMIT_NOT_COMPUTABLE')
    application = ok(request_info(officer, application, ['monthly_revenue_rub', 'previous_monthly_revenue_rub'],
                                  reason='Укажите выручку: нулевые значения не позволяют рассчитать лимит.'))
    answered = ok(respond(client, application, {'monthly_revenue_rub': 800_000, 'previous_monthly_revenue_rub': 680_000}))
    total = oracle.score(48, 800_000, 680_000, 160_000, 'clean')
    limit = oracle.scored_limit(TERM, oracle.risk(total), 800_000)
    evaluation = answered['latest_evaluation']
    assert (evaluation['score'], evaluation['scored_limit_rub'], evaluation['rule'], evaluation['outcome']) == (total, limit, 'R5', 'MANUAL_REVIEW')
    (_, latest) = evaluations(client, application)
    assert latest.input_snapshot['review_flags'] == ['declared_finance']  # the declaration is still flagged
    assert latest.input_snapshot['finance']['monthly_revenue_rub']['origin'] == 'declared'
    staff = detail(officer, answered)['application']
    assert staff['preapproval'] == {'amount_min_rub': 300_000, 'amount_max_rub': 1_000_000, 'blocked_by': None}
    assert ok(preapprove(officer, staff, 1_000_000))['preapproved_amount_rub'] == 1_000_000
    assert len(bki_calls) == 1


def test_conflict_flags_are_retained_after_the_client_aligns_an_override(client, officer):
    application = asked(client, officer, 'strong', ['previous_monthly_revenue_rub'], answers={'previous_monthly_revenue_rub': 800_000})
    answered = ok(respond(client, application, {'previous_monthly_revenue_rub': 680_000}))  # now equals the source
    first, second = evaluations(client, application)
    assert first.input_snapshot['review_flags'] == ['finance_override']
    assert second.input_snapshot['finance']['previous_monthly_revenue_rub']['origin'] == 'source'
    assert second.input_snapshot['review_flags'] == ['finance_override'] and second.rule == 'R5'
    assert (answered['status'], answered['latest_evaluation']['score']) == ('MANUAL_REVIEW', oracle.score(48, 800_000, 680_000, 160_000, 'clean'))


def test_collateral_details_are_answered_by_their_own_paths(client, officer):
    application = asked(client, officer, 'secured_investment', ['collateral.encumbered'],
                        answers={'collateral': {'encumbered': True}})
    error = refused(respond(client, application, {'collateral': {'encumbered': False, 'type': 'vehicle'}}), 422, 'ANSWER_NOT_REQUESTED')
    assert set(error['fields']) == {'collateral.type'}
    answered = ok(respond(client, application, {'collateral': {'encumbered': False}}))
    assert answered['answers']['collateral'] == {**application['answers']['collateral'], 'encumbered': False}  # merged by key
    assert answered['answers']['collateral']['declared_value_rub'] == 8_000_000
    evaluation = answered['latest_evaluation']  # secured low risk: min(6m, 3 x 1.5m, 70% of 8m) = 4.5m; 4m requested
    assert (evaluation['rule'], evaluation['outcome'], evaluation['scored_limit_rub']) == ('R8', 'MANUAL_REVIEW', 4_500_000)


@pytest.mark.parametrize('answers,response,status,code,fields', [
    ({'monthly_debt_payment_rub': 240_000, 'employees': 3}, 'Ответ', 422, 'ANSWER_NOT_REQUESTED', {'employees'}),
    ({}, 'Ответ', 422, 'NEED_INFO', {'monthly_debt_payment_rub'}),
    ({'monthly_debt_payment_rub': None}, 'Ответ', 422, 'NEED_INFO', {'monthly_debt_payment_rub'}),
    ({'monthly_debt_payment_rub': -1}, 'Ответ', 422, 'VALIDATION_ERROR', None),
    ({'monthly_debt_payment_rub': '240000'}, 'Ответ', 422, 'VALIDATION_ERROR', None),
    ({'credit_history': 'clean'}, 'Ответ', 422, 'VALIDATION_ERROR', None),
    ({'monthly_debt_payment_rub': 240_000}, '   ', 422, 'VALIDATION_ERROR', None),
    ({'monthly_debt_payment_rub': 240_000}, 'я' * 2001, 422, 'VALIDATION_ERROR', None),
])
def test_respond_info_accepts_only_valid_answers_to_the_requested_fields(client, officer, bki_calls, answers, response, status, code, fields):
    application = asked(client, officer, 'medium', ['monthly_debt_payment_rub'])
    error = refused(respond(client, application, answers, response=response), status, code)
    if fields is not None:
        assert set(error['fields']) == fields
    assert read(client, application)['status'] == 'NEED_INFO' and read(client, application)['version'] == application['version']
    (request,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert (request.response, request.resolved_at) == (None, None)
    assert len(evaluations(client, application)) == 1 and len(bki_calls) == 1


def test_a_response_cannot_drop_the_pledge_a_secured_product_requires(client, officer):
    application = asked(client, officer, 'secured_investment', ['collateral'], answers={'collateral': {'encumbered': True}})
    error = refused(respond(client, application, {'collateral': {'status': 'none'}}), 422, 'NEED_INFO')  # R3 on the merged answers
    assert set(error['fields']) == {'collateral'}
    assert ok(respond(client, application, {'collateral': {'encumbered': False}}))['answers']['collateral']['status'] == 'declared'


def test_a_response_never_rewrites_the_requested_amount(client, officer):
    application = asked(client, officer, 'medium', ['employees'], requested_amount_rub=700_000)
    error = refused(respond(client, application, {'employees': 5, 'requested_amount_rub': 450_000}), 422, 'NEED_FIELDS_LOCKED')
    assert set(error['fields']) == {'requested_amount_rub'}
    answered = ok(respond(client, application, {'employees': 5}))
    assert (answered['requested_amount_rub'], answered['answers']['requested_amount_rub']) == (700_000, 700_000)
    assert answered['latest_evaluation']['rule'] == 'R11'  # still compared with the original 700,000 (limit 600,000)
    (_, latest) = evaluations(client, application)
    assert latest.input_snapshot['answers']['requested_amount_rub'] == 700_000
    staff = detail(officer, answered)['application']
    assert staff['preapproval']['amount_max_rub'] == MEDIUM_LIMIT  # min(original 700,000, scored limit 600,000)
    refused(preapprove(officer, staff, MEDIUM_LIMIT + 1), 422, 'AMOUNT_OUT_OF_BOUNDS')


def internal_gap(client, application: dict) -> dict:
    """The defensive client-answers gap of an internal check (Task 4a): the draft reaches the check without the submit
    gate, as a submitted application whose answers still miss required values."""
    from app.applications import checks
    from app.applications.lifecycle import ApplicationChange
    from app.applications.models import Application
    from app.models import Company
    from app.recommendations.catalog import CONFIG
    with client.app.state.test_factory.begin() as db:
        row = db.get(Application, application['id'])
        row.submitted_at = FIXED_NOW
        change = ApplicationChange(db, row, actor_id=None, now=FIXED_NOW)
        change.move('CHECKING', reason_code='SUBMITTED', reason_text='Проверка без шлюза анкеты')
        checks.run_check(db, change, db.get(Company, row.company_id), CONFIG.product(TERM))
    return read(client, application)


def test_a_system_request_for_a_need_field_cannot_rewrite_the_need_either(client, bki_calls):
    application = draft(client, 'strong')
    cleared = client.patch(f"/api/v1/applications/{application['id']}/answers",
                           json={'version': application['version'], 'current_stage': 2, 'answers': {'requested_amount_rub': None}})
    assert cleared.status_code == 200, cleared.text
    application = internal_gap(client, cleared.json()['application'])
    assert application['status'] == 'NEED_INFO' and 'requested_amount_rub' in application['missing_fields']
    error = refused(respond(client, application, {'requested_amount_rub': 500_000}), 422, 'NEED_FIELDS_LOCKED')
    assert set(error['fields']) == {'requested_amount_rub'}
    assert read(client, application)['status'] == 'NEED_INFO' and bki_calls == []


def test_a_trusted_source_request_cannot_be_answered_by_the_client(client, officer, bki_calls):
    application = submitted(client, 'bki_missing')
    assert application['open_info_request']['kind'] == 'trusted_source'
    assert application['allowed_actions'] == ['retry_check', 'cancel']  # never respond_info
    for answers in ({}, {'employees': 3}):
        refused(respond(client, application, answers), 409, 'TRUSTED_SOURCE_REQUIRED')
    refused(respond(client, application, {'credit_history': 'clean'}), 422, 'VALIDATION_ERROR')  # never accepts BKI fields
    assert read(client, application) == application and len(evaluations(client, application)) == 1
    (request,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert (request.response, request.resolved_at) == (None, None) and len(bki_calls) == 1


def test_respond_info_needs_an_open_client_answers_request_and_the_current_version(client, officer):
    review = submitted(client, 'medium')
    refused(respond(client, review, {'employees': 3}), 409, 'INVALID_STATUS')
    waiting = submitted(client, 'bki_unavailable')
    refused(respond(client, waiting, {'employees': 3}), 409, 'INVALID_STATUS')
    application = ok(request_info(officer, claimed(officer, review), ['employees']))
    refused(respond(client, application, {'employees': 3}, version=review['version']), 409, 'VERSION_CONFLICT')
    client.post('/api/v1/auth/logout', json={})
    register(client, 'other@example.test')
    refused(respond(client, application, {'employees': 3}), 404, 'APPLICATION_NOT_FOUND')
    refused(client.get(f"/api/v1/applications/{application['id']}/history"), 404, 'APPLICATION_NOT_FOUND')


def test_a_response_to_a_system_request_is_queued_unassigned(client, officer, bki_calls):
    """The defensive client-answers gap of an internal check (Task 4a) closes through respond-info."""
    application = internal_gap(client, draft(client, 'missing_turnover'))
    assert application['status'] == 'NEED_INFO' and application['allowed_actions'] == ['respond_info', 'cancel']
    answers = {'company_confirmed': True, 'actual_address': 'Демо-адрес', 'actual_activity': 'Торговля', 'tax_regime': 'USN',
               'employees': 3, 'monthly_debt_payment_rub': 160_000, 'tax_debt_rub': 0, 'legal_proceedings': False,
               'representative_name': 'Демо Представитель', 'representative_authority_confirmed': True,
               'beneficial_owners_confirmed': True, 'accuracy_confirmed': True,
               'monthly_revenue_rub': 800_000, 'previous_monthly_revenue_rub': 680_000}
    answers = {name: value for name, value in answers.items() if name in application['missing_fields']}
    assert set(answers) == set(application['missing_fields'])
    answered = ok(respond(client, application, answers))
    assert answered['status'] == 'MANUAL_REVIEW' and bki_calls == []
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.assignee_id is None  # a system request has no officer: the case waits in the queue
    queued = officer.get('/api/v1/officer/applications', params={'assignee': 'unassigned', 'status': 'MANUAL_REVIEW'}).json()
    assert [item['id'] for item in queued['items']] == [application['id']]
    evaluation = answered['latest_evaluation']
    assert (evaluation['rule'], evaluation['outcome'], evaluation['score']) == ('R5', 'MANUAL_REVIEW', None)  # no BKI evidence yet
    staff = detail(officer, answered)['application']
    assert staff['allowed_actions'] == ['claim']
    assert ok(claim(officer, staff))['preapproval']['blocked_by']['code'] == 'LIMIT_NOT_COMPUTABLE'


def test_open_requests_on_terminal_applications_stay_as_unresolved_audit_rows(client, officer):
    application = asked(client, officer, 'medium', ['employees'])
    cancelled = ok(cancel(client, application))
    assert cancelled['status'] == 'CANCELLED' and cancelled['open_info_request'] is None and cancelled['allowed_actions'] == []
    (request,) = rows(client, 'InfoRequest', application_id=application['id'])
    assert request.resolved_at is None
    body = detail(officer, application)
    assert body['application']['open_info_request'] is None and body['application']['allowed_actions'] == []
    (shown,) = body['info_requests']
    assert (shown['open'], shown['resolved_at'], shown['response']) == (False, None, None)
    refused(respond(client, cancelled, {'employees': 3}), 409, 'INVALID_STATUS')


def test_another_officer_sees_the_request_but_cannot_decide(client, officer, second_officer):
    application = asked(client, officer, 'medium', ['employees'])
    answered = ok(respond(client, application, {'employees': 5}))
    body = detail(second_officer, answered)
    assert body['application']['allowed_actions'] == [] and body['application']['assignee']['id'] == officer.user['id']
    refused(preapprove(second_officer, answered, 300_000), 409, 'ASSIGNMENT_REQUIRED')
    refused(claim(second_officer, answered), 409, 'ALREADY_ASSIGNED')
    assert second_officer.get(staff_url(answered)).json()['history'][3]['actor']['display_name'] == officer.user['display_name']


def stored_overdue_of_thirty_days(client, application):
    from sqlalchemy import select
    from app.applications.models import Evaluation
    with client.app.state.test_factory.begin() as db:
        row = db.scalars(select(Evaluation).where(Evaluation.application_id == application['id'])).one()
        row.sources = {**row.sources, 'bki': {**row.sources['bki'], 'current_overdue_days': 30}}


@pytest.mark.parametrize('stop', ['company_inactive', 'stored_overdue'])
def test_a_response_rechecked_into_a_mandatory_stop_keeps_the_declaration_flag(client, officer, stop):
    application = asked(client, officer, 'missing_turnover', ['employees'],
                        answers={'monthly_revenue_rub': 800_000, 'previous_monthly_revenue_rub': 680_000})  # declared → R5
    assert evaluations(client, application)[0].input_snapshot['review_flags'] == ['declared_finance']
    if stop == 'company_inactive':
        set_company(client, application['company_id'], registry_status='inactive')
    else:
        stored_overdue_of_thirty_days(client, application)
    answered = ok(respond(client, application, {'employees': 5}))
    assert (answered['status'], answered['latest_evaluation']['rule']) == ('MANUAL_REVIEW', 'R2')
    assert evaluations(client, application)[1].input_snapshot['review_flags'] == ['declared_finance']
    assert detail(officer, answered)['application']['preapproval']['blocked_by']['code'] == 'MANDATORY_STOP'


def test_the_info_request_guard_keeps_need_fields_for_system_requests_only(client, officer):
    from app.applications.info_requests import create_info_request
    from app.applications.models import Application
    application = claimed(officer, submitted(client, 'medium'))
    with client.app.state.test_factory() as db:
        row = db.get(Application, application['id'])
        for name in NEED:
            with pytest.raises(ValueError):
                create_info_request(db, row, kind='client_answers', source=None, requested_fields=[name], question='Вопрос',
                                    now=FIXED_NOW, officer_id=officer.user['id'])
        system = create_info_request(db, row, kind='client_answers', source=None, requested_fields=list(NEED),
                                     question='Не хватает параметров', now=FIXED_NOW)  # built from a check's missing answers
        assert system.requested_fields == NEED and system.officer_id is None
        db.rollback()
