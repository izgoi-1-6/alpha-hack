"""HTTP contract tests: auth, source boundaries and persisted company lifecycle."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

ORIGIN = 'http://localhost:5173'
PASSWORD = 'DemoCredit2026!'
CONSENT_VERSION = 'demo-consent-v2'
CONSENTS = [{'code': c, 'version': CONSENT_VERSION, 'accepted': True}
            for c in ('ONBOARDING_PROCESSING', 'REGISTRY_LOOKUP')]

@pytest.fixture
def client():
    # Bootstrap test intentionally uses the same app before DB infrastructure exists.
    if hasattr(app.state, 'engine'):
        from app.db import Base, get_db
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        url = os.getenv('TEST_DATABASE_URL', 'sqlite://')
        opts = {'connect_args': {'check_same_thread': False}, 'poolclass': StaticPool} if url == 'sqlite://' else {}
        if url != 'sqlite://' and not url.rsplit('/',1)[-1].endswith('_test'):
            raise RuntimeError('TEST_DATABASE_URL must target a disposable database ending in _test')
        engine = create_engine(url, **opts)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        def db():
            with factory() as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
        app.dependency_overrides[get_db] = db
        app.state.test_factory = factory
    with TestClient(app, headers={'origin': ORIGIN}) as c:
        yield c
    app.dependency_overrides.clear()
    if hasattr(app.state, 'test_factory'):
        engine.dispose()

def register(c, email='new@example.test', **extra):
    return c.post('/api/v1/auth/register', json={'email': email, 'password': PASSWORD, 'display_name': 'Новый клиент', **extra})

def verify(c, inn='9900000017', *, key=None):
    """The mock Госуслуги authority check of the session user for the ИНН."""
    return c.post('/api/v1/identity/gosuslugi/verify', json={'inn': inn}, headers={'Idempotency-Key': key or uuid4().hex})

def create_company(c, inn, verification_id, consents=None):
    """POST /companies with the given verification id (None: the field is left out)."""
    body = {'inn': inn, 'consents': CONSENTS if consents is None else consents}
    if verification_id is not None:
        body['authority_verification_id'] = verification_id
    return c.post('/api/v1/companies', json=body)

def add(c, inn='9900000017', consents=None):
    """Onboarding as the UI does it: the Госуслуги check for the ИНН, then the company with that verification (a
    refused check leaves the field out, so the company request reports its own validation or registry error)."""
    verified = verify(c, inn)
    return create_company(c, inn, verified.json()['verification_id'] if verified.status_code == 201 else None, consents)

def test_registration_cookie_and_refresh_persistence(client):
    r = register(client, '  New@Example.test  ')
    assert r.status_code == 201
    assert r.json()['user']['email'] == 'new@example.test'
    assert r.json()['user']['role'] == 'CLIENT'
    assert set(r.json()['user']) == {'id','email','display_name','role'}
    cookie = r.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie
    assert client.get('/api/v1/auth/me').json() == r.json()
    company = add(client).json()
    assert client.get('/api/v1/companies').json()['total'] == 1
    assert client.get('/api/v1/companies/' + company['company']['id']).json() == company
    # A new connection/client sees the same server-owned state.
    with TestClient(app, headers={'origin': ORIGIN}, cookies=client.cookies) as refreshed:
        assert refreshed.get('/api/v1/auth/me').json() == r.json()
        assert refreshed.get('/api/v1/companies').json()['total'] == 1

@pytest.mark.parametrize('extra', [{'role':'CREDIT_OFFICER'}, {'owner_user_id':str(uuid4())}, {'status':'APPROVED'}])
def test_registration_rejects_privilege_injection(client, extra):
    assert register(client, **extra).status_code == 422
    assert client.get('/api/v1/auth/me').status_code == 401

def test_login_logout_and_duplicate_email(client):
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    token = client.cookies.get('credit_route_session')
    assert client.post('/api/v1/auth/logout', json={}).status_code == 204
    assert client.get('/api/v1/auth/me').status_code == 401
    assert client.post('/api/v1/auth/logout', json={}).status_code == 204
    client.cookies.set('credit_route_session', token)
    assert client.get('/api/v1/auth/me').status_code == 401
    client.cookies.clear()
    assert client.post('/api/v1/auth/login', json={'email':'new@example.test','password':'wrongwrongwrong'}).status_code == 401
    r = client.post('/api/v1/auth/login', json={'email':'NEW@example.test','password':PASSWORD})
    assert r.status_code == 200
    assert client.cookies.get('credit_route_session') != token

def test_password_and_email_validation(client):
    for payload in [dict(email='bad',password=PASSWORD,display_name='Name'), dict(email='a@b.test',password='short',display_name='Name'), dict(email='a@b.test',password=PASSWORD,display_name=' '),dict(email='a@b.test',password='x'*129,display_name='Name')]:
        assert client.post('/api/v1/auth/register', json=payload).status_code == 422

@pytest.mark.parametrize('origin', ['', 'http://evil.example', 'http://localhost:5173.evil.test'])
def test_mutations_reject_missing_or_foreign_origin(client, origin):
    r = client.post('/api/v1/auth/register', json={'email':'a@b.test','password':PASSWORD,'display_name':'Name'}, headers={'origin':origin})
    assert r.status_code == 403
    assert r.json()['error']['code'] == 'ORIGIN_FORBIDDEN'

@pytest.mark.parametrize('inn', ['9900000018', '0000000000', '111111111111', '９９００００００１７', 9900000017, '123', '990000000290'])
def test_rejects_invalid_inn(client, inn):
    register(client)
    r=add(client, inn)
    assert r.status_code == 422
    assert client.get('/api/v1/companies').json()['total'] == 0

@pytest.mark.parametrize('inn,entity', [('9900000017','LLC'), ('990000000299','IP')])
def test_valid_inn_entity_and_source_minimization(client, inn, entity):
    register(client)
    r=add(client,inn)
    assert r.status_code == 201
    data=r.json()
    assert data['company']['entity_type'] == entity
    assert data['precheck']['synthetic'] is True
    assert data['precheck']['source_version'] == 'demo-fixtures-v2'
    assert 'credit_history' not in str(data) and 'bki' not in str(data).lower()
    # The registry facts: the SME-register flag on the company row, tax regime and staff in the registry payload.
    assert data['company']['msp_registry'] is True and data['company']['region'] in ('Москва', 'Санкт-Петербург')
    assert {key: data['precheck']['registry_payload'][key] for key in ('msp_registry', 'tax_regime', 'employees')} == \
           ({'msp_registry': True, 'tax_regime': 'OSN', 'employees': 24} if entity == 'LLC' else
            {'msp_registry': True, 'tax_regime': 'USN', 'employees': 6})
    assert 'director_name' not in data['precheck']['registry_payload']
    assert data['company']['created_at'].endswith('Z')
    assert add(client,inn).status_code == 409

@pytest.mark.parametrize('consents', [[], CONSENTS[:1], [{'code':x['code'],'version':'old','accepted':True} for x in CONSENTS], [{'code':x['code'],'version':x['version'],'accepted':False} for x in CONSENTS]])
def test_requires_explicit_current_onboarding_consents(client, consents):
    register(client)
    assert add(client, consents=consents).status_code == 422
    assert client.get('/api/v1/companies').json()['total'] == 0

def test_unknown_valid_inn_does_not_persist(client):
    register(client)
    r=add(client,'7707083893')
    assert r.status_code == 422
    assert r.json()['error']['code'] == 'REGISTRY_NOT_FOUND'
    assert client.get('/api/v1/companies').json()['total'] == 0

def test_inactive_missing_and_unavailable_registry(client):
    register(client)
    inactive=add(client,'9900000049').json()
    assert inactive['company']['registry_status'] == 'inactive'
    missing=add(client,'990000000500').json()
    assert missing['precheck']['turnover_source_status'] == 'missing'
    assert missing['precheck']['monthly_revenue_rub'] is None
    unknown=add(client,'9900000063').json()
    assert unknown['company']['registry_status'] == 'unknown'
    cid=unknown['company']['id']
    assert client.get(f'/api/v1/companies/{cid}/precheck').json() == unknown
    r=client.post(f'/api/v1/companies/{cid}/precheck/retry', json={'version':1}, headers={'Idempotency-Key':'retry-one'})
    assert r.status_code == 200
    assert r.json()['company']['registry_status'] == 'active'
    assert r.json()['company']['version'] == 2
    assert r.json()['precheck']['id'] != unknown['precheck']['id']
    assert client.post(f'/api/v1/companies/{cid}/precheck/retry', json={'version':1}, headers={'Idempotency-Key':'retry-one'}).json() == r.json()
    assert client.post(f'/api/v1/companies/{cid}/precheck/retry', json={'version':2}, headers={'Idempotency-Key':'retry-one'}).status_code == 409
    assert client.post(f'/api/v1/companies/{cid}/precheck/retry', json={'version':1}, headers={'Idempotency-Key':'retry-two'}).status_code == 409
    assert client.post(f'/api/v1/companies/{cid}/precheck/retry', json={'version':2}).status_code == 422

def test_cross_user_company_is_not_disclosed(client):
    register(client)
    company=add(client).json()['company']
    client.post('/api/v1/auth/logout',json={})
    register(client,'other@example.test')
    assert client.get('/api/v1/companies').json()['total'] == 0
    for suffix in ['', '/precheck']:
        assert client.get('/api/v1/companies/'+company['id']+suffix).status_code == 404
    assert client.post('/api/v1/companies/'+company['id']+'/precheck/retry',json={'version':1},headers={'Idempotency-Key':'x'}).status_code == 404
    assert add(client).status_code == 201

def test_session_expires_after_twelve_hours(client):
    from app.clock import utc_now
    fixed=datetime(2030,1,1,tzinfo=timezone.utc)
    app.dependency_overrides[utc_now]=lambda: fixed
    register(client)
    app.dependency_overrides[utc_now]=lambda: fixed+timedelta(hours=12)
    assert client.get('/api/v1/auth/me').status_code == 401

def test_demo_seed_is_idempotent_and_roles_server_owned(client):
    from app.seed import seed_demo
    from sqlalchemy import select, func
    from app.models import User, Company
    with app.state.test_factory() as db:
        seed_demo(db, demo_mode=True)
        seed_demo(db, demo_mode=True)
        db.commit()
        assert db.scalar(select(func.count()).select_from(User)) == 3
        assert db.scalar(select(func.count()).select_from(Company)) == 10
        with pytest.raises(RuntimeError):
            seed_demo(db, demo_mode=False)
    r=client.post('/api/v1/auth/login', json={'email':'officer@demo.local','password':PASSWORD})
    assert r.json()['user']['role'] == 'CREDIT_OFFICER'
    assert add(client).status_code == 403
    assert client.get('/api/v1/companies').status_code == 403

def test_login_failure_limit_is_persisted(client):
    register(client)
    client.post('/api/v1/auth/logout',json={})
    for _ in range(10):
        assert client.post('/api/v1/auth/login', json={'email':'new@example.test','password':'wrongwrongwrong'}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'email':'new@example.test','password':PASSWORD}).status_code == 429

def test_consent_documents_are_versioned(client):
    r=client.get('/api/v1/consents/documents?stage=onboarding')
    assert r.status_code == 200
    assert {x['code'] for x in r.json()['items']} == {'ONBOARDING_PROCESSING','REGISTRY_LOOKUP'}
    assert all(x['version']==CONSENT_VERSION and x['text'] for x in r.json()['items'])
    assert client.get('/api/v1/consents/documents?stage=invalid').status_code == 422

def test_consent_cannot_be_numeric_true(client):
    register(client)
    assert add(client,consents=[{**c,'accepted':1} for c in CONSENTS]).status_code == 422

def test_retry_is_latest_when_clock_has_not_advanced(client):
    from app.clock import utc_now
    app.dependency_overrides[utc_now]=lambda:datetime(2030,1,1,tzinfo=timezone.utc)
    register(client)
    original=add(client,'9900000063').json()
    cid=original['company']['id']
    from app.models import Precheck
    with app.state.test_factory() as db:
        previous=db.get(Precheck,original['precheck']['id'])
        previous.id='ffffffff-ffff-4fff-bfff-ffffffffffff'
        db.commit()
    for version in range(1,12):
        r=client.post(f'/api/v1/companies/{cid}/precheck/retry',json={'version':version},headers={'Idempotency-Key':f'retry-{version}'})
        assert r.status_code == 200
        assert r.json()['precheck']['registry_source_status'] == 'available'
        assert client.get(f'/api/v1/companies/{cid}/precheck').json() == r.json()

def test_session_stores_hash_and_consents_are_append_only(client):
    from app.models import AuthSession, Consent, User
    from sqlalchemy import select
    register(client)
    result=add(client).json()
    with app.state.test_factory() as db:
        session=db.scalar(select(AuthSession))
        assert session.token_hash != client.cookies.get('credit_route_session')
        assert len(session.token_hash)==64
        user=db.scalar(select(User))
        assert user.password_hash.startswith('$argon2id$') and PASSWORD not in user.password_hash
        saved=db.scalars(select(Consent).where(Consent.company_id==result['company']['id'])).all()
        assert {c.code for c in saved}=={'REGISTRY_LOOKUP','ONBOARDING_PROCESSING'}
    client.post(f"/api/v1/companies/{result['company']['id']}/precheck/retry",json={'version':1},headers={'Idempotency-Key':'refresh'})
    with app.state.test_factory() as db:
        assert len(db.scalars(select(Consent)).all())==2
