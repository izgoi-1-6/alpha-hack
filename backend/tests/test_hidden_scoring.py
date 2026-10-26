"""The client never learns the scoring (user request after hand-over: «User shouldn't know the results of scoring»).

Every customer application surface — the application, the list, the dialog, the history with its notifications, the
document checklist and every command response — carries no score, risk band, factors, review flags, scored limit or
rule field, no score-revealing rule id (R5–R11) and no text about points, risk, scoring or the calculated limit, for
every outcome family. Clients get neutral texts by outcome; a source wait, an information request, a known inactive
company and a failed eligibility fact keep their own texts. Staff responses keep everything.

The customer texts are the ruling's literal wording, written out here rather than read from the code under test.
"""
import json
import re
from uuid import uuid4
import pytest
from sqlalchemy import update
from application_helpers import (TERM, bki_calls, clock, complete, draft, history, onboard, read, retry, rows, set_turnover,
                                 submit, submitted)
from document_helpers import storage, upload
from officer_helpers import claimed, detail, ok, officer, request_info, respond
from recommendation_oracle import FIXTURES
from test_identity_company import client

pytestmark = pytest.mark.usefixtures('clock')
NBSP = ' '
PREAPPROVED = 'Заявка предварительно одобрена. Это не окончательное решение.'
SMALLER = (f'Заявка предварительно одобрена. Предварительно одобрена сумма 2{NBSP}400{NBSP}000{NBSP}₽ — меньше '
           'запрошенной; исходная сумма заявки сохранена. Это не окончательное решение.')
REVIEW = 'Заявку рассмотрит кредитный специалист.'
REJECTED = 'К сожалению, сейчас мы не можем одобрить заявку.'
REJECTION_NOTICE = 'По заявке принят отказ. К сожалению, сейчас мы не можем одобрить заявку.'
INACTIVE = 'Компания не действует по данным реестра.'
CHECKING_NOTICE = 'Заявка проверяется по данным источников.'
HIDDEN_KEYS = {'score', 'risk', 'scored_limit_rub', 'factors', 'review_flags', 'rule'}
HIDDEN_RULES = re.compile(r'^R(?:[5-9]|1[01])$')
SCORING_WORDS = re.compile(r'балл|риск|скоринг|лимит', re.IGNORECASE)
COMPANY_NAMES = sorted((fixture['name'] for fixture in FIXTURES.values()), key=len, reverse=True)  # «ИП «Средний риск»»


def capture(session, bodies: list) -> None:
    """Records every JSON body the session receives from an application route (the customer surfaces)."""
    def record(response):
        response.read()
        if response.request.url.path.startswith('/api/v1/applications'):
            bodies.append((response.request.method, response.request.url.path, response.status_code, json.loads(response.text)))
    session.event_hooks = {'request': [], 'response': [record]}


def offenders(value, path: str = ''):
    """(path, what) for every hidden key, score-revealing rule id or scoring word of a body, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            here = f'{path}.{key}' if path else key
            if key in HIDDEN_KEYS:
                yield here, f'key {key}'
            yield from offenders(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from offenders(item, f'{path}[{index}]')
    elif isinstance(value, str):
        text = value
        for name in COMPANY_NAMES:  # a synthetic profile's name is not a scoring result
            text = text.replace(name, '')
        if HIDDEN_RULES.match(text) or SCORING_WORDS.search(text):
            yield path, value


def leaks(bodies) -> list[str]:
    return [f'{method} {path} {status}: {where} = {what!r}' for method, path, status, body in bodies
            for where, what in offenders(body)]


def use_bki(monkeypatch, fixture_id='strong', **values):
    from app import companies
    inn = FIXTURES[fixture_id]['inn']
    monkeypatch.setitem(companies.SOURCES, inn, {**companies.SOURCES[inn], **values})


def read_everything(client, application: dict) -> dict:
    """Every customer read of the application: the application, the list, the dialog, the history and, once in the
    document phase, the checklist. Returns the application as read."""
    current = read(client, application)
    assert client.get('/api/v1/applications').status_code == 200
    assert client.get(f"/api/v1/applications/{application['id']}/dialog").status_code == 200
    history(client, application)
    if current['document_summary'] is not None:
        assert client.get(f"/api/v1/applications/{application['id']}/documents").status_code == 200
    return current


# --- one flow per outcome family -------------------------------------------------------------------------------------

def inactive(client, officer, monkeypatch):
    response = submit(client, draft(client, 'inactive'))  # known inactive overrides the missing answers
    assert response.status_code == 200, response.text
    return response.json()['application']


def overdue(client, officer, monkeypatch):
    use_bki(monkeypatch, current_overdue_days=30)
    return submitted(client, 'strong')


def ineligible(client, officer, monkeypatch):
    """After a registry recovery the company is outside the SME register: R2 with reason ELIGIBILITY_FAILED."""
    from app import companies
    inn = FIXTURES['registry_unavailable']['inn']
    source = companies.SOURCES[inn]
    monkeypatch.setitem(companies.SOURCES, inn, {**source, 'recovery': {**source['recovery'], 'retry_msp_registry': False}})
    from test_application_products import GOSCREDIT, ready
    return ok(retry(client, submit(client, ready(client, GOSCREDIT, 'registry_unavailable')).json()['application']))


def registry_wait(client, officer, monkeypatch):
    return submitted(client, 'registry_unavailable')


def bki_wait(client, officer, monkeypatch):
    return submitted(client, 'bki_unavailable')


def bki_gap(client, officer, monkeypatch):
    return submitted(client, 'bki_missing')


def tax_debt(client, officer, monkeypatch):
    return submitted(client, 'strong', answers={'tax_debt_rub': 1})


def zero_turnover(client, officer, monkeypatch):
    company = onboard(client, 'strong')
    set_turnover(client, company, 0, 680_000)
    return submitted(client, 'strong', company=company)


def high_risk(client, officer, monkeypatch):
    return submitted(client, 'high_risk')


def limit_below_minimum(client, officer, monkeypatch):
    company = onboard(client, 'strong')
    set_turnover(client, company, 99_999, 99_999)  # low risk; 3 x 99,999 = 299,997 < 300,000
    return submitted(client, 'strong', company=company, requested_amount_rub=300_000, answers={'monthly_debt_payment_rub': 0})


def preapproved(client, officer, monkeypatch):
    application = submitted(client, 'strong')
    response = upload(client, application)  # the document surface returns the application too
    assert response.status_code == 201, response.text
    return response.json()['application']


def smaller_amount(client, officer, monkeypatch):
    return submitted(client, 'strong', requested_amount_rub=3_000_000)


def medium_within(client, officer, monkeypatch):
    return submitted(client, 'medium', requested_amount_rub=600_000)


def medium_above(client, officer, monkeypatch):
    return submitted(client, 'medium', requested_amount_rub=700_000)


def forced_review(client, officer, monkeypatch):
    """Trusted-source recovery: the rules alone would say R8, the outcome is a forced review."""
    return ok(retry(client, submitted(client, 'bki_missing')))


def answered(client, officer, monkeypatch):
    """The re-check after the client's information response (its reasons say the calculation was updated)."""
    application = claimed(officer, submitted(client, 'medium', requested_amount_rub=700_000))
    asked = ok(request_info(officer, application, ['seasonal']))
    return ok(respond(client, asked, {'seasonal': True}))


# (flow, rule of the latest evaluation, status, the customer's evaluation reasons — None: the staff texts are kept —,
#  the last history row's customer reason code and text, its notification — None: the stored one is kept)
FAMILIES = {
    'R2 inactive': (inactive, 'R2', 'REJECTED', [INACTIVE], 'R2', INACTIVE, f'По заявке принят отказ. {INACTIVE}'),
    'R2 overdue': (overdue, 'R2', 'REJECTED', [REJECTED], 'CHECK_RESULT', REJECTED, REJECTION_NOTICE),
    'R2 eligibility': (ineligible, 'R2', 'REJECTED', None, 'ELIGIBILITY_FAILED', None, None),
    'R3': (bki_gap, 'R3', 'NEED_INFO', None, 'R3', None, None),
    'R4 registry': (registry_wait, 'R4', 'WAIT_EXTERNAL', None, 'R4', None, None),
    'R4 BKI': (bki_wait, 'R4', 'WAIT_EXTERNAL', None, 'R4', None, None),
    'R5 tax debt': (tax_debt, 'R5', 'MANUAL_REVIEW', [REVIEW], 'CHECK_RESULT', REVIEW, None),
    'R5 zero turnover': (zero_turnover, 'R5', 'MANUAL_REVIEW', [REVIEW], 'CHECK_RESULT', REVIEW, None),
    'R6': (high_risk, 'R6', 'REJECTED', [REJECTED], 'CHECK_RESULT', REJECTED, REJECTION_NOTICE),
    'R7': (limit_below_minimum, 'R7', 'REJECTED', [REJECTED], 'CHECK_RESULT', REJECTED, REJECTION_NOTICE),
    'R8': (preapproved, 'R8', 'PREAPPROVED', [PREAPPROVED], 'CHECK_RESULT', PREAPPROVED, None),
    'R9': (smaller_amount, 'R9', 'PREAPPROVED', [SMALLER], 'CHECK_RESULT', SMALLER, None),
    'R10': (medium_within, 'R10', 'MANUAL_REVIEW', [REVIEW], 'CHECK_RESULT', REVIEW, None),
    'R11': (medium_above, 'R11', 'MANUAL_REVIEW', [REVIEW], 'CHECK_RESULT', REVIEW, None),
    'forced review': (forced_review, 'R8', 'MANUAL_REVIEW', [REVIEW], 'CHECK_RESULT', REVIEW, None),
    'after a response': (answered, 'R11', 'MANUAL_REVIEW', [REVIEW], 'INFO_PROVIDED', 'Ответ на запрос: сведения уточнены.',
                         None),
}


@pytest.mark.parametrize('family', list(FAMILIES))
def test_customer_responses_carry_no_scoring_for_any_outcome(client, officer, bki_calls, storage, monkeypatch, family):
    flow, rule, status, reasons, code, text, notice = FAMILIES[family]
    bodies = []
    capture(client, bodies)
    application = read_everything(client, flow(client, officer, monkeypatch))
    (saved,) = rows(client, 'Application', id=application['id'])
    latest = max(rows(client, 'Evaluation', application_id=application['id']), key=lambda row: row.sequence)
    assert (application['status'], latest.rule) == (status, rule)  # the flow reached the family it names
    assert len(bodies) >= 6 and leaks(bodies) == []
    assert 'scored_limit_rub' not in application
    evaluation = application['latest_evaluation']
    assert set(evaluation) == {'id', 'outcome', 'reasons', 'created_at'} and evaluation['outcome'] == latest.outcome
    assert evaluation['reasons'] == (list(latest.reasons) if reasons is None else reasons)
    last = history(client, application)[-1]
    assert last['reason_code'] == code
    stored = rows(client, 'StatusHistory', id=last['id'])[0]
    assert last['reason_text'] == (stored.reason_text if text is None else text)
    note = rows(client, 'Notification', status_history_id=last['id'])[0]
    assert last['notification']['message'] == (note.message if notice is None else notice)
    # The bank keeps its own record: the stored reasons, the rule and the scored limit are unchanged.
    assert stored.reason_code == ('INFO_PROVIDED' if family == 'after a response' else
                                  'ELIGIBILITY_FAILED' if family == 'R2 eligibility' else rule)
    assert saved.scored_limit_rub == latest.scored_limit_rub


def test_the_checking_step_and_a_stored_rejection_notice_never_name_the_scoring(client, bki_calls):
    application = submitted(client, 'high_risk')
    checking, rejection = history(client, application)[1:]
    assert checking['notification']['message'] == CHECKING_NOTICE
    assert rejection['notification']['message'] == REJECTION_NOTICE
    stored = {row.event_code: row.message for row in rows(client, 'Notification', application_id=application['id'])}
    assert stored['application_rejected'] == REJECTION_NOTICE  # the notice the client was sent is the neutral one
    # Rows written before the change still carry the old texts; the customer view maps them as well.
    from app.applications.models import Notification
    with client.app.state.test_factory.begin() as db:
        for event, message in (('application_checking', 'Заявка проверяется: источники данных и скоринг.'),
                               ('application_rejected', 'По заявке принят отказ. Высокий риск по результатам скоринга: '
                                                        'менее 50 баллов.')):
            db.execute(update(Notification).where(Notification.application_id == application['id'],
                                                  Notification.event_code == event).values(message=message))
    checking, rejection = history(client, application)[1:]
    assert (checking['notification']['message'], rejection['notification']['message']) == (CHECKING_NOTICE, REJECTION_NOTICE)


def test_a_replayed_command_returns_the_hidden_view(client, bki_calls):
    application = complete(client, draft(client, 'medium', requested_amount_rub=700_000))
    first = submit(client, application, key='hidden-replay')
    again = submit(client, application, key='hidden-replay')
    assert again.json() == first.json() and list(offenders(again.json())) == []


# --- staff keep everything -------------------------------------------------------------------------------------------

def test_officer_responses_keep_the_score_risk_factors_limit_rule_and_staff_texts(client, officer, bki_calls):
    review = submitted(client, 'medium', requested_amount_rub=700_000)  # 65 points, medium risk, scored limit 600,000: R11
    rejected = submitted(client, 'high_risk')  # 10 points: R6
    body = detail(officer, review)
    staff = body['application']
    assert staff['scored_limit_rub'] == 600_000
    evaluation = staff['latest_evaluation']
    assert (evaluation['rule'], evaluation['outcome'], evaluation['score'], evaluation['risk'], evaluation['scored_limit_rub']) == \
           ('R11', 'MANUAL_REVIEW', 65, 'medium', 600_000)
    assert evaluation['factors']['credit_history_points'] == 25 and evaluation['review_flags'] == []
    assert evaluation['reasons'] == [f'Средний риск: запрошенная сумма выше рассчитанного лимита. Возможная сумма — до '
                                     f'600{NBSP}000{NBSP}₽; заявку рассмотрит кредитный специалист.']
    (record,) = body['evaluations']
    assert (record['rule'], record['score'], record['risk'], record['scored_limit_rub']) == ('R11', 65, 'medium', 600_000)
    assert record['reasons'] == evaluation['reasons'] and record['factors'] == evaluation['factors']
    last = body['history'][-1]
    assert (last['reason_code'], last['reason_text']) == ('R11', evaluation['reasons'][0])
    queue = officer.get('/api/v1/officer/applications', params={'status': 'MANUAL_REVIEW'}).json()['items']
    (item,) = [item for item in queue if item['id'] == review['id']]
    assert (item['scored_limit_rub'], item['latest_evaluation']['score'], item['latest_evaluation']['risk']) == (600_000, 65, 'medium')
    assert item['latest_evaluation']['factors'] is not None
    body = detail(officer, rejected)
    evaluation = body['application']['latest_evaluation']
    assert (evaluation['rule'], evaluation['score'], evaluation['risk']) == ('R6', 10, 'high')
    assert evaluation['reasons'] == ['Высокий риск по результатам скоринга: менее 50 баллов.']
    last = body['history'][-1]
    assert (last['reason_code'], last['reason_text']) == ('R6', 'Высокий риск по результатам скоринга: менее 50 баллов.')
    assert last['notification']['message'] == REJECTION_NOTICE  # staff see what the client was told
    # The same applications, as their owner sees them.
    for application in (review, rejected):
        assert list(offenders(read(client, application))) == [] and list(offenders(history(client, application))) == []


def test_the_scan_catches_every_hidden_field_rule_and_word():
    leaked = {'score': 65, 'items': [{'reason_code': 'R11', 'reason_text': 'Средний риск'}, {'text': 'Балл не рассчитан'}],
              'latest_evaluation': {'rule': 'R2', 'reasons': ['Рассчитанный лимит 299 997 ₽ ниже минимальной суммы.']},
              'note': 'Заявка проверяется: источники данных и скоринг.'}
    assert [where for where, _ in offenders(leaked)] == ['score', 'items[0].reason_code', 'items[0].reason_text',
                                                         'items[1].text', 'latest_evaluation.rule',
                                                         'latest_evaluation.reasons[0]', 'note']
    clean = {'company': {'name': 'ИП «Средний риск»'}, 'reason_code': 'CHECK_RESULT', 'reasons': [REVIEW, REJECTED, SMALLER],
             'codes': ['R2', 'R3', 'R4', 'R12', 'R1'], 'indicative_limit_rub': 2_400_000}
    assert list(offenders(clean)) == []
