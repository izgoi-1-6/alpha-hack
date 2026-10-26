"""Officer-side HTTP helpers and fixtures for the review queue and decision tests.

Each staff session is its own TestClient on the same app and test database as the customer's `client`, so a test can
act as the customer and as one or two officers without logging out. The demo officer comes from the demo seed; a
second officer is inserted the way the seed creates staff (public registration only creates clients).
"""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from app.main import app
from application_helpers import FIXED_NOW, rows
from test_identity_company import ORIGIN, PASSWORD

OFFICER_EMAIL = 'officer@demo.local'
SECOND_OFFICER_EMAIL = 'second.officer@example.test'
REASON = 'Проверил выписку и анкету: решение обосновано.'


def login(session, email: str) -> dict:
    response = session.post('/api/v1/auth/login', json={'email': email, 'password': PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()['user']


def seed_demo_actors(client) -> None:
    from app.seed import seed_demo
    with client.app.state.test_factory.begin() as db:
        seed_demo(db, demo_mode=True)


def add_officer(client, email: str, display_name: str) -> str:
    """A staff account created like the demo seed's officer (role set server-side, never through registration)."""
    from app.identity import password_hasher
    from app.models import User
    with client.app.state.test_factory.begin() as db:
        user = User(email=email, password_hash=password_hasher.hash(PASSWORD), display_name=display_name,
                    role='CREDIT_OFFICER', created_at=FIXED_NOW)
        db.add(user)
        db.flush()
        return user.id


@pytest.fixture
def officer(client, clock):
    """The seeded demo officer, logged in on its own session."""
    seed_demo_actors(client)
    with TestClient(app, headers={'origin': ORIGIN}) as session:
        session.user = login(session, OFFICER_EMAIL)
        yield session


@pytest.fixture
def second_officer(client, clock):
    add_officer(client, SECOND_OFFICER_EMAIL, 'Второй кредитный специалист')
    with TestClient(app, headers={'origin': ORIGIN}) as session:
        session.user = login(session, SECOND_OFFICER_EMAIL)
        yield session


def staff_url(application: dict, suffix: str = '') -> str:
    return f"/api/v1/officer/applications/{application['id']}{suffix}"


def staff_command(session, application: dict, name: str, body: dict | None = None, *, key: str | None = None,
                  version: int | None = None):
    return session.post(staff_url(application, f'/{name}'), headers={'Idempotency-Key': key or uuid4().hex},
                        json={'version': version or application['version'], **(body or {})})


def claim(session, application: dict, **options):
    return staff_command(session, application, 'claim', **options)


def request_info(session, application: dict, fields: list[str], reason: str = 'Уточните, пожалуйста, сведения анкеты.', **options):
    return staff_command(session, application, 'request-info', {'reason': reason, 'requested_fields': fields}, **options)


def preapprove(session, application: dict, amount: int, reason: str = REASON, **options):
    return staff_command(session, application, 'preapprove', {'amount_rub': amount, 'reason': reason}, **options)


def reject(session, application: dict, reason: str = REASON, **options):
    return staff_command(session, application, 'reject', {'reason': reason}, **options)


def ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()['application']


def refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()['error']
    assert error['code'] == code, response.text
    return error


def detail(session, application: dict) -> dict:
    response = session.get(staff_url(application))
    assert response.status_code == 200, response.text
    return response.json()


def claimed(session, application: dict) -> dict:
    return ok(claim(session, application))


def respond(client, application: dict, answers: dict, response: str = 'Ответ на запрос: сведения уточнены.', *,
            key: str | None = None, version: int | None = None):
    return client.post(f"/api/v1/applications/{application['id']}/respond-info",
                       headers={'Idempotency-Key': key or uuid4().hex},
                       json={'version': version or application['version'], 'response': response, 'answers': answers})


def set_status(client, application: dict, status: str) -> None:
    """Moves a persisted application to a document-phase status directly, without the document commands."""
    from app.applications.models import Application
    with client.app.state.test_factory.begin() as db:
        db.execute(update(Application).where(Application.id == application['id']).values(status=status))


def decisions(client, application: dict) -> list:
    return sorted(rows(client, 'OfficerDecision', application_id=application['id']), key=lambda row: row.sequence)
