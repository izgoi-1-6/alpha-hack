"""HTTP flow helpers and fixtures for the application tests.

Helpers drive the public API: onboarding, saved recommendation snapshots, drafts, answers and commands. A few tests
also move a persisted source row to a boundary value (turnover, registration date, registry status); those tweaks are
explicit here. No scoring or policy logic lives in this module.
"""
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select, update
from app.clock import get_clock, utc_now
from app.models import Company, Precheck
from application_oracle import BY_INN
from recommendation_oracle import FIXTURES, PRODUCTS
from test_identity_company import CONSENT_VERSION, PASSWORD, add, register

FIXED_NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)  # the fixture business date, at noon UTC
FIXED_DATE = FIXED_NOW.date()
TERM, LINE, SECURED = 'alfa_term_loan_unsecured', 'alfa_revolving_line_unsecured', 'alfa_term_loan_secured'
CONSENTS = [{'code': 'APPLICATION_PROCESSING', 'version': CONSENT_VERSION, 'accepted': True},
            {'code': 'BKI', 'version': CONSENT_VERSION, 'accepted': True}]
# The spec's six-stage table, in order.
STAGE_FIELDS = [
    ['company_confirmed', 'actual_address', 'actual_activity'],
    ['purpose', 'requested_amount_rub', 'term_months', 'collateral'],
    ['monthly_revenue_rub', 'previous_monthly_revenue_rub', 'financial_period_end', 'tax_regime', 'employees', 'seasonal'],
    ['monthly_debt_payment_rub', 'tax_debt_rub', 'legal_proceedings', 'obligations_note'],
    ['representative_name', 'representative_authority_confirmed', 'beneficial_owners_confirmed'],
    ['accuracy_confirmed'],
]
ANSWER_FIELDS = {name for stage in STAGE_FIELDS for name in stage}
EMAIL = 'new@example.test'  # test_identity_company.register's default account


class Clock:
    """Overridable request clock; tests move `now` explicitly."""
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(client):
    """Pins the request clock to the fixture business date, so onboarded companies score at 2026-10-24. The same clock
    serves `Now` and `get_clock` (a time an upload reads once its body has arrived)."""
    fixed = Clock(FIXED_NOW)
    client.app.dependency_overrides[utc_now] = fixed
    client.app.dependency_overrides[get_clock] = lambda: fixed
    return fixed


@pytest.fixture
def bki_calls():
    """The BKI mock's observable in-process call log, emptied for each test."""
    from app.applications import bki
    bki.CALLS.clear()
    return bki.CALLS


def declared_collateral(value: int = 8_000_000, **changes) -> dict:
    return {'status': 'declared', 'type': 'equipment', 'declared_value_rub': value, 'description': 'Производственное оборудование',
            'owner_confirmed': True, 'encumbered': False, **changes}


def default_product(fixture_id: str) -> str:
    return FIXTURES[fixture_id]['expected_check_outcome']['product_id']


def need_of(fixture_id: str, product: str | None = None, **changes) -> dict:
    """The fixture's stage-2 parameters (purpose, amount, term); a product that requires collateral gets the fixture's
    declared collateral, and a product without a term gets none (its stage 2 has no term field)."""
    fixture = FIXTURES[fixture_id]
    product = PRODUCTS[product or default_product(fixture_id)]
    need = dict(fixture['need'])
    if product['term_min_months'] is None:
        need.pop('term_months', None)
    if product['collateral_mode'] == 'required' and fixture['collateral_status'] == 'declared':
        need['collateral'] = declared_collateral(fixture['collateral_value_rub'], type=fixture['collateral_type'],
                                                 encumbered=fixture['collateral_encumbered'])
    need.update(changes)
    return need


def onboard(client, fixture_id: str, *, new_user: bool = True) -> str:
    if new_user:
        register(client)
    response = add(client, FIXTURES[fixture_id]['inn'])
    assert response.status_code == 201, response.text
    return response.json()['company']['id']


def snapshot_for(client, company_id: str, requested_amount_rub: int = 2_000_000) -> str:
    """A saved recommendation snapshot: the need is the amount alone."""
    response = client.post(f'/api/v1/companies/{company_id}/recommendations', json={'requested_amount_rub': requested_amount_rub})
    assert response.status_code == 201, response.text
    return response.json()['snapshot_id']


def create(client, company_id: str, product_id: str, snapshot_id: str, *, key: str | None = None):
    return client.post('/api/v1/applications', headers={'Idempotency-Key': key or uuid4().hex},
                       json={'company_id': company_id, 'product_id': product_id, 'recommendation_snapshot_id': snapshot_id})


def draft(client, fixture_id: str, *, product: str | None = None, company: str | None = None, **need_changes) -> dict:
    """A new DRAFT for the fixture's need (or a changed one): created from a fresh amount-only snapshot, which prefills
    only the amount, then stage 2 (purpose, term, collateral) answered as the client would."""
    company = company or onboard(client, fixture_id)
    product = product or default_product(fixture_id)
    need = need_of(fixture_id, product, **need_changes)
    response = create(client, company, product, snapshot_for(client, company, need['requested_amount_rub']))
    assert response.status_code == 201, response.text
    application = response.json()['application']
    stage_two = {name: value for name, value in need.items() if name != 'requested_amount_rub' and value is not None}
    if not stage_two:
        return application
    response = patch_answers(client, application, **stage_two)
    assert response.status_code == 200, response.text
    return response.json()['application']


def patch_answers(client, application: dict, *, stage: int | None = None, version: int | None = None, **answers):
    return client.patch(f"/api/v1/applications/{application['id']}/answers",
                        json={'version': version or application['version'], 'current_stage': stage or application['current_stage'],
                              'answers': answers})


def complete_answers(application: dict, **overrides) -> dict:
    """Valid client answers for every stage; the client declares the fixture's monthly debt payment. The tax regime,
    the employee count and the representative are source-owned: prefilled by the server, never sent."""
    fixture = BY_INN[application['company']['inn']]
    return {'company_confirmed': True, 'actual_address': 'Синтетический адрес, офис 1',
            'actual_activity': 'Оптовая торговля', 'seasonal': False,
            'monthly_debt_payment_rub': fixture['monthly_debt_payment_rub'], 'tax_debt_rub': 0, 'legal_proceedings': False,
            'beneficial_owners_confirmed': True, 'accuracy_confirmed': True, **overrides}


def complete(client, application: dict, **overrides) -> dict:
    response = patch_answers(client, application, stage=6, **complete_answers(application, **overrides))
    assert response.status_code == 200, response.text
    return response.json()['application']


def command(client, application: dict, name: str, body: dict, key: str | None, version: int | None):
    return client.post(f"/api/v1/applications/{application['id']}/{name}", headers={'Idempotency-Key': key or uuid4().hex},
                       json={'version': version or application['version'], **body})


def submit(client, application: dict, *, consents=CONSENTS, key: str | None = None, version: int | None = None):
    return command(client, application, 'submit', {'consents': consents}, key, version)


def retry(client, application: dict, *, key: str | None = None, version: int | None = None):
    return command(client, application, 'retry-check', {}, key, version)


def cancel(client, application: dict, reason: str = 'Потребность изменилась', *, key: str | None = None,
           version: int | None = None):
    return command(client, application, 'cancel', {'reason': reason}, key, version)


def submitted(client, fixture_id: str, *, product: str | None = None, company: str | None = None, answers: dict | None = None,
              **need_changes) -> dict:
    """Draft, complete and submit; returns the application after the synchronous check."""
    application = complete(client, draft(client, fixture_id, product=product, company=company, **need_changes), **(answers or {}))
    response = submit(client, application)
    assert response.status_code == 200, response.text
    return response.json()['application']


def read(client, application: dict) -> dict:
    response = client.get(f"/api/v1/applications/{application['id']}")
    assert response.status_code == 200, response.text
    return response.json()['application']


def history(client, application: dict) -> list[dict]:
    response = client.get(f"/api/v1/applications/{application['id']}/history")
    assert response.status_code == 200, response.text
    return response.json()['items']


def relogin(client, email: str = EMAIL) -> None:
    """Opens a new session, e.g. after the clock moved past the 12-hour session lifetime."""
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': PASSWORD})
    assert response.status_code == 200, response.text


def set_turnover(client, company_id: str, revenue: int | None, previous: int | None) -> None:
    with client.app.state.test_factory.begin() as db:
        db.execute(update(Precheck).where(Precheck.company_id == company_id)
                   .values(monthly_revenue_rub=revenue, previous_monthly_revenue_rub=previous))


def set_company(client, company_id: str, **values) -> None:
    with client.app.state.test_factory.begin() as db:
        db.execute(update(Company).where(Company.id == company_id).values(**values))


def scored(client, application: dict) -> dict:
    """The customer's application with the scoring the bank keeps and the client never sees, read from the persisted
    rows: the application's `scored_limit_rub` and the latest evaluation as staff read it (rule, outcome, score, risk,
    scored limit, the stored reasons)."""
    from app.applications.models import Application, Evaluation
    with client.app.state.test_factory() as db:
        limit = db.get(Application, application['id']).scored_limit_rub
        row = db.scalar(select(Evaluation).where(Evaluation.application_id == application['id'])
                        .order_by(Evaluation.sequence.desc()).limit(1))
        evaluation = None if row is None else {'id': row.id, 'rule': row.rule, 'outcome': row.outcome, 'score': row.score,
                                               'risk': row.risk, 'scored_limit_rub': row.scored_limit_rub,
                                               'reasons': list(row.reasons)}
    return {**application, 'scored_limit_rub': limit, 'latest_evaluation': evaluation}


def rows(client, model_name: str, **where) -> list:
    """Persisted application-module rows (imported lazily so a missing module fails per test, not at collection)."""
    from app.applications import models
    model = getattr(models, model_name)
    with client.app.state.test_factory() as db:
        query = select(model)
        for key, value in where.items():
            query = query.where(getattr(model, key) == value)
        return db.scalars(query).all()
