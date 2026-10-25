"""Application lifecycle over HTTP + DB: creation from saved snapshots, the six saved stages, guarded commands,
ownership, idempotency, versions, the one-active-application guard, lazy expiry and history with simulated
notifications.

Expected values come from the spec, the acceptance document and the frozen fixtures, never from the code under test.
Scoring outcomes are covered in test_applications_scoring.py.
"""
from datetime import datetime, timezone
import json
import os
import threading
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.main import app
from app.models import Company, Consent
from application_helpers import (ANSWER_FIELDS, CONSENTS, LINE, SECURED, STAGE_FIELDS, TERM, bki_calls, cancel,
                                 clock, complete, create, draft, history, need_of, onboard, patch_answers, read, relogin,
                                 retry, rows, snapshot_for, submit, submitted)
from recommendation_oracle import FIXTURES, PRODUCTS
from test_identity_company import ORIGIN, PASSWORD, add, client, register
import catalog_oracle

pytestmark = pytest.mark.usefixtures('clock')
MISSING_IN_NEW_DRAFT = ['company_confirmed', 'actual_address', 'actual_activity', 'tax_regime', 'employees',
                        'monthly_debt_payment_rub', 'tax_debt_rub', 'legal_proceedings', 'representative_name',
                        'representative_authority_confirmed', 'beneficial_owners_confirmed', 'accuracy_confirmed']
PUBLIC_EVALUATION = {'id', 'rule', 'outcome', 'score', 'risk', 'scored_limit_rub', 'reasons', 'created_at'}


def url(application, suffix=''):
    return f"/api/v1/applications/{application['id']}{suffix}"


def seed_and_login_officer(client):
    from app.seed import seed_demo
    with client.app.state.test_factory.begin() as db:
        seed_demo(db, demo_mode=True)
    client.post('/api/v1/auth/logout', json={})
    assert client.post('/api/v1/auth/login', json={'email': 'officer@demo.local', 'password': PASSWORD}).status_code == 200


def test_draft_is_created_from_an_owned_snapshot_with_server_prefill(client, bki_calls):
    company = onboard(client, 'strong')
    snapshot = snapshot_for(client, company, 2_000_000)
    response = create(client, company, TERM, snapshot)
    assert response.status_code == 201, response.text
    application = response.json()['application']
    assert (application['status'], application['version'], application['current_stage']) == ('DRAFT', 1, 1)
    assert (application['company_id'], application['product_id'], application['recommendation_snapshot_id']) == (company, TERM, snapshot)
    catalog = client.get('/api/v1/catalog').json()
    assert (application['catalog_version'], application['rules_version']) == (catalog['catalog_version'], catalog['rules_version'])
    answers = application['answers']
    assert set(answers) == ANSWER_FIELDS
    # Stage 2 starts from the saved need, which is the amount alone: purpose, term and collateral are the client's.
    assert answers['requested_amount_rub'] == 2_000_000
    assert all(answers[key] is None for key in ('purpose', 'term_months', 'collateral')) and 'funding_pattern' not in answers
    # Stage 3 comes from the persisted turnover source; the debt payment is a client declaration, never prefilled.
    assert (answers['monthly_revenue_rub'], answers['previous_monthly_revenue_rub'], answers['financial_period_end']) == (800_000, 680_000, '2026-09-30')
    assert answers['monthly_debt_payment_rub'] is None and answers['tax_debt_rub'] is None
    assert all(answers[key] is None for key in MISSING_IN_NEW_DRAFT)
    assert application['requested_amount_rub'] == 2_000_000 and application['indicative_limit_rub'] == 2_400_000
    for key in ('scored_limit_rub', 'preapproved_amount_rub', 'final_amount_rub', 'submitted_at', 'preapproved_at', 'preapproval_expires_at'):
        assert application[key] is None, key
    assert application['allowed_actions'] == ['edit_answers', 'submit', 'cancel']
    assert application['missing_fields'] == MISSING_IN_NEW_DRAFT[:3] + ['purpose', 'term_months'] + MISSING_IN_NEW_DRAFT[3:]
    assert application['latest_evaluation'] is None and application['open_info_request'] is None
    assert application['document_summary'] is None
    product = application['product']
    assert (product['id'], product['amount_min_rub'], product['amount_max_rub'], product['term_min_months'], product['term_max_months']) == \
           (TERM, 300_000, 30_000_000, 12, 60)  # the catalog's terms
    assert (product['collateral_mode'], product['required_documents']) == ('none', ['BANK_STATEMENT', 'FINANCIAL_REPORT'])
    assert (product['secured'], product['payment_model']) == (False, 'annuity')
    assert application['company']['id'] == company and application['company']['inn'] == FIXTURES['strong']['inn']
    assert application['created_at'].endswith('Z')
    # Staff-only fields stay out of the customer view.
    assert not {'assignee_id', 'submitted_input_snapshot', 'factors', 'sources'} & set(application)
    assert bki_calls == []
    items = history(client, application)
    assert [(item['from_status'], item['to_status']) for item in items] == [(None, 'DRAFT')]
    assert items[0]['application_version'] == 1 and items[0]['reason_code'] == 'CREATED'
    assert items[0]['notification']['channel'] == 'demo_in_app' and items[0]['notification']['message']


@pytest.mark.parametrize('product_id', catalog_oracle.OVERLAY_IDS + ['unknown_product'])
def test_overlays_and_unknown_products_cannot_create_applications(client, product_id):
    company = onboard(client, 'strong')
    snapshot = snapshot_for(client, company)
    response = create(client, company, product_id, snapshot)
    assert response.status_code == 422 and response.json()['error']['code'] == 'PRODUCT_NOT_SUPPORTED'
    assert client.get('/api/v1/applications').json() == {'items': [], 'total': 0}


def test_creation_requires_an_owned_company_and_its_own_snapshot(client):
    company = onboard(client, 'strong')
    other_company = add(client, FIXTURES['medium']['inn']).json()['company']['id']
    snapshot = snapshot_for(client, company)
    foreign_snapshot = snapshot_for(client, other_company)
    for snapshot_id in (foreign_snapshot, str(uuid4())):  # another owned company's snapshot, an absent one
        response = create(client, company, TERM, snapshot_id)
        assert response.status_code == 404 and response.json()['error']['code'] == 'RECOMMENDATION_NOT_FOUND'
    body = {'company_id': company, 'product_id': TERM, 'recommendation_snapshot_id': snapshot}
    assert client.post('/api/v1/applications', json=body).status_code == 422  # Idempotency-Key is required
    for injected in ({'status': 'PREAPPROVED'}, {'answers': {}}, {'version': 3}, {'owner_user_id': str(uuid4())}):
        response = client.post('/api/v1/applications', json={**body, **injected}, headers={'Idempotency-Key': uuid4().hex})
        assert response.status_code == 422, injected
    assert client.post('/api/v1/applications', json=body, headers={'Idempotency-Key': 'x', 'origin': 'http://evil.test'}).status_code == 403
    assert client.get('/api/v1/applications').json()['total'] == 0
    client.post('/api/v1/auth/logout', json={})
    register(client, 'other@example.test')
    response = create(client, company, TERM, snapshot)
    assert response.status_code == 404 and response.json()['error']['code'] == 'COMPANY_NOT_FOUND'
    seed_and_login_officer(client)
    assert create(client, company, TERM, snapshot).status_code == 403


def test_creation_is_idempotent_per_key_and_body(client):
    company = onboard(client, 'strong')
    snapshot = snapshot_for(client, company)
    first = create(client, company, TERM, snapshot, key='create-once')
    again = create(client, company, TERM, snapshot, key='create-once')
    assert first.status_code == again.status_code == 201 and again.json() == first.json()
    assert client.get('/api/v1/applications').json()['total'] == 1
    conflict = create(client, company, LINE, snapshot, key='create-once')
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    second = create(client, company, TERM, snapshot, key='create-twice')  # several drafts per company/product are allowed
    assert second.status_code == 201 and second.json()['application']['id'] != first.json()['application']['id']
    assert client.get('/api/v1/applications').json()['total'] == 2


def edited_config(tmp_path, which: str):
    """The shipped configuration with one file edited and its version left as it is: only the content hash changes."""
    from app.products_config import load_config
    catalog = json.loads(catalog_oracle.CATALOG_PATH.read_text(encoding='utf-8'))
    policy = json.loads(catalog_oracle.POLICY_PATH.read_text(encoding='utf-8'))
    if which == 'catalog':
        catalog['items'][0]['display']['features'][0] += '.'
    else:
        policy['products']['psk_borderline']['priority'] += 1
    paths = tmp_path / 'catalog.json', tmp_path / 'policy.json'
    for path, data in zip(paths, (catalog, policy)):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return load_config(*paths)


@pytest.mark.parametrize('which', ['catalog', 'policy'])
def test_an_edited_catalog_or_policy_makes_the_snapshot_and_the_draft_stale(client, bki_calls, monkeypatch, tmp_path, which):
    from app.recommendations import catalog
    company = onboard(client, 'strong')
    snapshot = snapshot_for(client, company)
    application = complete(client, draft(client, 'strong', company=company))
    edited = edited_config(tmp_path, which)
    versions = (catalog.CONFIG.catalog_version, catalog.CONFIG.rules_version), (edited.catalog_version, edited.rules_version)
    assert [version.split('+')[0] for version in versions[0]] == [version.split('+')[0] for version in versions[1]]
    assert versions[0] != versions[1]  # no version bump, yet a new content hash
    monkeypatch.setattr(catalog, 'CONFIG', edited)
    response = create(client, company, TERM, snapshot)
    assert response.status_code == 409 and response.json()['error']['code'] == 'RECOMMENDATION_STALE'
    response = submit(client, application)
    assert response.status_code == 409 and response.json()['error']['code'] == 'RECOMMENDATION_STALE'
    assert read(client, application)['status'] == 'DRAFT' and bki_calls == []


def test_dialog_declares_the_six_saved_stages(client):
    application = draft(client, 'strong')
    response = client.get(url(application, '/dialog'))
    assert response.status_code == 200, response.text
    dialog = response.json()
    assert dialog['steps_total'] == 6 and dialog['current_stage'] == 1
    stages = dialog['stages']
    assert [stage['number'] for stage in stages] == [1, 2, 3, 4, 5, 6]
    assert [stage['title'] for stage in stages] == ['Компания', 'Параметры', 'Бизнес и финансы', 'Обязательства',
                                                     'Руководитель и владельцы', 'Проверка и согласия']
    # The term loan takes no collateral, so its stage 2 hides the pledge (the answer key stays, empty).
    assert [[field['name'] for field in stage['fields']] for stage in stages] == \
           [[name for name in stage if name != 'collateral'] for stage in STAGE_FIELDS]
    assert [stage['complete'] for stage in stages] == [False, True, False, False, False, False]
    assert dialog['answers'] == application['answers'] and dialog['missing_fields'] == MISSING_IN_NEW_DRAFT
    assert all(field['label'] and field['type'] and isinstance(field['required'], bool) for stage in stages for field in stage['fields'])
    parameters = {field['name']: field for field in stages[1]['fields']}
    assert (parameters['requested_amount_rub']['min'], parameters['requested_amount_rub']['max']) == (300_000, 30_000_000)
    assert (parameters['term_months']['min'], parameters['term_months']['max']) == (12, 60)
    assert [option['value'] for option in parameters['purpose']['options']] == PRODUCTS[TERM]['purposes']
    assert 'collateral' not in parameters and 'funding_pattern' not in parameters
    finance = {field['name']: field for field in stages[2]['fields']}
    assert finance['monthly_revenue_rub']['source'] == {'name': 'turnover', 'status': 'available', 'value': 800_000}
    assert finance['monthly_revenue_rub']['origin'] == 'source'
    assert [option['value'] for option in finance['tax_regime']['options']] == ['OSN', 'USN', 'PSN', 'OTHER']
    assert finance['seasonal']['required'] is False
    obligations = {field['name']: field for field in stages[3]['fields']}
    assert obligations['monthly_debt_payment_rub']['min'] == 0 and 'source' not in obligations['monthly_debt_payment_rub']
    assert {field['name']: field['required'] for field in stages[5]['fields']} == {'accuracy_confirmed': True}


def test_secured_dialog_requires_a_declared_collateral(client):
    application = draft(client, 'strong', product=SECURED, collateral=None)  # the need states no collateral
    dialog = client.get(url(application, '/dialog')).json()
    parameters = {field['name']: field for field in dialog['stages'][1]['fields']}
    assert parameters['collateral']['required'] is True and dialog['stages'][1]['complete'] is False
    assert 'collateral' in dialog['missing_fields']
    assert application['indicative_limit_rub'] is None


def test_answers_are_saved_revised_and_survive_reload(client):
    application = draft(client, 'strong')
    response = patch_answers(client, application, stage=2, company_confirmed=True, actual_address='  Демо-адрес, офис 2  ',
                             actual_activity='Оптовая торговля')
    assert response.status_code == 200, response.text
    saved = response.json()['application']
    assert saved['version'] == application['version'] + 1 and saved['current_stage'] == 2 and saved['status'] == 'DRAFT'
    assert saved['answers']['actual_address'] == 'Демо-адрес, офис 2' and saved['answers']['company_confirmed'] is True
    revised = patch_answers(client, saved, stage=2, requested_amount_rub=1_500_000, term_months=24).json()['application']
    assert revised['version'] == saved['version'] + 1 and revised['requested_amount_rub'] == 1_500_000
    assert revised['answers']['term_months'] == 24 and revised['answers']['actual_activity'] == 'Оптовая торговля'
    cleared = patch_answers(client, revised, stage=3, actual_activity=None).json()['application']
    assert cleared['answers']['actual_activity'] is None and 'actual_activity' in cleared['missing_fields']
    with TestClient(app, headers={'origin': ORIGIN}, cookies=client.cookies) as reloaded:
        assert reloaded.get(url(application)).json()['application']['answers'] == cleared['answers']
        assert reloaded.get(url(application, '/dialog')).json()['current_stage'] == 3
    assert len(history(client, application)) == 1  # same-state edits do not invent status transitions


def test_collateral_answers_are_deep_merged(client):
    application = draft(client, 'strong', product=SECURED, collateral=None)
    application = patch_answers(client, application, stage=2, collateral={'status': 'declared', 'type': 'equipment'}).json()['application']
    assert {'collateral.declared_value_rub', 'collateral.description'} <= set(application['missing_fields'])
    application = patch_answers(client, application, collateral={'declared_value_rub': 4_000_000, 'description': 'Станок'}).json()['application']
    application = patch_answers(client, application, collateral={'owner_confirmed': True, 'encumbered': False}).json()['application']
    assert application['answers']['collateral'] == {'status': 'declared', 'type': 'equipment', 'declared_value_rub': 4_000_000,
                                                    'description': 'Станок', 'owner_confirmed': True, 'encumbered': False}
    assert not any(path.startswith('collateral') for path in application['missing_fields'])
    cleared = patch_answers(client, application, collateral=None).json()['application']
    assert cleared['answers']['collateral'] is None and 'collateral' in cleared['missing_fields']


@pytest.mark.parametrize('body', [
    {'status': 'PREAPPROVED'}, {'product_id': LINE}, {'company_id': str(uuid4())}, {'recommendation_snapshot_id': str(uuid4())},
    {'scored_limit_rub': 3_000_000}, {'assignee_id': str(uuid4())}, {'current_stage': 0}, {'current_stage': 7},
    {'current_stage': '2'}, {'version': True},
    {'answers': {'credit_history': 'clean'}}, {'answers': {'current_overdue_days': 0}}, {'answers': {'score': 100}},
    {'answers': {'status': 'APPROVED'}}, {'answers': {'product_id': LINE}},
    {'answers': {'monthly_debt_payment_rub': -1}}, {'answers': {'tax_debt_rub': -5}}, {'answers': {'monthly_revenue_rub': -1}},
    {'answers': {'employees': -1}}, {'answers': {'requested_amount_rub': 0}}, {'answers': {'requested_amount_rub': '1000000'}},
    {'answers': {'requested_amount_rub': 1.5}}, {'answers': {'requested_amount_rub': 2_000_000_001}},
    {'answers': {'term_months': 121}}, {'answers': {'term_months': 0}}, {'answers': {'tax_regime': 'FLAT'}},
    {'answers': {'funding_pattern': 'one_time'}},
    {'answers': {'company_confirmed': 1}}, {'answers': {'actual_address': 'я' * 301}}, {'answers': {'representative_name': 'я' * 101}},
    {'answers': {'financial_period_end': 'not-a-date'}}, {'answers': {'purpose': 'consumer'}},
    {'answers': {'collateral': {'status': 'pledged'}}}, {'answers': {'collateral': {'declared_value_rub': 0}}},
    {'answers': {'collateral': {'guarantor_consent': True}}},
])
def test_answers_reject_unknown_server_owned_and_invalid_values(client, body):
    application = draft(client, 'strong')
    payload = {'version': 1, 'current_stage': 1, 'answers': {}, **body}
    response = client.patch(url(application, '/answers'), json=payload)
    assert response.status_code == 422, response.text
    assert read(client, application) == application


def test_answers_need_the_current_version_and_a_draft(client):
    application = draft(client, 'strong')
    assert patch_answers(client, application, actual_address='Адрес').status_code == 200
    stale = patch_answers(client, application, actual_address='Другой адрес')  # still version 1
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'
    preapproved = submitted(client, 'strong', company=application['company_id'])
    response = patch_answers(client, preapproved, actual_address='Новый адрес')
    assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_STATUS'
    assert read(client, preapproved)['answers'] == preapproved['answers']


def test_every_application_route_is_owner_scoped_and_client_only(client):
    application = draft(client, 'strong')
    version = {'version': 1}
    commands = [('submit', {**version, 'consents': CONSENTS}), ('retry-check', version), ('cancel', {**version, 'reason': 'Чужая'})]
    client.post('/api/v1/auth/logout', json={})
    register(client, 'other@example.test')
    assert client.get('/api/v1/applications').json() == {'items': [], 'total': 0}
    assert client.get('/api/v1/applications', params={'company_id': application['company_id']}).json()['total'] == 0
    for suffix in ('', '/dialog', '/history'):
        response = client.get(url(application, suffix))
        assert response.status_code == 404 and response.json()['error']['code'] == 'APPLICATION_NOT_FOUND', suffix
    response = client.patch(url(application, '/answers'), json={'version': 1, 'current_stage': 1, 'answers': {}})
    assert response.status_code == 404
    for name, body in commands:
        response = client.post(url(application, f'/{name}'), json=body, headers={'Idempotency-Key': uuid4().hex})
        assert response.status_code == 404 and response.json()['error']['code'] == 'APPLICATION_NOT_FOUND', name
    seed_and_login_officer(client)
    assert client.get('/api/v1/applications').status_code == 403
    for suffix in ('', '/dialog', '/history'):
        assert client.get(url(application, suffix)).status_code == 403
    assert client.patch(url(application, '/answers'), json={'version': 1, 'current_stage': 1, 'answers': {}}).status_code == 403
    for name, body in commands:
        assert client.post(url(application, f'/{name}'), json=body, headers={'Idempotency-Key': uuid4().hex}).status_code == 403
    client.post('/api/v1/auth/logout', json={})
    relogin(client)
    assert read(client, application) == application  # nothing changed


def test_owner_can_cancel_a_draft_and_cancellation_is_terminal(client, bki_calls):
    application = draft(client, 'strong')
    blank = cancel(client, application, reason='   ')
    assert blank.status_code == 422
    response = cancel(client, application, reason='  Потребность отпала  ', key='cancel-1')
    assert response.status_code == 200, response.text
    cancelled = response.json()['application']
    assert cancelled['status'] == 'CANCELLED' and cancelled['version'] == application['version'] + 1 and cancelled['allowed_actions'] == []
    assert cancel(client, application, reason='  Потребность отпала  ', key='cancel-1').json() == response.json()
    again = cancel(client, cancelled, key='cancel-2')
    assert again.status_code == 409 and again.json()['error']['code'] == 'INVALID_STATUS'
    assert submit(client, cancelled).status_code == 409 and retry(client, cancelled).status_code == 409
    items = history(client, application)
    assert [(item['from_status'], item['to_status']) for item in items] == [(None, 'DRAFT'), ('DRAFT', 'CANCELLED')]
    me = client.get('/api/v1/auth/me').json()['user']['id']
    assert items[1]['actor_role'] == 'client' and items[1]['reason_text'] == 'Потребность отпала'
    assert items[1]['application_version'] == cancelled['version']
    assert [row.actor_id for row in rows(client, 'StatusHistory', application_id=application['id'], to_status='CANCELLED')] == [me]
    assert bki_calls == []


@pytest.mark.parametrize('fixture_id,status', [('bki_unavailable', 'WAIT_EXTERNAL'), ('bki_missing', 'NEED_INFO'),
                                               ('medium', 'MANUAL_REVIEW'), ('strong', 'PREAPPROVED')])
def test_owner_can_cancel_a_submitted_active_application(client, fixture_id, status):
    application = submitted(client, fixture_id)
    assert application['status'] == status and 'cancel' in application['allowed_actions']
    response = cancel(client, application)
    assert response.status_code == 200 and response.json()['application']['status'] == 'CANCELLED'
    assert history(client, application)[-1]['from_status'] == status


def test_rejected_applications_cannot_be_cancelled(client):
    application = submitted(client, 'high_risk')
    assert application['status'] == 'REJECTED' and application['allowed_actions'] == []
    response = cancel(client, application)
    assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_STATUS'


def test_history_records_each_transition_with_its_simulated_notification(client):
    application = submitted(client, 'strong')
    items = history(client, application)
    assert [(item['from_status'], item['to_status']) for item in items] == [(None, 'DRAFT'), ('DRAFT', 'CHECKING'), ('CHECKING', 'PREAPPROVED')]
    version = application['version']
    assert [item['application_version'] for item in items] == [1, version, version]  # one increment per command
    me = client.get('/api/v1/auth/me').json()['user']['id']
    assert [item['actor_role'] for item in items] == ['client', 'client', 'system']  # the check result is a system step
    assert all('actor_id' not in item for item in items)  # the customer timeline names roles, never user ids
    saved_rows = sorted(rows(client, 'StatusHistory', application_id=application['id']), key=lambda row: row.sequence)
    assert [row.actor_id for row in saved_rows] == [me, me, None]
    assert [item['reason_code'] for item in items] == ['CREATED', 'SUBMITTED', 'R8']
    assert all(item['created_at'].endswith('Z') and item['reason_text'] for item in items)
    assert all(item['notification']['channel'] == 'demo_in_app' and item['notification']['message'] for item in items)
    assert '2 000 000' in items[2]['notification']['message'] and '07.11.2026' in items[2]['notification']['message']
    saved = rows(client, 'Notification', application_id=application['id'])
    assert len(saved) == 3 and {row.channel for row in saved} == {'demo_in_app'}


def test_my_applications_lists_owned_items_with_filters(client):
    company = onboard(client, 'strong')
    first = draft(client, 'strong', company=company)
    second = submitted(client, 'strong', product=LINE, company=company)
    listing = client.get('/api/v1/applications').json()
    assert listing['total'] == 2 and {item['id'] for item in listing['items']} == {first['id'], second['id']}
    assert [item['id'] for item in client.get('/api/v1/applications', params={'status': 'DRAFT'}).json()['items']] == [first['id']]
    assert [item['id'] for item in client.get('/api/v1/applications', params={'status': second['status']}).json()['items']] == [second['id']]
    assert client.get('/api/v1/applications', params={'company_id': company}).json()['total'] == 2
    assert client.get('/api/v1/applications', params={'company_id': str(uuid4())}).json()['total'] == 0
    assert client.get('/api/v1/applications', params={'status': 'OFFERED'}).status_code == 422


def test_second_active_submission_conflicts_with_the_existing_application(client, bki_calls):
    company = onboard(client, 'strong')
    first = submitted(client, 'strong', company=company)
    second = complete(client, draft(client, 'strong', company=company))
    response = submit(client, second)
    assert response.status_code == 409 and response.json()['error']['code'] == 'DUPLICATE_ACTIVE_APPLICATION'
    assert response.json()['error']['details']['application_id'] == first['id']
    assert read(client, second) == second and len(bki_calls) == 1
    with client.app.state.test_factory() as db:
        assert db.scalars(select(Consent).where(Consent.application_id == second['id'])).all() == []
    other_product = submitted(client, 'strong', product=LINE, company=company)  # the guard is per company and product
    assert other_product['status'] == 'PREAPPROVED'
    assert cancel(client, first).status_code == 200  # a terminal application permits a new submission
    response = submit(client, second)
    assert response.status_code == 200 and response.json()['application']['status'] == 'PREAPPROVED'


def test_the_database_admits_one_active_application_per_company_and_product(client):
    from app.applications.models import Application
    application = draft(client, 'strong')
    with client.app.state.test_factory() as db:
        original = db.get(Application, application['id'])
        values = {column.name: getattr(original, column.name) for column in Application.__table__.columns if column.name != 'id'}
        db.add(Application(**{**values, 'status': 'DRAFT'}))
        db.add(Application(**{**values, 'status': 'CANCELLED'}))
        db.add(Application(**{**values, 'status': 'MANUAL_REVIEW'}))
        db.flush()  # many drafts and terminal rows are fine next to one active row
        db.add(Application(**{**values, 'status': 'PREAPPROVED'}))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='concurrent submissions need PostgreSQL row locks')
def test_concurrent_submissions_for_one_company_product_admit_exactly_one(client, bki_calls):
    company = onboard(client, 'strong')
    drafts = [complete(client, draft(client, 'strong', company=company)) for _ in range(2)]
    outcome = {}

    def run(application, key):
        with TestClient(app, headers={'origin': ORIGIN}, cookies=client.cookies) as worker:
            outcome[application['id']] = submit(worker, application, key=key)

    with client.app.state.test_factory() as blocker:
        # Both submissions must serialize on the company row: hold it until both requests are waiting.
        blocker.execute(select(Company).where(Company.id == company).with_for_update())
        workers = [threading.Thread(target=run, args=(application, f'race-{n}')) for n, application in enumerate(drafts)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=1)
        assert all(worker.is_alive() for worker in workers), 'both submissions must wait for the company lock'
        blocker.commit()
    for worker in workers:
        worker.join(timeout=30)
    assert not any(worker.is_alive() for worker in workers)
    assert sorted(response.status_code for response in outcome.values()) == [200, 409]
    winner = next(key for key, response in outcome.items() if response.status_code == 200)
    loser = next(response for response in outcome.values() if response.status_code == 409)
    assert loser.json()['error']['code'] == 'DUPLICATE_ACTIVE_APPLICATION'
    assert loser.json()['error']['details']['application_id'] == winner
    assert sorted(read(client, application)['status'] for application in drafts) == ['DRAFT', 'PREAPPROVED']
    assert len(bki_calls) == 1


def test_preapproval_expires_exactly_once_at_the_fourteen_day_deadline(client, clock):
    clock.now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    application = submitted(client, 'strong')
    assert application['status'] == 'PREAPPROVED'
    assert (application['preapproved_at'], application['preapproval_expires_at']) == ('2026-10-24T12:00:00Z', '2026-11-07T12:00:00Z')
    clock.now = datetime(2026, 11, 7, 11, 59, 59, tzinfo=timezone.utc)
    relogin(client)
    assert read(client, application)['status'] == 'PREAPPROVED'
    clock.now = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)
    expired = read(client, application)
    assert expired['status'] == 'EXPIRED' and expired['version'] == application['version'] + 1
    assert expired['allowed_actions'] == [] and expired['preapproved_amount_rub'] == 2_000_000
    assert client.get('/api/v1/applications').json()['items'][0]['status'] == 'EXPIRED'
    assert client.get(url(application, '/dialog')).status_code == 200
    items = history(client, application)
    assert [item['to_status'] for item in items].count('EXPIRED') == 1
    assert items[-1]['actor_role'] == 'system' and items[-1]['from_status'] == 'PREAPPROVED'
    assert items[-1]['application_version'] == expired['version']
    assert len([row for row in rows(client, 'Notification', application_id=application['id']) if 'expired' in row.event_code]) == 1
    response = cancel(client, expired)
    assert response.status_code == 409 and response.json()['error']['code'] == 'INVALID_STATUS'


def test_a_command_after_the_deadline_records_the_expiry_and_is_refused(client, clock):
    application = submitted(client, 'strong')
    clock.now = datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc)
    relogin(client)
    response = cancel(client, application)  # the first touch after the deadline is a command
    assert response.status_code == 409 and response.json()['error']['code'] == 'APPLICATION_EXPIRED'
    # The refused command itself persisted the expiry (read the rows directly: an API read would expire it again).
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.status == 'EXPIRED' and row.version == application['version'] + 1
    assert [entry.to_status for entry in rows(client, 'StatusHistory', application_id=application['id'])].count('EXPIRED') == 1
    assert read(client, application)['status'] == 'EXPIRED'
    assert [item['to_status'] for item in history(client, application)].count('EXPIRED') == 1


def test_lazy_expiry_runs_before_the_duplicate_active_check(client, clock):
    company = onboard(client, 'strong')
    first = submitted(client, 'strong', company=company)
    second = complete(client, draft(client, 'strong', company=company))
    assert submit(client, second).status_code == 409
    clock.now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    relogin(client)
    response = submit(client, second, version=read(client, second)['version'])
    assert response.status_code == 200 and response.json()['application']['status'] == 'PREAPPROVED'
    assert read(client, first)['status'] == 'EXPIRED'
