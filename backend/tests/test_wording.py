"""No demo wording in what the server says (revision rule 7).

Cyrillic «демо», «демонстрац…» or «имитац…» is refused in every string literal of the backend code outside docstrings
(labels, notices, notifications, errors, consent texts, the document review notice), in the fixture and policy files and
in every response body of the main client and officer flows.

Latin "demo" (any case) is refused (controller ruling, Task 10 fix round 1) in the values the UI renders — the consent
`version` of both consent stages, `rules_version`, `catalog_version` — and in every human-readable text the server
sends: each Russian literal of the code (the labels, messages, notices, notifications and errors are all Russian) and
each key and string value of the flows' response bodies. The binding exceptions are named in the allow-list below and
nothing else may say "demo"; Latin identifiers of the code that are never sent (env names, file paths, constraint
names, the seed's console output) are outside the human-text scan. The OpenAPI document is a schema of route
identifiers (the allowed fixture list route with its generated operation id and summary): only its title is checked.
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
LATIN = re.compile(r'demo', re.IGNORECASE)
CYRILLIC = re.compile(r'[а-яё]', re.IGNORECASE)
# The binding exceptions (revision rule 7: technical names stay; Task 10 fix round 1 ruling). Within any text:
ALLOWED_TEXT = {
    'seeded e-mail': re.compile(r'[\w.+-]+@demo\.local\b'),
    'data file name': re.compile(r'\bdemo-[\w-]+\.json\b'),
    'environment variable': re.compile(r'\bDEMO_MODE\b'),
    'fixture list route': re.compile(r'/(?:api/v1/)?demo/fixtures\b'),
    'seed password': re.compile(re.escape('DemoCredit2026!')),
}
ALLOWED_KEY = {'demo_mode'}  # GET /health
# Internal identifiers a response carries under these keys; the UI never renders them.
ALLOWED_VALUE = {'source_version': 'demo-fixtures-v2',  # precheck: the fixture file's version
                 'channel': 'demo_in_app',  # notification channel
                 'provider': 'demo_bki_mock'}  # BKI simulator
RENDERED = ('rules_version', 'catalog_version')  # with the consent documents' `version`
BACKEND = Path(__file__).resolve().parents[1]
FIXTURE_FILE = BACKEND.parent / 'data' / 'demo-companies.json'
POLICY_FILE = BACKEND.parent / 'data' / 'demo-policy.json'


def test_the_pattern_catches_the_wording_and_spares_ordinary_words():
    for text in ('Демо-реестр', 'демо', '(демонстрационное решение)', 'Демонстрационная проверка', 'имитация уведомления',
                 'в локальном имитаторе БКИ'):
        assert FORBIDDEN.search(text), text
    for text in ('в пределах лимита', 'лимитами', 'Подставной', 'consent-v2'):
        assert not FORBIDDEN.search(text), text


def latin_demo(text: str) -> bool:
    """Latin "demo" (any case) left once the allowed exceptions are taken out of the text."""
    for allowed in ALLOWED_TEXT.values():
        text = allowed.sub('', text)
    return bool(LATIN.search(text))


def latin_offenders(value, path: str = ''):
    """(path, text) for every key and string value of a response body that says "demo" outside the allow-list."""
    if isinstance(value, dict):
        for key, item in value.items():
            here = f'{path}.{key}' if path else key
            if key not in ALLOWED_KEY and latin_demo(key):
                yield here, key
            if ALLOWED_VALUE.get(key) != item:
                yield from latin_offenders(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from latin_offenders(item, f'{path}[{index}]')
    elif isinstance(value, str) and latin_demo(value):
        yield path, value


def test_latin_demo_is_refused_outside_the_named_exceptions():
    for text in ('demo-consent-v2', 'demo-rules-v2+b84e1ea4', 'Demo', 'DEMO', 'Альфа-Бизнес (demo)',
                 '/demo/alfa-business/0b6f', 'client@demo.local, demo'):
        assert latin_demo(text), text
    for text in ('consent-v2', 'rules-v2+0a1b2c3d', '2026-10-25.1+c0683aa1', 'client@demo.local', 'officer@demo.local',
                 'DEMO_MODE=true', 'demo-companies.json', '/api/v1/demo/fixtures', 'DemoCredit2026!', '/alfa-business/0b6f',
                 'Подставной'):
        assert not latin_demo(text), text
    allowed = {'source_version': 'demo-fixtures-v2', 'channel': 'demo_in_app', 'provider': 'demo_bki_mock',
               'demo_mode': True, 'user': {'email': 'officer@demo.local'}}
    assert list(latin_offenders(allowed)) == []
    # An identifier is allowed only under its own key, and only with its own value.
    leaked = {'message': 'demo_in_app', 'demo_flag': True, 'channel': 'demo_sms', 'items': [{'version': 'demo-consent-v2'}]}
    assert list(latin_offenders(leaked)) == [('message', 'demo_in_app'), ('demo_flag', 'demo_flag'), ('channel', 'demo_sms'),
                                             ('items[0].version', 'demo-consent-v2')]


def docstrings(tree: ast.AST) -> set[int]:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                nodes.add(id(first.value))
    return nodes


def literals():
    """(where, text) for every string literal of the backend code outside docstrings."""
    for path in sorted((BACKEND / 'app').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        skipped = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skipped:
                yield f'{path.relative_to(BACKEND)}:{node.lineno}', node.value


def test_no_server_string_says_demo_or_simulation():
    found = list(literals())
    assert [f'{where}: {text[:80]}' for where, text in found if FORBIDDEN.search(text)] == []
    assert len(found) > 500  # the scan reads the real code base


def test_no_human_text_of_the_server_says_demo_in_latin_letters():
    """The human-readable texts are the Russian literals; Latin identifiers that are never sent are not scanned."""
    human = [(where, text) for where, text in literals() if CYRILLIC.search(text)]
    assert [f'{where}: {text[:80]}' for where, text in human if latin_demo(text)] == []
    assert len(human) > 300


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


def test_the_policy_texts_and_version_say_no_demo():
    policy = json.loads(POLICY_FILE.read_text(encoding='utf-8'))
    assert [text for text in texts(policy) if FORBIDDEN.search(text)] == []
    assert not latin_demo(policy['rules_version'])


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


def parsed(bodies) -> list[tuple[str, str, int, object]]:
    found = []
    for method, path, status, text in bodies:
        try:
            found.append((method, path, status, json.loads(text)))
        except ValueError:
            pass
    return found


def pairs(value):
    """Every (key, value) of a JSON document, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from pairs(item)
    elif isinstance(value, list):
        for item in value:
            yield from pairs(item)


def latin_scanned(bodies) -> list[str]:
    """Latin "demo" in the flows' response bodies outside the allow-list; the OpenAPI schema only by its title."""
    offenders = []
    for method, path, status, body in parsed(bodies):
        if path == '/openapi.json':
            found = [('info.title', body['info']['title'])] if latin_demo(body['info']['title']) else []
        else:
            found = list(latin_offenders(body))
        offenders += [f'{method} {path} {status}: {where} = {text!r}' for where, text in found]
    return offenders


def test_the_main_flows_send_no_demo_wording(client, officer, bki_calls):
    bodies = []
    capture(client, bodies)
    capture(officer, bodies)
    client.get('/openapi.json')
    client.get('/api/v1/health')
    for stage in ('onboarding', 'application'):
        client.get(f'/api/v1/consents/documents?stage={stage}')
    register(client)
    officer.get('/api/v1/auth/me')  # a seeded e-mail
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
    unconsented = complete(client, draft(client, 'secured_investment'))
    submit(client, unconsented, consents=[])  # NEED_INFO: the consents message names the current version
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
    # Latin: the rendered versions first (present and clean), then every human text and value of every body.
    documents = [body for _, path, _, body in parsed(bodies) if path == '/api/v1/consents/documents']
    consent_versions = {item['version'] for body in documents for item in body['items']}
    assert len(documents) == 2 and consent_versions and not any(latin_demo(version) for version in consent_versions)
    versions = {(key, value) for _, _, _, body in parsed(bodies) for key, value in pairs(body) if key in RENDERED}
    assert {key for key, _ in versions} == set(RENDERED) and not any(latin_demo(value) for _, value in versions)
    consents_refusal = next(body for method, path, status, body in parsed(bodies) if path.endswith('/submit') and status == 422
                            and 'consents' in body['error'].get('fields', {}))
    assert all(version in consents_refusal['error']['fields']['consents'] for version in consent_versions)
    assert latin_scanned(bodies) == []
