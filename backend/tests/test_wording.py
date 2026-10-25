"""No «демо», «демонстрац…» or «имитац…» wording in what the server says (revision rule 7): every string literal of the
backend code outside docstrings (labels, notices, notifications, errors, consent texts, the document review notice),
the fixture file's names and texts, and every response body of the main client and officer flows. Technical
identifiers stay (`DEMO_MODE`, `@demo.local`, `demo_in_app`, file names): they are Latin and do not match.
"""
import ast
import json
import re
from pathlib import Path
import pytest
from application_helpers import (LINE, bki_calls, clock, complete, draft, history, patch_answers, read, retry, submit,
                                 submitted)
from officer_helpers import claimed, detail, ok, officer, request_info, respond
from test_identity_company import client, create_company, register, verify

pytestmark = pytest.mark.usefixtures('clock')
FORBIDDEN = re.compile(r'(?<![а-яё])(?:демо|имитац|имитатор)', re.IGNORECASE)  # «лимита» is not «имита…»
BACKEND = Path(__file__).resolve().parents[1]
FIXTURE_FILE = BACKEND.parent / 'data' / 'demo-companies.json'


def test_the_pattern_catches_the_wording_and_spares_ordinary_words():
    for text in ('Демо-реестр', 'демо', '(демонстрационное решение)', 'Демонстрационная проверка', 'имитация уведомления',
                 'в локальном имитаторе БКИ'):
        assert FORBIDDEN.search(text), text
    for text in ('в пределах лимита', 'лимитами', 'demo_in_app', 'client@demo.local', 'demo-consent-v2', 'Подставной'):
        assert not FORBIDDEN.search(text), text


def docstrings(tree: ast.AST) -> set[int]:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                nodes.add(id(first.value))
    return nodes


def test_no_server_string_says_demo_or_simulation():
    offenders, scanned = [], 0
    for path in sorted((BACKEND / 'app').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        skipped = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skipped:
                scanned += 1
                if FORBIDDEN.search(node.value):
                    offenders.append(f'{path.relative_to(BACKEND)}:{node.lineno}: {node.value[:80]}')
    assert offenders == []
    assert scanned > 500  # the scan reads the real code base


def texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from texts(item)


def test_fixture_names_and_texts_say_no_demo():
    fixtures = json.loads(FIXTURE_FILE.read_text(encoding='utf-8'))
    assert [text for text in texts(fixtures) if FORBIDDEN.search(text)] == []
    names = [company['name'] for company in fixtures['companies']] + [company['director_name'] for company in fixtures['companies']]
    assert len(names) == 20 and all(names)


def capture(session, bodies: list) -> None:
    """Records every response body the session receives."""
    def record(response):
        response.read()
        bodies.append((response.request.method, response.request.url.path, response.status_code, response.text))
    session.event_hooks = {'request': [], 'response': [record]}


def scanned(bodies) -> list[str]:
    offenders = []
    for method, path, status, text in bodies:
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False)
        except ValueError:
            pass
        if FORBIDDEN.search(text):
            offenders.append(f'{method} {path} {status}: {FORBIDDEN.search(text).group(0)} … {text[:200]}')
    return offenders


def test_the_main_flows_send_no_demo_wording(client, officer, bki_calls):
    bodies = []
    capture(client, bodies)
    capture(officer, bodies)
    client.get('/openapi.json')
    for stage in ('onboarding', 'application'):
        client.get(f'/api/v1/consents/documents?stage={stage}')
    register(client)
    client.get('/api/v1/demo/fixtures')
    client.get('/api/v1/catalog')
    verify(client, '7707083893')  # REGISTRY_NOT_FOUND
    create_company(client, '9900000017', None)  # AUTHORITY_NOT_VERIFIED
    # A preapproved term loan: dialog, a refused source-owned answer, history, documents and the hand-off refusal.
    strong = draft(client, 'strong')
    client.get(f"/api/v1/applications/{strong['id']}/dialog")
    patch_answers(client, strong, employees=3)  # SOURCE_OWNED_FIELDS
    strong = submit(client, complete(client, strong)).json()['application']
    assert strong['status'] == 'PREAPPROVED'
    history(client, strong)
    client.get(f"/api/v1/applications/{strong['id']}/documents")
    retry(client, strong)  # INVALID_STATUS
    client.post('/api/v1/integrations/alfa-business/link', json={'application_id': strong['id']},
                headers={'Idempotency-Key': 'link'})  # INVALID_STATUS
    # Source outages and stops: the registry waits and recovers, the BKI misses a category or is down, inactive is R2.
    waiting = submitted(client, 'registry_unavailable')
    history(client, read(client, retry(client, waiting).json()['application']))
    missing = submitted(client, 'bki_missing')
    respond(client, missing, {})  # TRUSTED_SOURCE_REQUIRED
    history(client, missing)
    history(client, submitted(client, 'bki_unavailable'))
    history(client, submitted(client, 'inactive'))
    submit(client, draft(client, 'missing_turnover'))  # NEED_INFO before the check
    # The officer's review: detail, a refused and an accepted request, the client's response.
    review = claimed(officer, submitted(client, 'medium', product=LINE, answers={'tax_debt_rub': 1}))
    detail(officer, review)
    request_info(officer, review, ['employees'])  # FIELD_NOT_REQUESTABLE
    asked = ok(request_info(officer, review, ['seasonal']))
    respond(client, asked, {'seasonal': True})
    history(client, asked)
    detail(officer, asked)
    officer.get('/api/v1/officer/applications')
    client.get('/api/v1/applications')
    statuses = {status for _, _, status, _ in bodies}
    assert {200, 201, 403, 409, 422} <= statuses and len(bodies) > 60  # the scan saw successes and refusals
    assert scanned(bodies) == []
