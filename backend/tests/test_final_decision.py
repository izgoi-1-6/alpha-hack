"""Officer document review, final approval and the simulated Alfa-Business handoff over HTTP + DB + private storage:
review guards and reasons, the verified collateral value, DOCS_REWORK and replacement, approval only with every
required document accepted and within product_min <= final <= min(preapproved, the recomputed verified bound), the
below-minimum refusal, final-phase rejections with incomplete packets, lazy expiry, idempotent replays, the staff
views and DB constraints, and the A09/A10 journeys.

Amounts are the acceptance document's literal numbers and integer arithmetic on the spec's 70% LTV, never the code
under test.
"""
from datetime import timedelta
import json
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from application_helpers import clock, history, read, relogin, rows
from document_helpers import (DEADLINE, SECURED_DOCS, UNSECURED_DOCS, accept_all, approve, checklist, complete_docs,
                              completed, delete, document_rows, download, in_review, link, pdf_bytes, png_bytes,
                              preapproved, review, reviewed, storage, stored, upload, upload_all, uploaded)
from officer_helpers import (OFFICER_EMAIL, claimed, decisions, detail, login, ok, officer, refused, reject,
                             second_officer)
from test_identity_company import ORIGIN, client, register

pytestmark = pytest.mark.usefixtures('clock', 'storage')
TERM_MIN, SECURED_MIN = 300_000, 500_000  # spec product table
STRONG_PREAPPROVED, STRONG_LIMIT = 2_000_000, 2_400_000  # acceptance: strong R8 2m, limit 2.4m
SECURED_PREAPPROVED = 4_000_000  # acceptance: secured_investment R8 4m (limit 4.5m)
REASON = 'Демонстрационная проверка документов: всё сходится.'


def ltv_cap(value: int) -> int:
    return value * 7000 // 10000  # spec: floor(value x 70%)


def history_rows(client, application):
    return sorted(rows(client, 'StatusHistory', application_id=application['id']), key=lambda row: row.sequence)


# --- document review -------------------------------------------------------------------------------------------------

def test_document_review_needs_the_assignee_the_current_version_and_docs_uploaded(client, officer, second_officer):
    application, documents = upload_all(client, preapproved(client))
    staff = claimed(officer, application)
    refused(review(officer, staff, documents['BANK_STATEMENT']), 409, 'INVALID_STATUS')  # PREAPPROVED: packet not sent
    application = completed(client, read(client, application))
    refused(review(second_officer, application, documents['BANK_STATEMENT']), 409, 'ASSIGNMENT_REQUIRED')
    refused(review(officer, application, documents['BANK_STATEMENT'], version=application['version'] - 1), 409, 'VERSION_CONFLICT')
    refused(review(client, application, documents['BANK_STATEMENT']), 403, 'OFFICER_REQUIRED')
    refused(review(officer, application, {'id': '00000000-0000-4000-8000-000000000000'}), 404, 'DOCUMENT_NOT_FOUND')
    assert all(row.status == 'UPLOADED' and row.reviewer_id is None for row in document_rows(client))


@pytest.mark.parametrize('body', [{'reason': ''}, {'reason': '   '}, {'reason': 'x' * 2001}, {'decision': 'maybe'},
                                  {'status': 'ACCEPTED'}, {'reviewer_id': 'x'}, {'verified_value_rub': 0},
                                  {'verified_value_rub': -1}, {'verified_value_rub': '5000000'}, {'verified_value_rub': 1.5}])
def test_review_bodies_are_strict(client, officer, body):
    application, documents = in_review(client, officer)
    payload = {'decision': 'accept', 'reason': REASON, **body}
    response = review(officer, application, documents['BANK_STATEMENT'], payload.pop('decision'), payload.pop('reason'), extra=payload)
    refused(response, 422, 'VALIDATION_ERROR')
    assert all(row.status == 'UPLOADED' for row in document_rows(client))


def test_accepting_records_reviewer_reason_and_time_without_a_status_change(client, officer):
    application, documents = in_review(client, officer)
    document, result = reviewed(officer, application, documents['BANK_STATEMENT'], reason='  Выписка читается.  ')
    assert (document['status'], document['review_reason'], document['reviewed_at']) == ('ACCEPTED', 'Выписка читается.', '2026-10-24T12:00:00Z')
    assert document['verified_value_rub'] is None and document['reviewer'] == {'id': officer.user['id'], 'display_name': officer.user['display_name']}
    assert result['status'] == 'DOCS_UPLOADED' and result['version'] == application['version'] + 1
    assert [row.to_status for row in history_rows(client, application)][-1] == 'DOCS_UPLOADED'  # no history row
    (row,) = [row for row in document_rows(client) if row.document_type == 'BANK_STATEMENT']
    assert (row.status, row.reviewer_id, row.review_reason) == ('ACCEPTED', officer.user['id'], 'Выписка читается.')
    refused(review(officer, result, documents['BANK_STATEMENT']), 409, 'DOCUMENT_NOT_REVIEWABLE')  # reviewed once
    customer = checklist(client, application)['requirements'][0]['current_document']
    assert customer['status'] == 'ACCEPTED' and customer['review_reason'] == 'Выписка читается.'
    assert officer.user['id'] not in json.dumps(checklist(client, application)) + json.dumps(read(client, application))


def test_a_rejected_document_moves_the_packet_to_rework_and_accepted_ones_stay_fixed(client, officer, storage):
    application, documents = in_review(client, officer)
    _, application = reviewed(officer, application, documents['BANK_STATEMENT'])
    rejected, result = reviewed(officer, application, documents['FINANCIAL_REPORT'], 'reject', reason='Отчёт за другой период.')
    assert rejected['status'] == 'REJECTED' and result['status'] == 'DOCS_REWORK'
    last = history_rows(client, application)[-1]
    assert (last.from_status, last.to_status, last.actor_id, last.reason_code, last.reason_text) == (
        'DOCS_UPLOADED', 'DOCS_REWORK', officer.user['id'], 'DOCUMENT_REJECTED', 'Отчёт за другой период.')
    note = rows(client, 'Notification', status_history_id=last.id)[0]
    assert note.event_code == 'application_docs_rework' and 'финансовая отчётность' in note.message.lower()
    customer = read(client, application)
    assert customer['document_summary'] == {'required_total': 2, 'current_uploaded': 2, 'accepted': 1, 'rejected': 1,
                                            'missing': [], 'can_complete': False}
    assert customer['allowed_actions'] == ['upload_document', 'delete_document', 'cancel']
    response = complete_docs(client, customer)
    refused(response, 409, 'DOCUMENTS_INCOMPLETE')
    assert response.json()['error']['details'] == {'missing': [], 'rejected': ['FINANCIAL_REPORT']}
    before = stored(storage)
    refused(upload(client, customer, 'BANK_STATEMENT'), 409, 'DOCUMENT_ACCEPTED')  # accepted evidence is never replaced
    refused(delete(client, customer, documents['BANK_STATEMENT']), 409, 'DOCUMENT_ACCEPTED')
    refused(review(officer, result, documents['BANK_STATEMENT']), 409, 'INVALID_STATUS')  # reviews wait for the next packet
    assert stored(storage) == before


def test_the_owner_may_delete_a_rejected_current_file_and_the_requirement_reopens(client, officer, storage):
    """Ruling: a REJECTED current revision is deletable; the DELETED row keeps its review, the bytes go."""
    application, documents = in_review(client, officer)
    rejected = documents['FINANCIAL_REPORT']
    _, application = reviewed(officer, application, rejected, 'reject', reason='Отчёт за другой период.')
    customer = read(client, application)
    assert customer['allowed_actions'] == ['upload_document', 'delete_document', 'cancel']
    (before,) = document_rows(client, document_type='FINANCIAL_REPORT')
    response = delete(client, customer, rejected)
    assert response.status_code == 200, response.text
    customer = response.json()['application']
    (row,) = document_rows(client, document_type='FINANCIAL_REPORT')
    assert (row.status, row.review_reason, row.reviewer_id) == ('DELETED', 'Отчёт за другой период.', officer.user['id'])
    assert before.storage_key not in stored(storage) and len(stored(storage)) == 1  # the statement stays
    refused(download(client, customer, rejected), 404, 'DOCUMENT_NOT_FOUND')
    refused(download(officer, customer, rejected), 404, 'DOCUMENT_NOT_FOUND')
    assert customer['document_summary'] == {'required_total': 2, 'current_uploaded': 1, 'accepted': 0, 'rejected': 0,
                                            'missing': ['FINANCIAL_REPORT'], 'can_complete': False}
    assert customer['allowed_actions'] == ['upload_document', 'delete_document', 'cancel']
    staff_row = next(item for item in detail(officer, application)['documents'] if item['id'] == rejected['id'])
    assert (staff_row['status'], staff_row['review_reason'], staff_row['download_url']) == ('DELETED', 'Отчёт за другой период.', None)
    replacement, customer = uploaded(client, customer, 'FINANCIAL_REPORT', png_bytes(), kind='png')
    assert (replacement['revision'], replacement['status']) == (2, 'UPLOADED')
    assert completed(client, customer)['status'] == 'DOCS_UPLOADED'


def test_only_an_accepted_valuation_carries_a_positive_verified_value(client, officer):
    application, documents = in_review(client, officer, 'secured_investment')
    valuation, statement = documents['COLLATERAL_VALUATION'], documents['BANK_STATEMENT']
    refused(review(officer, application, statement, verified_value_rub=5_000_000), 422, 'VERIFIED_VALUE_NOT_ALLOWED')
    refused(review(officer, application, valuation), 422, 'VERIFIED_VALUE_REQUIRED')
    refused(review(officer, application, valuation, 'reject', verified_value_rub=5_000_000), 422, 'VERIFIED_VALUE_NOT_ALLOWED')
    assert all(row.status == 'UPLOADED' and row.verified_value_rub is None for row in document_rows(client))
    document, _ = reviewed(officer, application, valuation, verified_value_rub=5_000_000)
    assert (document['status'], document['verified_value_rub']) == ('ACCEPTED', 5_000_000)
    (row,) = document_rows(client, document_type='COLLATERAL_VALUATION')
    assert (row.status, row.verified_value_rub, row.reviewer_id) == ('ACCEPTED', 5_000_000, officer.user['id'])


def test_a_replaced_valuation_starts_without_a_verified_value(client, officer):
    application, documents = in_review(client, officer, 'secured_investment')
    _, application = reviewed(officer, application, documents['COLLATERAL_VALUATION'], 'reject', reason='Оценка устарела.')
    replacement, customer = uploaded(client, read(client, application), 'COLLATERAL_VALUATION')
    assert (replacement['revision'], replacement['status'], replacement['verified_value_rub']) == (2, 'UPLOADED', None)
    application = completed(client, customer)
    assert [(row.revision, row.status, row.verified_value_rub) for row in document_rows(client, document_type='COLLATERAL_VALUATION')] == [
        (1, 'SUPERSEDED', None), (2, 'UPLOADED', None)]
    staff = detail(officer, application)['application']
    assert staff['final_approval']['blocked_by']['code'] == 'DOCUMENTS_NOT_ACCEPTED'


def test_review_replays_record_once(client, officer):
    application, documents = in_review(client, officer)
    first = review(officer, application, documents['FINANCIAL_REPORT'], 'reject', reason='Нужна подпись.', key='review-once')
    again = review(officer, application, documents['FINANCIAL_REPORT'], 'reject', reason='Нужна подпись.', key='review-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    refused(review(officer, application, documents['FINANCIAL_REPORT'], 'accept', key='review-once'), 409, 'IDEMPOTENCY_CONFLICT')
    assert [row.to_status for row in history_rows(client, application)].count('DOCS_REWORK') == 1


# --- final approval --------------------------------------------------------------------------------------------------

def test_approval_needs_every_required_document_accepted(client, officer):
    application, documents = in_review(client, officer)
    for amount in (TERM_MIN, STRONG_PREAPPROVED):
        response = approve(officer, application, amount)
        refused(response, 409, 'DOCUMENTS_NOT_ACCEPTED')
    _, application = reviewed(officer, application, documents['BANK_STATEMENT'])
    refused(approve(officer, application, STRONG_PREAPPROVED), 409, 'DOCUMENTS_NOT_ACCEPTED')  # one still pending
    staff = detail(officer, application)['application']
    assert staff['allowed_actions'] == ['review_document', 'reject']
    assert staff['final_approval']['blocked_by']['code'] == 'DOCUMENTS_NOT_ACCEPTED'
    assert (staff['final_approval']['amount_min_rub'], staff['final_approval']['amount_max_rub']) == (None, None)
    assert decisions(client, application) == [] and read(client, application)['status'] == 'DOCS_UPLOADED'


@pytest.mark.parametrize('amount,accepted', [(TERM_MIN - 1, False), (TERM_MIN, True), (STRONG_PREAPPROVED, True),
                                             (STRONG_PREAPPROVED + 1, False), (STRONG_LIMIT, False)])
def test_the_final_amount_is_bounded_by_the_product_minimum_and_the_preapproved_amount(client, officer, amount, accepted):
    application, documents = in_review(client, officer)
    application = accept_all(officer, application, documents)
    staff = detail(officer, application)['application']
    assert staff['final_approval'] == {'amount_min_rub': TERM_MIN, 'amount_max_rub': STRONG_PREAPPROVED,
                                       'verified_limit_rub': STRONG_LIMIT, 'blocked_by': None}
    assert staff['allowed_actions'] == ['approve', 'reject']
    response = approve(officer, application, amount)
    if accepted:
        result = ok(response)
        assert (result['status'], result['final_amount_rub'], result['preapproved_amount_rub'], result['requested_amount_rub']) == (
            'APPROVED', amount, STRONG_PREAPPROVED, 2_000_000)
        (decision,) = decisions(client, application)
        assert (decision.phase, decision.action, decision.amount_rub, decision.officer_id) == ('final', 'approve', amount, officer.user['id'])
    else:
        error = response.json()['error']
        assert response.status_code == 422 and error['code'] == 'AMOUNT_OUT_OF_BOUNDS'
        assert error['details'] == {'amount_min_rub': TERM_MIN, 'amount_max_rub': STRONG_PREAPPROVED} and 'amount_rub' in error['fields']
        assert decisions(client, application) == [] and read(client, application)['final_amount_rub'] is None


def test_approval_is_for_the_assignee_on_the_current_version_in_docs_uploaded(client, officer, second_officer):
    application, documents = in_review(client, officer)
    application = accept_all(officer, application, documents)
    refused(approve(second_officer, application, STRONG_PREAPPROVED), 409, 'ASSIGNMENT_REQUIRED')
    refused(approve(officer, application, STRONG_PREAPPROVED, version=application['version'] - 1), 409, 'VERSION_CONFLICT')
    refused(approve(client, application, STRONG_PREAPPROVED), 403, 'OFFICER_REQUIRED')
    for body in ({'reason': ''}, {'amount_rub': 0}, {'status': 'APPROVED'}, {'final_amount_rub': 1}):
        payload = {'version': application['version'], 'amount_rub': STRONG_PREAPPROVED, 'reason': REASON, **body}
        response = officer.post(f"/api/v1/officer/applications/{application['id']}/approve", json=payload,
                                headers={'Idempotency-Key': os.urandom(8).hex()})
        refused(response, 422, 'VALIDATION_ERROR')
    first = approve(officer, application, STRONG_PREAPPROVED, key='approve-once')
    again = approve(officer, application, STRONG_PREAPPROVED, key='approve-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    refused(approve(officer, application, TERM_MIN, key='approve-once'), 409, 'IDEMPOTENCY_CONFLICT')
    refused(approve(officer, application, STRONG_PREAPPROVED, key='approve-twice'), 409, 'VERSION_CONFLICT')
    assert len(decisions(client, application)) == 1
    assert [row.to_status for row in history_rows(client, application)].count('APPROVED') == 1


@pytest.mark.parametrize('status', ['PREAPPROVED', 'DOCS_REWORK'])
def test_approval_outside_docs_uploaded_is_invalid(client, officer, status):
    application, documents = upload_all(client, preapproved(client))
    if status == 'DOCS_REWORK':
        application = claimed(officer, completed(client, application))
        _, application = reviewed(officer, application, documents['BANK_STATEMENT'], 'reject', reason='Замените выписку.')
    else:
        application = claimed(officer, application)
    refused(approve(officer, application, STRONG_PREAPPROVED), 409, 'INVALID_STATUS')
    assert decisions(client, application) == []


# --- secured: verified valuation -------------------------------------------------------------------------------------

def secured_ready(client, officer, valuation: int) -> dict:
    application, documents = in_review(client, officer, 'secured_investment')
    return accept_all(officer, application, documents, valuation=valuation)


def test_the_secured_bound_is_recomputed_from_the_verified_valuation(client, officer):
    """Acceptance: verified collateral 5m caps at 3.5m — the original 4m cannot be approved, at most 3.5m can."""
    application = secured_ready(client, officer, 5_000_000)
    cap = ltv_cap(5_000_000)
    assert cap == 3_500_000
    staff = detail(officer, application)['application']
    assert staff['final_approval'] == {'amount_min_rub': SECURED_MIN, 'amount_max_rub': cap, 'verified_limit_rub': cap, 'blocked_by': None}
    response = approve(officer, application, SECURED_PREAPPROVED)
    refused(response, 422, 'AMOUNT_OUT_OF_BOUNDS')
    assert response.json()['error']['details'] == {'amount_min_rub': SECURED_MIN, 'amount_max_rub': cap}
    refused(approve(officer, application, cap + 1), 422, 'AMOUNT_OUT_OF_BOUNDS')
    # A process restart: a fresh officer session reads only persisted evidence (the accepted valuation row).
    with TestClient(app, headers={'origin': ORIGIN}) as restarted:
        login(restarted, OFFICER_EMAIL)
        assert detail(restarted, application)['application']['final_approval']['amount_max_rub'] == cap
        refused(approve(restarted, application, SECURED_PREAPPROVED), 422, 'AMOUNT_OUT_OF_BOUNDS')
        result = ok(approve(restarted, application, cap))
    assert (result['status'], result['final_amount_rub'], result['preapproved_amount_rub']) == ('APPROVED', cap, SECURED_PREAPPROVED)
    assert read(client, application)['answers']['collateral']['declared_value_rub'] == 8_000_000  # the declaration is untouched


def test_a_higher_verified_value_never_lifts_the_final_amount_above_the_preapproval(client, officer):
    application = secured_ready(client, officer, 8_000_000)  # cap 5.6m, turnover 4.5m: the preapproved 4m binds
    assert detail(officer, application)['application']['final_approval']['amount_max_rub'] == SECURED_PREAPPROVED
    refused(approve(officer, application, SECURED_PREAPPROVED + 1), 422, 'AMOUNT_OUT_OF_BOUNDS')
    assert ok(approve(officer, application, SECURED_PREAPPROVED))['final_amount_rub'] == SECURED_PREAPPROVED


@pytest.mark.parametrize('valuation,approvable', [(714_285, False), (714_286, True)])
def test_a_verified_bound_below_the_product_minimum_refuses_approval(client, officer, valuation, approvable):
    """Acceptance: 714,285 caps at 499,999 (< 500,000 minimum), 714,286 at exactly 500,000."""
    application = secured_ready(client, officer, valuation)
    cap = ltv_cap(valuation)
    final = detail(officer, application)['application']['final_approval']
    if approvable:
        assert cap == SECURED_MIN and final['amount_max_rub'] == SECURED_MIN and final['blocked_by'] is None
        assert ok(approve(officer, application, SECURED_MIN))['final_amount_rub'] == SECURED_MIN
        return
    assert cap == 499_999 and final['verified_limit_rub'] == cap and final['blocked_by']['code'] == 'COLLATERAL_INSUFFICIENT'
    for amount in (SECURED_MIN, cap):
        refused(approve(officer, application, amount), 409, 'COLLATERAL_INSUFFICIENT')
    assert 'approve' not in detail(officer, application)['application']['allowed_actions']
    result = ok(reject(officer, application, reason='Проверенная стоимость залога недостаточна для минимальной суммы.'))
    assert result['status'] == 'REJECTED' and result['final_amount_rub'] is None
    assert [(row.phase, row.action) for row in decisions(client, application)] == [('final', 'reject')]


# --- final-phase rejection with incomplete or unaccepted packets -----------------------------------------------------

@pytest.mark.parametrize('status', ['PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK'])
def test_a_final_rejection_needs_no_complete_or_accepted_packet(client, officer, storage, status):
    application = preapproved(client)
    document, application = uploaded(client, application, 'BANK_STATEMENT')  # one of two documents only
    if status != 'PREAPPROVED':
        _, application = uploaded(client, application, 'FINANCIAL_REPORT')
        application = completed(client, application)
    application = claimed(officer, application)
    if status == 'DOCS_REWORK':
        _, application = reviewed(officer, application, document, 'reject', reason='Нечитаемо.')
    assert application['status'] == status and 'reject' in application['allowed_actions']
    result = ok(reject(officer, application, reason='Финальная проверка: отказ.'))
    assert result['status'] == 'REJECTED'
    last = history_rows(client, application)[-1]
    assert (last.from_status, last.reason_code) == (status, 'FINAL_REJECTED')
    before = stored(storage)
    refused(upload(client, read(client, application), 'FINANCIAL_REPORT'), 409, 'INVALID_STATUS')
    assert stored(storage) == before and download(client, application, document).status_code == 200


# --- expiry ----------------------------------------------------------------------------------------------------------

def test_approval_one_second_before_the_deadline_is_final_and_never_expires(client, officer, clock):
    application, documents = in_review(client, officer)
    application = accept_all(officer, application, documents)
    clock.now = DEADLINE - timedelta(seconds=1)
    login(officer, OFFICER_EMAIL)
    assert ok(approve(officer, application, STRONG_PREAPPROVED))['status'] == 'APPROVED'
    clock.now = DEADLINE + timedelta(days=30)
    relogin(client)
    assert read(client, application)['status'] == 'APPROVED'
    assert checklist(client, application)['items'][0]['status'] == 'ACCEPTED'
    assert 'EXPIRED' not in [row.to_status for row in history_rows(client, application)]


@pytest.mark.parametrize('command', ['approve', 'review'])
def test_an_officer_document_command_at_the_deadline_records_the_expiry(client, officer, clock, command):
    application, documents = in_review(client, officer)
    if command == 'approve':
        application = accept_all(officer, application, documents)
    clock.now = DEADLINE
    login(officer, OFFICER_EMAIL)
    send = (lambda: approve(officer, application, STRONG_PREAPPROVED)) if command == 'approve' else (
        lambda: review(officer, application, documents['BANK_STATEMENT']))
    refused(send(), 409, 'APPLICATION_EXPIRED')
    assert [row.to_status for row in history_rows(client, application)].count('EXPIRED') == 1
    assert decisions(client, application) == [] and detail(officer, application)['application']['status'] == 'EXPIRED'


# --- the A09 journey and the handoff ---------------------------------------------------------------------------------

def test_a09_document_correction_journey_ends_in_a_simulated_handoff(client, officer, storage):
    application = preapproved(client)
    application, documents = upload_all(client, application)
    application = claimed(officer, completed(client, application))
    original = documents['FINANCIAL_REPORT']
    _, application = reviewed(officer, application, original, 'reject', reason='Отчёт без подписи руководителя.')
    replacement, customer = uploaded(client, read(client, application), 'FINANCIAL_REPORT', png_bytes(6, 6), kind='png')
    application = completed(client, customer)
    application = accept_all(officer, application, {'BANK_STATEMENT': documents['BANK_STATEMENT'], 'FINANCIAL_REPORT': replacement})
    result = ok(approve(officer, application, STRONG_PREAPPROVED, reason='Комплект принят, окончательное демо-решение.'))
    assert (result['status'], result['final_amount_rub']) == ('APPROVED', STRONG_PREAPPROVED)
    statuses = [(entry['to_status'], entry['reason_code'], entry['actor_role']) for entry in history(client, application)]
    assert statuses[-4:] == [('DOCS_UPLOADED', 'DOCUMENTS_SUBMITTED', 'client'), ('DOCS_REWORK', 'DOCUMENT_REJECTED', 'officer'),
                             ('DOCS_UPLOADED', 'DOCUMENTS_SUBMITTED', 'client'), ('APPROVED', 'FINAL_APPROVED', 'officer')]
    approved_note = history(client, application)[-1]['notification']['message']
    assert '2\u00a0000\u00a0000\u00a0₽' in approved_note and 'Деньги не перечисляются' in approved_note
    # The rejected original stays as audit evidence: superseded, with its reason, downloadable by owner and officer.
    items = {item['id']: item for item in checklist(client, application)['items']}
    assert (items[original['id']]['status'], items[original['id']]['review_reason']) == ('SUPERSEDED', 'Отчёт без подписи руководителя.')
    assert download(client, application, original).content == download(officer, application, original).content
    staff = detail(officer, application)
    assert {item['id']: item['status'] for item in staff['documents']} == {key: item['status'] for key, item in items.items()}
    assert len(stored(storage)) == 3
    customer = read(client, application)
    assert customer['allowed_actions'] == [] and customer['document_summary']['accepted'] == 2
    refused(upload(client, customer, 'FINANCIAL_REPORT'), 409, 'INVALID_STATUS')  # accepted evidence is final
    refused(delete(client, customer, replacement), 409, 'INVALID_STATUS')
    first = link(client, application, key='handoff')
    # The address bar shows the hand-off path: no demo wording (Task 10 fix round 1 ruling).
    assert first.status_code == 200 and first.json() == {'url': f"/alfa-business/{application['id']}", 'simulated': True}
    assert link(client, application, key='handoff').json() == first.json()
    assert read(client, application)['version'] == customer['version']  # the link changes nothing


def test_the_handoff_link_is_for_the_owner_of_an_approved_application_only(client, officer):
    application = preapproved(client)
    refused(link(client, application), 409, 'INVALID_STATUS')
    refused(link(officer, application), 403, 'CLIENT_REQUIRED')
    refused(link(client, application, body={'application_id': application['id'], 'url': 'https://evil.test'}), 422, 'VALIDATION_ERROR')
    refused(link(client, {'id': '00000000-0000-4000-8000-000000000000'}), 404, 'APPLICATION_NOT_FOUND')
    with TestClient(app, headers={'origin': ORIGIN}) as stranger:
        assert stranger.post('/api/v1/integrations/alfa-business/link', json={'application_id': application['id']},
                             headers={'Idempotency-Key': 'k'}).status_code == 401
        assert register(stranger, 'stranger@example.test').status_code == 201
        refused(link(stranger, application), 404, 'APPLICATION_NOT_FOUND')


# --- staff views -----------------------------------------------------------------------------------------------------

def test_requestable_fields_follow_the_product(client, officer):
    from app.applications.info_requests import NEED_FIELDS
    unsecured = detail(officer, preapproved(client))
    secured = detail(officer, preapproved(client, 'secured_investment'))
    for body in (unsecured, secured):
        assert body['requestable_fields'] and not set(body['requestable_fields']) & set(NEED_FIELDS)
        assert {'seasonal', 'monthly_debt_payment_rub', 'beneficial_owners_confirmed'} <= set(body['requestable_fields'])
        # Source-owned answers (registry, Госуслуги) are never asked of the client.
        assert not {'tax_regime', 'employees', 'representative_name', 'representative_authority_confirmed'} & set(body['requestable_fields'])
    assert not [path for path in unsecured['requestable_fields'] if path.split('.')[0] == 'collateral']
    assert {'collateral', 'collateral.declared_value_rub', 'collateral.owner_confirmed'} <= set(secured['requestable_fields'])


def test_staff_documents_name_the_reviewer_and_never_the_storage_key(client, officer):
    application, documents = in_review(client, officer)
    reviewed(officer, application, documents['BANK_STATEMENT'])
    body = detail(officer, application)
    assert [item['document_type'] for item in body['documents']] == UNSECURED_DOCS
    first = body['documents'][0]
    assert first['reviewer'] == {'id': officer.user['id'], 'display_name': officer.user['display_name']}
    assert body['documents'][1]['reviewer'] is None
    keys = [row.storage_key for row in document_rows(client)]
    assert not any(key in json.dumps(body) for key in keys)
    # The officer's review UI gets the same server-owned review notice as the customer's checklist.
    assert body['document_notice'] == checklist(client, application)['notice']
    assert body['document_notice'].startswith('Проверка документов')
    assert not any(key in json.dumps(checklist(client, application)) for key in keys)


# --- DB constraints --------------------------------------------------------------------------------------------------

def test_the_database_admits_one_current_document_per_requirement_and_only_valid_verified_values(client):
    from datetime import datetime, timezone
    from sqlalchemy.exc import IntegrityError
    from app.documents.models import Document
    application = preapproved(client)
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)

    def doc(revision, status='UPLOADED', document_type='BANK_STATEMENT', **values):
        fields = dict(application_id=application['id'], document_type=document_type, revision=revision, original_name='a.pdf',
                      media_type='application/pdf', size_bytes=10, sha256='0' * 64, storage_key=os.urandom(16).hex(),
                      status=status, created_at=now)
        return Document(**{**fields, **values})

    reviewed_fields = dict(reviewer_id=None, review_reason='ok', reviewed_at=now)
    with client.app.state.test_factory() as db:
        db.add_all([doc(1, 'SUPERSEDED'), doc(2, 'DELETED'), doc(3)])
        db.flush()
        db.rollback()
    officer_id = rows(client, 'StatusHistory', application_id=application['id'])[0].actor_id  # any existing user id
    bad = [[doc(1), doc(2)],  # two current documents for one requirement
           [doc(1, 'ACCEPTED', 'BANK_STATEMENT', **{**reviewed_fields, 'reviewer_id': officer_id}, verified_value_rub=5)],
           [doc(1, 'ACCEPTED', 'COLLATERAL_VALUATION', **{**reviewed_fields, 'reviewer_id': officer_id})],
           [doc(1, 'ACCEPTED', 'COLLATERAL_VALUATION', **{**reviewed_fields, 'reviewer_id': officer_id}, verified_value_rub=0)],
           [doc(1, 'UPLOADED', 'COLLATERAL_VALUATION', verified_value_rub=5)],
           [doc(1, 'ACCEPTED')],  # a review without reviewer, reason and time
           [doc(1, 'PENDING')], [doc(1, document_type='PASSPORT')], [doc(1, size_bytes=0)],
           [doc(1), doc(1, 'SUPERSEDED')]]  # a repeated revision number
    for documents in bad:
        with client.app.state.test_factory() as db:
            db.add_all(documents)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()


# --- PostgreSQL races ------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='concurrent commands need PostgreSQL row locks')
def test_approval_racing_the_owners_cancellation_leaves_one_outcome(client, officer):
    from test_documents import race
    application, documents = in_review(client, officer)
    application = accept_all(officer, application, documents)
    outcome = race(client, application, [
        (officer.cookies, lambda worker: approve(worker, application, STRONG_PREAPPROVED)),
        (client.cookies, lambda worker: worker.post(f"/api/v1/applications/{application['id']}/cancel",
                                                    json={'version': application['version'], 'reason': 'Передумал'},
                                                    headers={'Idempotency-Key': 'cancel-race'}))])
    assert sorted(response.status_code for response in outcome) == [200, 409]
    final = read(client, application)['status']
    assert final in ('APPROVED', 'CANCELLED')
    assert [row.action for row in decisions(client, application)] == (['approve'] if final == 'APPROVED' else [])
    assert [row.to_status for row in history_rows(client, application)].count(final) == 1
