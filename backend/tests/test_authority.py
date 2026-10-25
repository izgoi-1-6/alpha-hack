"""The mock Госуслуги authority check over HTTP + DB: the verification endpoint, the onboarding gate that requires an
unexpired, unused verification of the same user and ИНН, direct-API bypass attempts, several owners of one ИНН, the
seeded verifications and the submission re-check.

Person names and roles come from the raw fixture file (recommendation_oracle.FIXTURES), never from the code under test.
"""
from datetime import timedelta
import itertools
import os
import threading
from uuid import uuid4
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.main import app
from application_helpers import FIXED_NOW, bki_calls, clock, complete, draft, history, read, rows, submit
from recommendation_oracle import FIXTURES
from test_identity_company import CONSENTS, ORIGIN, PASSWORD, add, client, create_company, register, verify

pytestmark = pytest.mark.usefixtures('clock')
FIELDS = {'verification_id', 'inn', 'person_name', 'role', 'verified_at', 'expires_at'}
ROLES = {'LLC': 'Генеральный директор', 'IP': 'Индивидуальный предприниматель'}
STRONG, MEDIUM = FIXTURES['strong']['inn'], FIXTURES['medium']['inn']


def iso(moment) -> str:
    return moment.isoformat().replace('+00:00', 'Z')


def verification_rows(client, **where):
    from app.models import AuthorityVerification
    with client.app.state.test_factory() as db:
        query = select(AuthorityVerification)
        for key, value in where.items():
            query = query.where(getattr(AuthorityVerification, key) == value)
        return db.scalars(query).all()


def companies_of(client, user_id):
    from app.models import Company
    with client.app.state.test_factory() as db:
        return db.scalars(select(Company).where(Company.owner_user_id == user_id)).all()


def persisted(client) -> dict:
    """Row counts of what onboarding writes, and when each verification was used."""
    from app.models import Company, Consent, Precheck
    with client.app.state.test_factory() as db:
        counts = {model.__name__: len(db.scalars(select(model)).all()) for model in (Company, Consent, Precheck)}
    return {**counts, 'used': {row.id: row.used_at for row in verification_rows(client)}}


def me(client) -> str:
    return client.get('/api/v1/auth/me').json()['user']['id']


def refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code, response.text
    return response.json()['error']


# --- the verification endpoint ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('fixture_id', list(FIXTURES))
def test_the_check_always_confirms_the_fixture_director_for_the_session_user(client, fixture_id):
    register(client)
    fixture = FIXTURES[fixture_id]
    response = verify(client, fixture['inn'])
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == FIELDS
    assert (body['inn'], body['person_name'], body['role']) == (fixture['inn'], fixture['director_name'], ROLES[fixture['entity_type']])
    assert (body['verified_at'], body['expires_at']) == (iso(FIXED_NOW), iso(FIXED_NOW + timedelta(minutes=30)))
    (row,) = verification_rows(client)
    assert (row.id, row.user_id, row.inn, row.person_name, row.role) == (body['verification_id'], me(client), fixture['inn'],
                                                                         fixture['director_name'], ROLES[fixture['entity_type']])
    assert (row.method, row.used_at) == ('gosuslugi_mock', None)
    assert companies_of(client, me(client)) == []  # the check adds nothing by itself


def test_the_check_is_idempotent_per_key_and_body(client):
    register(client)
    first, again = verify(client, STRONG, key='verify-once'), verify(client, STRONG, key='verify-once')
    assert first.status_code == again.status_code == 201 and again.json() == first.json()
    assert len(verification_rows(client)) == 1
    refused(verify(client, MEDIUM, key='verify-once'), 409, 'IDEMPOTENCY_CONFLICT')
    second = verify(client, STRONG, key='verify-twice')
    assert second.status_code == 201 and second.json()['verification_id'] != first.json()['verification_id']
    assert len(verification_rows(client)) == 2


@pytest.mark.parametrize('inn', ['9900000018', '0000000000', '123', 9900000017, '９９００００００１７'])
def test_the_check_validates_the_inn(client, inn):
    register(client)
    error = refused(verify(client, inn), 422, 'VALIDATION_ERROR')
    assert set(error['fields']) == {'inn'}
    assert verification_rows(client) == []


def test_an_inn_outside_the_registry_is_not_confirmed(client):
    register(client)
    error = refused(verify(client, '7707083893'), 422, 'REGISTRY_NOT_FOUND')
    assert error['fields'] == {'inn': error['fields']['inn']} and error['fields']['inn']
    assert verification_rows(client) == []


def test_the_check_needs_a_client_session_the_origin_a_key_and_a_strict_body(client):
    url = '/api/v1/identity/gosuslugi/verify'
    with TestClient(app, headers={'origin': ORIGIN}) as anonymous:
        refused(anonymous.post(url, json={'inn': STRONG}, headers={'Idempotency-Key': 'k'}), 401, 'AUTH_REQUIRED')
    register(client)
    refused(client.post(url, json={'inn': STRONG}, headers={'Idempotency-Key': 'k', 'origin': 'http://evil.test'}), 403, 'ORIGIN_FORBIDDEN')
    assert client.post(url, json={'inn': STRONG}).status_code == 422  # Idempotency-Key is required
    for injected in ({'person_name': 'Иванов Иван Иванович'}, {'role': 'Генеральный директор'}, {'user_id': str(uuid4())},
                     {'verified': True}, {'expires_at': '2099-01-01T00:00:00Z'}):
        refused(client.post(url, json={'inn': STRONG, **injected}, headers={'Idempotency-Key': uuid4().hex}), 422, 'VALIDATION_ERROR')
    assert verification_rows(client) == []
    from officer_helpers import seed_demo_actors
    seed_demo_actors(client)
    client.post('/api/v1/auth/logout', json={})
    assert client.post('/api/v1/auth/login', json={'email': 'officer@demo.local', 'password': PASSWORD}).status_code == 200
    refused(verify(client, STRONG), 403, 'CLIENT_REQUIRED')
    assert verification_rows(client, method='gosuslugi_mock') == []


# --- the onboarding gate ---------------------------------------------------------------------------------------------

def test_a_company_is_added_with_its_verification_which_it_keeps(client):
    from app.models import AuthorityVerification, Company
    register(client)
    verification = verify(client, STRONG).json()
    response = create_company(client, STRONG, verification['verification_id'])
    assert response.status_code == 201, response.text
    company = response.json()['company']
    assert company['authority_verification_id'] == verification['verification_id']
    with client.app.state.test_factory() as db:
        row = db.get(Company, company['id'])
        used = db.get(AuthorityVerification, verification['verification_id'])
        assert row.authority_verification_id == used.id and (used.user_id, used.inn) == (me(client), STRONG)
        assert used.used_at is not None and used.used_at.replace(tzinfo=None) == FIXED_NOW.replace(tzinfo=None)


def gate_case(client, clock, case: str) -> tuple[str, str | None]:
    """An ИНН to add and the verification id the request presents, for one way the gate must refuse."""
    if case == 'absent':
        return STRONG, None
    if case == 'unknown':
        return STRONG, str(uuid4())
    if case == 'another user':
        register(client, 'owner@example.test')
        foreign = verify(client, STRONG).json()['verification_id']
        client.post('/api/v1/auth/logout', json={})
        register(client)
        return STRONG, foreign
    register(client)
    if case == 'another inn':
        return STRONG, verify(client, MEDIUM).json()['verification_id']
    if case == 'used':
        verification = verify(client, MEDIUM).json()['verification_id']
        assert create_company(client, MEDIUM, verification).status_code == 201
        return MEDIUM, verification  # the company exists: the gate refuses before COMPANY_EXISTS
    assert case == 'expired'
    verification = verify(client, STRONG).json()['verification_id']
    clock.now = FIXED_NOW + timedelta(minutes=30)  # valid strictly before verified_at + 30 minutes
    return STRONG, verification


@pytest.mark.parametrize('case', ['absent', 'unknown', 'another user', 'another inn', 'used', 'expired'])
def test_the_gate_refuses_a_missing_foreign_mismatched_used_or_expired_verification(client, clock, case):
    if case in ('absent', 'unknown'):
        register(client)
    inn, verification = gate_case(client, clock, case)
    before = persisted(client)
    error = refused(create_company(client, inn, verification), 403, 'AUTHORITY_NOT_VERIFIED')
    assert error['message']
    assert persisted(client) == before  # no company, precheck or consent written, no verification consumed


def test_the_gate_accepts_a_verification_until_its_thirtieth_minute(client, clock):
    register(client)
    verification = verify(client, STRONG).json()['verification_id']
    clock.now = FIXED_NOW + timedelta(minutes=30) - timedelta(seconds=1)
    assert create_company(client, STRONG, verification).status_code == 201


def test_a_null_or_mistyped_verification_id_is_refused(client):
    register(client)
    verification = verify(client, STRONG).json()['verification_id']
    body = {'inn': STRONG, 'consents': CONSENTS}
    refused(client.post('/api/v1/companies', json={**body, 'authority_verification_id': None}), 403, 'AUTHORITY_NOT_VERIFIED')
    for wrong in (123, True, [verification], {'id': verification}, 'x' * 37):
        refused(client.post('/api/v1/companies', json={**body, 'authority_verification_id': wrong}), 422, 'VALIDATION_ERROR')
    assert [row.used_at for row in verification_rows(client)] == [None]
    assert create_company(client, STRONG, verification).status_code == 201


def test_an_inn_outside_the_registry_still_reads_registry_not_found_on_onboarding(client):
    register(client)
    refused(create_company(client, '7707083893', None), 422, 'REGISTRY_NOT_FOUND')


def test_an_existing_company_is_reported_without_spending_the_new_verification(client):
    register(client)
    assert add(client, STRONG).status_code == 201
    fresh = verify(client, STRONG).json()['verification_id']
    refused(create_company(client, STRONG, fresh), 409, 'COMPANY_EXISTS')
    (unused,) = verification_rows(client, id=fresh)
    assert unused.used_at is None


# --- bypass attempts -------------------------------------------------------------------------------------------------

def test_the_gate_cannot_be_bypassed_through_the_request_body(client):
    register(client)
    verification = verify(client, MEDIUM).json()['verification_id']  # a real verification, for another ИНН
    body = {'inn': STRONG, 'consents': CONSENTS}
    for injected in ({'authority_verified': True}, {'representative_name': 'Соколов Андрей Викторович'},
                     {'authority_verification': {'id': verification, 'inn': STRONG}}, {'owner_user_id': me(client)}):
        refused(client.post('/api/v1/companies', json={**body, **injected}), 422, 'VALIDATION_ERROR')
    refused(client.post('/api/v1/companies', json={**body, 'authority_verification_id': verification}), 403, 'AUTHORITY_NOT_VERIFIED')
    assert companies_of(client, me(client)) == []


def test_a_replayed_check_returns_the_spent_verification_which_stays_spent(client):
    register(client)
    first = verify(client, STRONG, key='verify-replay').json()
    assert create_company(client, STRONG, first['verification_id']).status_code == 201
    replay = verify(client, STRONG, key='verify-replay')
    assert replay.status_code == 201 and replay.json() == first
    refused(create_company(client, STRONG, replay.json()['verification_id']), 403, 'AUTHORITY_NOT_VERIFIED')


def test_a_seeded_verification_cannot_be_reused_by_another_user(client):
    from officer_helpers import seed_demo_actors
    from app.models import Company
    seed_demo_actors(client)
    with client.app.state.test_factory() as db:
        seeded = db.scalar(select(Company).where(Company.fixture_id == 'strong')).authority_verification_id
    assert seeded
    register(client)
    refused(create_company(client, STRONG, seeded), 403, 'AUTHORITY_NOT_VERIFIED')


def test_several_users_may_add_the_same_inn_each_with_their_own_verification(client):
    register(client, 'first@example.test')
    first = add(client, STRONG).json()['company']
    client.post('/api/v1/auth/logout', json={})
    register(client, 'second@example.test')
    second = add(client, STRONG).json()['company']
    assert first['id'] != second['id'] and first['inn'] == second['inn'] == STRONG
    assert first['authority_verification_id'] != second['authority_verification_id']
    people = {row.id: (row.user_id, row.person_name) for row in verification_rows(client, inn=STRONG)}
    assert people[first['authority_verification_id']][1] == people[second['authority_verification_id']][1] == FIXTURES['strong']['director_name']
    assert people[first['authority_verification_id']][0] == first['owner_user_id']
    assert people[second['authority_verification_id']][0] == second['owner_user_id']


# --- PostgreSQL race --------------------------------------------------------------------------------------------------

pg_only = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='concurrent commands need PostgreSQL row locks')


class Ticking:
    """A request clock one second later on every request, so each request's writes carry their own time."""
    def __init__(self, start):
        self.start, self.ticks, self.lock = start, itertools.count(1), threading.Lock()

    def __call__(self):
        with self.lock:
            return self.start + timedelta(seconds=next(self.ticks))


def race(client, verification_id: str, calls: int, send):
    """Runs `send` concurrently while the verification row is locked, so every request queues on that lock."""
    from app.models import AuthorityVerification
    outcome = [None] * calls

    def run(index):
        with TestClient(app, headers={'origin': ORIGIN}, cookies=client.cookies) as worker:
            outcome[index] = send(worker)

    with client.app.state.test_factory() as blocker:
        blocker.execute(select(AuthorityVerification).where(AuthorityVerification.id == verification_id).with_for_update())
        workers = [threading.Thread(target=run, args=(index,)) for index in range(calls)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=1)
        assert all(worker.is_alive() for worker in workers), 'every request must wait for the verification row lock'
        blocker.commit()
    for worker in workers:
        worker.join(timeout=30)
    assert not any(worker.is_alive() for worker in workers)
    return outcome


@pg_only
def test_two_concurrent_companies_with_one_verification_admit_exactly_one(client):
    """Single use under concurrency: the gate's row lock serializes the two requests, so the second sees the
    verification spent (403), not a unique-constraint conflict; one company keeps it, used once by its request."""
    from app.models import AuthorityVerification, Company
    from app.clock import utc_now
    register(client)
    verification = verify(client, STRONG).json()['verification_id']
    client.app.dependency_overrides[utc_now] = Ticking(FIXED_NOW)
    outcome = race(client, verification, 2, lambda worker: create_company(worker, STRONG, verification))
    assert sorted(response.status_code for response in outcome) == [201, 403], [response.text for response in outcome]
    refusal = next(response for response in outcome if response.status_code == 403)
    assert refusal.json()['error']['code'] == 'AUTHORITY_NOT_VERIFIED'
    winner = next(response for response in outcome if response.status_code == 201).json()['company']
    with client.app.state.test_factory() as db:
        (company,) = db.scalars(select(Company).where(Company.owner_user_id == me(client))).all()
        assert company.id == winner['id'] and company.authority_verification_id == verification
        row = db.get(AuthorityVerification, verification)
        assert row.used_at is not None and row.used_at == company.created_at  # set by the winning request only
        assert db.scalars(select(Company).where(Company.authority_verification_id == verification)).all() == [company]


# --- the seed --------------------------------------------------------------------------------------------------------

def test_the_seed_gives_every_seeded_company_its_verification(client):
    from app.models import AuthorityVerification, Company
    from officer_helpers import seed_demo_actors
    seed_demo_actors(client)
    seed_demo_actors(client)  # idempotent
    with client.app.state.test_factory() as db:
        seeded = db.scalars(select(Company)).all()
        assert len(seeded) == len(FIXTURES) == len(db.scalars(select(AuthorityVerification)).all())
        for company in seeded:
            fixture = FIXTURES[company.fixture_id]
            row = db.get(AuthorityVerification, company.authority_verification_id)
            assert (row.user_id, row.inn, row.person_name, row.role) == (fixture['owner_user_id'], fixture['inn'],
                                                                         fixture['director_name'], ROLES[fixture['entity_type']])
            assert row.method == 'seed' and row.used_at is not None


def test_a_seeded_company_prefills_its_representative_and_submits(client, bki_calls):
    from officer_helpers import seed_demo_actors
    from application_helpers import TERM, create, patch_answers, snapshot_for
    seed_demo_actors(client)
    assert client.post('/api/v1/auth/login', json={'email': 'client@demo.local', 'password': PASSWORD}).status_code == 200
    company = FIXTURES['strong']['id']
    application = create(client, company, TERM, snapshot_for(client, company, 1_000_000)).json()['application']
    assert (application['answers']['representative_name'], application['answers']['representative_authority_confirmed']) == \
           (FIXTURES['strong']['director_name'], True)
    application = patch_answers(client, application, stage=2, purpose='working_capital', term_months=12).json()['application']
    response = submit(client, complete(client, application))
    assert response.status_code == 200, response.text
    assert response.json()['application']['status'] == 'PREAPPROVED' and len(bki_calls) == 1


# --- the submission re-check -----------------------------------------------------------------------------------------

@pytest.mark.parametrize('tamper', ['unlinked', 'another user', 'another inn'])
def test_submission_re_checks_the_company_verification(client, bki_calls, tamper):
    from app.models import AuthorityVerification, Company
    application = complete(client, draft(client, 'strong'))
    with client.app.state.test_factory.begin() as db:
        company = db.get(Company, application['company_id'])
        if tamper == 'unlinked':  # a company added before the check existed
            company.authority_verification_id = None
        else:
            row = db.get(AuthorityVerification, company.authority_verification_id)
            if tamper == 'another user':
                row.user_id = register_stranger(client)
            else:
                row.inn = MEDIUM
    error = refused(submit(client, application), 403, 'AUTHORITY_NOT_VERIFIED')
    assert error['message']
    assert read(client, application) == application and bki_calls == []
    assert [item['to_status'] for item in history(client, application)] == ['DRAFT']
    assert rows(client, 'Evaluation', application_id=application['id']) == []
    from app.models import Consent
    with client.app.state.test_factory() as db:
        assert db.scalars(select(Consent).where(Consent.application_id == application['id'])).all() == []


def register_stranger(client) -> str:
    """Another client account, created directly (the test keeps the owner's session)."""
    from app.identity import password_hasher
    from app.models import User
    with client.app.state.test_factory.begin() as db:
        user = User(email=f'stranger-{uuid4().hex}@example.test', password_hash=password_hasher.hash(PASSWORD),
                    display_name='Посторонний', role='CLIENT', created_at=FIXED_NOW)
        db.add(user)
        db.flush()
        return user.id
