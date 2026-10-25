"""Customer documents over HTTP + DB + private storage: the checklist and its summary, preapproval gating, partial
packets, replacement of UPLOADED revisions, deletion, completion, download authorization and headers, idempotent
replays, lazy expiry in the document phase and PostgreSQL races (one current document per requirement).

Expected values are the spec's literal states, codes and checklist, never the code under test.
"""
from datetime import datetime, timedelta, timezone
import os
import threading
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Company
from application_helpers import cancel, clock, draft, history, read, relogin, rows, submitted
from document_helpers import (DEADLINE, SECURED_DOCS, UNSECURED_DOCS, checklist, complete_docs, completed, delete,
                              document_rows, download, docs_url, jpeg_bytes, pdf_bytes, png_bytes, preapproved, sha256,
                              storage, stored, upload, upload_all, uploaded)
from officer_helpers import claimed, officer, refused
from test_identity_company import ORIGIN, client, register

pytestmark = pytest.mark.usefixtures('clock', 'storage')


def summary(required=2, uploaded=0, accepted=0, rejected=0, missing=UNSECURED_DOCS, can_complete=False) -> dict:
    return {'required_total': required, 'current_uploaded': uploaded, 'accepted': accepted, 'rejected': rejected,
            'missing': list(missing), 'can_complete': can_complete}


@pytest.fixture
def stranger(client):
    """Another synthetic client on its own session."""
    with TestClient(app, headers={'origin': ORIGIN}) as session:
        assert register(session, 'other.client@example.test').status_code == 201
        yield session


# --- checklist and gating --------------------------------------------------------------------------------------------

def test_a_preapproved_application_lists_its_required_documents(client):
    application = preapproved(client)
    body = checklist(client, application)
    notice = body.pop('notice')
    assert body == {'requirements': [{'document_type': kind, 'required': True, 'current_document': None} for kind in UNSECURED_DOCS],
                    'items': []}
    assert notice.startswith('Демонстрационная проверка документов') and 'не антивирусная' in notice
    assert application['document_summary'] == summary()
    assert application['allowed_actions'] == ['upload_document', 'cancel']


def test_the_secured_checklist_adds_ownership_and_valuation(client):
    application = preapproved(client, 'secured_investment')
    assert [item['document_type'] for item in checklist(client, application)['requirements']] == SECURED_DOCS
    assert application['document_summary'] == summary(required=4, missing=SECURED_DOCS)


def test_no_document_summary_before_preapproval(client):
    application = draft(client, 'strong')
    assert application['document_summary'] is None
    assert checklist(client, application)['items'] == []
    refused(upload(client, application), 409, 'INVALID_STATUS')


def at_status(client, status: str) -> dict:
    if status == 'MANUAL_REVIEW':
        return submitted(client, 'medium')
    if status == 'REJECTED':
        return submitted(client, 'high_risk')
    application = preapproved(client)
    if status == 'CANCELLED':
        response = cancel(client, application)
        assert response.status_code == 200
        return response.json()['application']
    if status == 'DOCS_UPLOADED':
        return completed(client, upload_all(client, application)[0])
    return application


@pytest.mark.parametrize('status', ['MANUAL_REVIEW', 'REJECTED', 'CANCELLED', 'DOCS_UPLOADED'])
def test_uploads_deletes_and_completion_are_refused_outside_the_upload_states(client, storage, status):
    application = at_status(client, status)
    assert application['status'] == status
    before = stored(storage)
    refused(upload(client, application), 409, 'INVALID_STATUS')
    refused(complete_docs(client, application), 409, 'INVALID_STATUS')
    assert stored(storage) == before and read(client, application)['version'] == application['version']
    for document in checklist(client, application)['items']:
        refused(delete(client, application, document), 409, 'INVALID_STATUS')
    assert all(action not in application['allowed_actions'] for action in ('upload_document', 'delete_document', 'complete_documents'))


# --- partial packets, replacement, deletion, completion --------------------------------------------------------------

def test_a_partial_packet_cannot_be_completed(client, storage):
    application = preapproved(client)
    preapproved_version = application['version']
    document, application = uploaded(client, application)
    assert application['version'] == preapproved_version + 1 and application['status'] == 'PREAPPROVED'  # same-state edit
    assert application['document_summary'] == summary(uploaded=1, missing=['FINANCIAL_REPORT'])
    assert application['allowed_actions'] == ['upload_document', 'delete_document', 'cancel']
    response = complete_docs(client, application)
    refused(response, 409, 'DOCUMENTS_INCOMPLETE')
    assert response.json()['error']['details'] == {'missing': ['FINANCIAL_REPORT'], 'rejected': []}
    body = checklist(client, application)
    assert [item['current_document'] and item['current_document']['id'] for item in body['requirements']] == [document['id'], None]
    assert [row.to_status for row in rows(client, 'StatusHistory', application_id=application['id'])].count('DOCS_UPLOADED') == 0


def test_an_uploaded_document_is_replaced_by_a_new_revision_and_stays_downloadable(client, storage):
    application = preapproved(client)
    first, application = uploaded(client, application, content=pdf_bytes(text=b'First'))
    second, application = uploaded(client, application, content=png_bytes(), kind='png')
    assert (second['revision'], second['status'], second['media_type']) == (2, 'UPLOADED', 'image/png')
    items = {item['id']: item for item in checklist(client, application)['items']}
    assert items[first['id']]['status'] == 'SUPERSEDED' and items[second['id']]['status'] == 'UPLOADED'
    assert checklist(client, application)['requirements'][0]['current_document']['id'] == second['id']
    assert download(client, application, first).content == pdf_bytes(text=b'First')  # superseded content stays readable
    assert download(client, application, second).content == png_bytes()
    assert len(stored(storage)) == 2
    assert [(row.revision, row.status) for row in document_rows(client)] == [(1, 'SUPERSEDED'), (2, 'UPLOADED')]


def test_deleting_the_current_file_removes_its_bytes_and_reopens_the_requirement(client, storage):
    application = preapproved(client)
    first, application = uploaded(client, application, content=pdf_bytes(text=b'First'))
    second, application = uploaded(client, application, content=pdf_bytes(text=b'Second'))
    before_delete = application['version']
    refused(delete(client, application, first), 409, 'DOCUMENT_NOT_CURRENT')  # a superseded revision is history
    response = delete(client, application, second)
    assert response.status_code == 200, response.text
    application = response.json()['application']
    assert set(response.json()) == {'application'} and application['version'] == before_delete + 1
    assert application['document_summary'] == summary(missing=UNSECURED_DOCS)
    assert list(stored(storage).values()) == [pdf_bytes(text=b'First')]
    refused(download(client, application, second), 404, 'DOCUMENT_NOT_FOUND')
    refused(delete(client, application, second), 404, 'DOCUMENT_NOT_FOUND')
    statuses = {item['id']: item['status'] for item in checklist(client, application)['items']}
    assert statuses == {first['id']: 'SUPERSEDED', second['id']: 'DELETED'}
    third, _ = uploaded(client, application, content=jpeg_bytes(), kind='jpeg')
    assert third['revision'] == 3 and len(stored(storage)) == 2


def test_documents_of_another_application_are_not_found(client, storage):
    application = preapproved(client)
    document, application = uploaded(client, application)
    mine = submitted(client, 'secured_investment')
    refused(delete(client, mine, document), 404, 'DOCUMENT_NOT_FOUND')
    refused(download(client, mine, document), 404, 'DOCUMENT_NOT_FOUND')
    refused(download(client, application, {'id': '00000000-0000-4000-8000-000000000000'}), 404, 'DOCUMENT_NOT_FOUND')


def test_completing_the_packet_moves_to_docs_uploaded_and_freezes_it(client, storage):
    application, documents = upload_all(client, preapproved(client))
    assert application['document_summary'] == summary(uploaded=2, missing=[], can_complete=True)
    assert application['allowed_actions'] == ['upload_document', 'delete_document', 'complete_documents', 'cancel']
    result = completed(client, application)
    assert result['status'] == 'DOCS_UPLOADED' and result['version'] == application['version'] + 1
    assert result['preapproval_expires_at'] == application['preapproval_expires_at'] == '2026-11-07T12:00:00Z'
    assert result['allowed_actions'] == ['cancel'] and result['document_summary'] == summary(uploaded=2, missing=[])
    last = history(client, application)[-1]
    assert (last['from_status'], last['to_status'], last['actor_role'], last['reason_code']) == (
        'PREAPPROVED', 'DOCS_UPLOADED', 'client', 'DOCUMENTS_SUBMITTED')
    assert last['notification']['channel'] == 'demo_in_app' and last['notification']['simulated'] is True
    before = stored(storage)
    refused(upload(client, result, 'BANK_STATEMENT'), 409, 'INVALID_STATUS')
    refused(delete(client, result, documents['BANK_STATEMENT']), 409, 'INVALID_STATUS')
    refused(complete_docs(client, result), 409, 'INVALID_STATUS')
    assert stored(storage) == before


# --- downloads -------------------------------------------------------------------------------------------------------

def test_downloads_are_for_the_owner_and_officers_with_private_attachment_headers(client, officer, stranger, storage):
    application = preapproved(client)
    content = png_bytes(8, 8)
    document, application = uploaded(client, application, 'FINANCIAL_REPORT', content, kind='png', filename='Отчёт.png')
    response = download(client, application, document)
    assert response.status_code == 200 and response.content == content
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-disposition'].startswith('attachment; ')
    assert sha256(response.content) == document['sha256']
    assert download(officer, application, document).content == content  # any officer, before any claim
    refused(download(stranger, application, document), 404, 'APPLICATION_NOT_FOUND')
    refused(stranger.get(docs_url(application)), 404, 'APPLICATION_NOT_FOUND')
    refused(upload(stranger, application), 404, 'APPLICATION_NOT_FOUND')
    refused(delete(stranger, application, document), 404, 'APPLICATION_NOT_FOUND')
    refused(complete_docs(stranger, application), 404, 'APPLICATION_NOT_FOUND')
    with TestClient(app, headers={'origin': ORIGIN}) as anonymous:
        assert download(anonymous, application, document).status_code == 401
        assert anonymous.get(docs_url(application)).status_code == 401
        assert upload(anonymous, application).status_code == 401
    refused(officer.get(docs_url(application)), 403, 'CLIENT_REQUIRED')  # staff read documents through their detail
    refused(upload(officer, application), 403, 'CLIENT_REQUIRED')
    assert len(document_rows(client)) == 1 and len(stored(storage)) == 1


def test_document_mutations_need_the_exact_origin(client, storage):
    application = preapproved(client)
    document, application = uploaded(client, application)
    for response in (client.post(docs_url(application), headers={'origin': 'http://evil.test', 'Idempotency-Key': 'k1'},
                                 files={'file': ('a.pdf', pdf_bytes(), 'application/pdf')},
                                 data={'document_type': 'BANK_STATEMENT', 'version': str(application['version'])}),
                     client.request('DELETE', docs_url(application, f"/{document['id']}"), json={'version': application['version']},
                                    headers={'origin': 'http://evil.test', 'Idempotency-Key': 'k2'}),
                     client.post(docs_url(application, '/complete'), json={'version': application['version']},
                                 headers={'origin': 'http://evil.test', 'Idempotency-Key': 'k3'})):
        refused(response, 403, 'ORIGIN_FORBIDDEN')
    assert len(stored(storage)) == 1


# --- idempotency and versions ----------------------------------------------------------------------------------------

def test_an_upload_replay_returns_the_stored_result_without_a_second_file(client, storage):
    application = preapproved(client)
    first = upload(client, application, key='upload-once')
    again = upload(client, application, key='upload-once')
    assert first.status_code == again.status_code == 201 and again.json() == first.json()
    assert len(document_rows(client)) == 1 and len(stored(storage)) == 1
    for changed in (dict(content=pdf_bytes(text=b'Other')), dict(filename='other.pdf'), dict(document_type='FINANCIAL_REPORT')):
        refused(upload(client, application, key='upload-once', **{'document_type': 'BANK_STATEMENT', **changed}), 409, 'IDEMPOTENCY_CONFLICT')
    refused(upload(client, application, key='upload-twice'), 409, 'VERSION_CONFLICT')  # the old version
    assert len(document_rows(client)) == 1 and len(stored(storage)) == 1


def test_delete_and_complete_replays_record_once(client, storage):
    application, documents = upload_all(client, preapproved(client))
    document, application = uploaded(client, application, 'BANK_STATEMENT', jpeg_bytes(), kind='jpeg')
    first = delete(client, application, document, key='delete-once')
    again = delete(client, application, document, key='delete-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    application = first.json()['application']
    _, application = uploaded(client, application, 'BANK_STATEMENT')
    first = complete_docs(client, application, key='complete-once')
    again = complete_docs(client, application, key='complete-once')
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    refused(complete_docs(client, application, key='complete-twice'), 409, 'VERSION_CONFLICT')
    assert [entry['to_status'] for entry in history(client, application)].count('DOCS_UPLOADED') == 1


# --- lazy expiry -----------------------------------------------------------------------------------------------------

def expiries(client, application) -> int:
    return [row.to_status for row in rows(client, 'StatusHistory', application_id=application['id'])].count('EXPIRED')


def test_uploads_never_extend_the_deadline_and_a_read_at_the_deadline_expires_once(client, clock, storage):
    application = preapproved(client)
    clock.now = DEADLINE - timedelta(seconds=1)
    relogin(client)
    _, application = uploaded(client, application)
    assert application['preapproval_expires_at'] == '2026-11-07T12:00:00Z' and application['status'] == 'PREAPPROVED'
    clock.now = DEADLINE
    body = checklist(client, application)
    assert len(body['items']) == 1 and expiries(client, application) == 1
    expired = read(client, application)
    assert expired['status'] == 'EXPIRED' and expired['allowed_actions'] == [] and expired['document_summary']['can_complete'] is False
    refused(upload(client, expired), 409, 'INVALID_STATUS')
    assert download(client, expired, body['items'][0]).status_code == 200  # terminal: reads and downloads stay
    assert expiries(client, application) == 1 and len(stored(storage)) == 1


@pytest.mark.parametrize('status', ['PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK'])
def test_a_document_command_at_the_deadline_records_the_expiry_and_is_refused(client, officer, clock, storage, status):
    from document_helpers import reviewed
    application, documents = upload_all(client, preapproved(client))
    if status != 'PREAPPROVED':
        application = completed(client, application)
    if status == 'DOCS_REWORK':
        _, application = reviewed(officer, claimed(officer, application), documents['FINANCIAL_REPORT'], 'reject',
                                  reason='Нечитаемая копия: замените файл.')
        application = read(client, application)
    assert application['status'] == status
    before = stored(storage)
    clock.now = DEADLINE
    relogin(client)
    command = complete_docs if status == 'DOCS_UPLOADED' else upload
    refused(command(client, application), 409, 'APPLICATION_EXPIRED')
    (row,) = rows(client, 'Application', id=application['id'])
    assert row.status == 'EXPIRED' and row.version == application['version'] + 1 and expiries(client, application) == 1
    assert stored(storage) == before and len(document_rows(client)) == len(documents)
    refused(command(client, {**application, 'version': row.version}), 409, 'INVALID_STATUS')
    assert expiries(client, application) == 1
    notes = [note.event_code for note in rows(client, 'Notification', application_id=application['id'])]
    assert notes.count('application_expired') == 1


@pytest.mark.parametrize('status', ['DOCS_UPLOADED', 'DOCS_REWORK'])
def test_reads_at_the_deadline_expire_a_submitted_packet_exactly_once(client, officer, clock, storage, status):
    from document_helpers import reviewed
    from officer_helpers import OFFICER_EMAIL, detail, login
    application, documents = upload_all(client, preapproved(client))
    application = completed(client, application)
    if status == 'DOCS_REWORK':
        _, application = reviewed(officer, claimed(officer, application), documents['BANK_STATEMENT'], 'reject', reason='Замените.')
    clock.now = DEADLINE - timedelta(seconds=1)
    relogin(client)
    login(officer, OFFICER_EMAIL)
    assert read(client, application)['status'] == status and expiries(client, application) == 0
    clock.now = DEADLINE
    assert download(officer, application, documents['FINANCIAL_REPORT']).status_code == 200  # the first read expires it
    assert detail(officer, application)['application']['status'] == 'EXPIRED'
    assert checklist(client, application)['items'] and read(client, application)['status'] == 'EXPIRED'
    assert expiries(client, application) == 1 and len(stored(storage)) == 2


@pytest.mark.parametrize('arrives_at,accepted', [(DEADLINE - timedelta(seconds=1), True), (DEADLINE, False)])
def test_an_upload_is_judged_at_the_time_its_body_has_arrived(client, clock, storage, monkeypatch, arrives_at, accepted):
    """The request starts a second before `arrives_at` and the body takes that second to arrive: the command, its
    lazy expiry and `created_at` use the arrival time."""
    from app.documents import intake
    application = preapproved(client)
    clock.now = arrives_at - timedelta(seconds=1)
    relogin(client)
    receive = intake.receive_upload

    def slow(*args, **kwargs):
        form = receive(*args, **kwargs)
        clock.now = arrives_at
        return form

    monkeypatch.setattr(intake, 'receive_upload', slow)
    response = upload(client, application)
    if accepted:
        assert response.status_code == 201, response.text
        assert response.json()['document']['created_at'] == '2026-11-07T11:59:59Z' and len(stored(storage)) == 1
        return
    refused(response, 409, 'APPLICATION_EXPIRED')
    assert expiries(client, application) == 1 and document_rows(client) == [] and stored(storage) == {}


# --- PostgreSQL races ------------------------------------------------------------------------------------------------

pg_only = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='concurrent commands need PostgreSQL row locks')


def race(client, application, calls):
    """Runs (cookies, send) calls concurrently while the company row is locked, so all of them queue on that lock."""
    outcome = [None] * len(calls)

    def run(index, cookies, send):
        with TestClient(app, headers={'origin': ORIGIN}, cookies=cookies) as worker:
            outcome[index] = send(worker)

    with client.app.state.test_factory() as blocker:
        blocker.execute(select(Company).where(Company.id == application['company_id']).with_for_update())
        workers = [threading.Thread(target=run, args=(index, cookies, send)) for index, (cookies, send) in enumerate(calls)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=1)
        assert all(worker.is_alive() for worker in workers), 'every command must wait for the row lock'
        blocker.commit()
    for worker in workers:
        worker.join(timeout=30)
    assert not any(worker.is_alive() for worker in workers)
    return outcome


@pg_only
def test_an_upload_holds_no_open_transaction_while_its_body_is_read(client, storage, monkeypatch):
    """The ownership read ends its transaction before the body streams, so a slow upload holds no pooled connection
    in an open transaction; the locked command begins a fresh one."""
    from sqlalchemy import text
    from app.documents import intake
    receive, seen = intake.receive_upload, []

    def observed(*args, **kwargs):
        with client.app.state.test_factory() as db:
            seen.append(db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                       "AND state LIKE 'idle in transaction%'")))
        return receive(*args, **kwargs)

    application = preapproved(client)
    monkeypatch.setattr(intake, 'receive_upload', observed)
    assert upload(client, application).status_code == 201 and seen == [0]


@pg_only
def test_two_uploads_for_one_requirement_leave_one_current_document_and_one_file(client, storage):
    application = preapproved(client)
    contents = [pdf_bytes(text=b'Alpha'), pdf_bytes(text=b'Beta')]
    outcome = race(client, application, [(client.cookies, lambda worker, content=content: upload(worker, application, content=content))
                                         for content in contents])
    assert sorted(response.status_code for response in outcome) == [201, 409]
    assert next(r for r in outcome if r.status_code == 409).json()['error']['code'] == 'VERSION_CONFLICT'
    (row,) = document_rows(client)
    assert row.status == 'UPLOADED' and list(stored(storage).values()) in ([contents[0]], [contents[1]])
    assert sha256(list(stored(storage).values())[0]) == row.sha256


@pg_only
def test_a_concurrently_replayed_upload_records_one_document(client, storage):
    application = preapproved(client)
    send = lambda worker: upload(worker, application, key='same-upload')  # noqa: E731
    outcome = race(client, application, [(client.cookies, send), (client.cookies, send)])
    assert [response.status_code for response in outcome] == [201, 201] and outcome[0].json() == outcome[1].json()
    assert len(document_rows(client)) == 1 and len(stored(storage)) == 1


@pg_only
def test_a_deletion_racing_completion_on_one_version_lets_only_one_through(client, storage):
    """Both commands are valid on their own for this version; only the row lock makes the second see the first.
    Without it both would succeed, and a deletion could land in a submitted packet."""
    application, documents = upload_all(client, preapproved(client))
    statement = documents['BANK_STATEMENT']
    outcome = race(client, application, [(client.cookies, lambda worker: delete(worker, application, statement)),
                                         (client.cookies, lambda worker: complete_docs(worker, application))])
    assert sorted(response.status_code for response in outcome) == [200, 409]
    assert next(r for r in outcome if r.status_code == 409).json()['error']['code'] == 'VERSION_CONFLICT'
    final = read(client, application)
    (row,) = [row for row in document_rows(client) if row.document_type == 'BANK_STATEMENT']
    if final['status'] == 'DOCS_UPLOADED':  # completion won: the submitted packet is whole
        assert row.status == 'UPLOADED' and len(stored(storage)) == 2
    else:  # deletion won: still collecting, the file is gone
        assert (final['status'], row.status) == ('PREAPPROVED', 'DELETED') and len(stored(storage)) == 1
    assert final['version'] == application['version'] + 1
