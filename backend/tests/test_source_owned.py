"""Source-owned answers over HTTP + DB: the tax regime and the employee count come from the
registry payload, the representative's name and authority from the company's Госуслуги verification. They are
prefilled, read-only in the dialog, refused in answers PATCH and in an information response, never asked by R3, never
requestable by an officer, and pinned from their sources at submission. An unavailable registry still waits (R4).

Expected values come from the raw fixture file (recommendation_oracle.FIXTURES), never from the code under test.
"""
import pytest
from application_helpers import (FIXED_NOW, bki_calls, clock, complete, draft, history, patch_answers, read, retry, rows,
                                 scored, submit, submitted)
from officer_helpers import claimed, decisions, detail, ok, officer, refused, request_info, respond
from recommendation_oracle import FIXTURES
from test_identity_company import client

pytestmark = pytest.mark.usefixtures('clock')
REGISTRY_FIELDS = ('tax_regime', 'employees')
AUTHORITY_FIELDS = ('representative_name', 'representative_authority_confirmed')
SOURCE_OWNED = REGISTRY_FIELDS + AUTHORITY_FIELDS


def dialog_fields(client, application) -> dict:
    dialog = client.get(f"/api/v1/applications/{application['id']}/dialog").json()
    return {field['name']: field for stage in dialog['stages'] for field in stage['fields']}


def stored(client, application):
    from app.applications.models import Application
    with client.app.state.test_factory() as db:
        row = db.get(Application, application['id'])
        return dict(row.answers), row.version


def without_registry_values(monkeypatch, fixture_id: str) -> None:
    """The registry mock answers for the fixture without a tax regime or an employee count (restored afterwards)."""
    from app import companies
    inn = FIXTURES[fixture_id]['inn']
    monkeypatch.setitem(companies.SOURCES, inn, {**companies.SOURCES[inn], 'tax_regime': None, 'employees': None})


# --- prefill and the dialog ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('fixture_id', list(FIXTURES))
def test_a_new_draft_prefills_the_source_owned_answers_and_shows_them_read_only(client, fixture_id):
    fixture = FIXTURES[fixture_id]
    application = draft(client, fixture_id)
    answers = application['answers']
    assert {name: answers[name] for name in SOURCE_OWNED} == {
        'tax_regime': fixture['tax_regime'], 'employees': fixture['employees'],
        'representative_name': fixture['director_name'], 'representative_authority_confirmed': True}
    assert answers['beneficial_owners_confirmed'] is None  # still the client's confirmation
    assert not set(SOURCE_OWNED) & set(application['missing_fields'])
    fields = dialog_fields(client, application)
    for name in REGISTRY_FIELDS:
        assert fields[name]['read_only'] is True
        assert fields[name]['source'] == {'name': 'registry', 'status': fixture['registry_source_status'], 'value': fixture[name]}
    assert fields['representative_name']['source'] == {'name': 'gosuslugi', 'status': 'available', 'value': fixture['director_name']}
    assert fields['representative_authority_confirmed']['source'] == {'name': 'gosuslugi', 'status': 'available', 'value': True}
    assert all(fields[name]['read_only'] is True for name in AUTHORITY_FIELDS)
    read_only = [name for name, field in fields.items() if field.get('read_only')]
    assert sorted(read_only) == sorted(SOURCE_OWNED)
    # Nothing is asked of the client for them (R3 skips them): no requirement flags on the read-only descriptors.
    assert all(fields[name]['required'] is False and 'must_be_true' not in fields[name] for name in SOURCE_OWNED)
    assert fields['beneficial_owners_confirmed']['required'] is True and fields['beneficial_owners_confirmed']['must_be_true'] is True
    assert 'source' not in fields['beneficial_owners_confirmed'] and 'source' not in fields['seasonal']


# --- the client cannot set them --------------------------------------------------------------------------------------

@pytest.mark.parametrize('patch', [
    {'tax_regime': 'USN'}, {'tax_regime': None}, {'employees': 7}, {'employees': None},
    {'representative_name': 'Иванов Иван Иванович'}, {'representative_name': None},
    {'representative_authority_confirmed': True}, {'representative_authority_confirmed': False},
    {'employees': 7, 'seasonal': True, 'actual_activity': 'Оптовая торговля'},
    {'tax_regime': 'OTHER', 'employees': 1, 'representative_name': 'Подставной', 'representative_authority_confirmed': True},
])
def test_answers_patch_refuses_source_owned_fields(client, patch):
    application = draft(client, 'strong')
    before = stored(client, application)
    response = patch_answers(client, application, stage=3, **patch)
    error = refused(response, 422, 'SOURCE_OWNED_FIELDS')
    owned = [name for name in patch if name in SOURCE_OWNED]
    assert set(error['fields']) == set(owned) and all(error['fields'].values())
    assert error['details'] == {'fields': owned}
    assert stored(client, application) == before and read(client, application) == application


def test_the_client_still_confirms_the_beneficial_owners_and_the_other_stage_three_answers(client):
    application = draft(client, 'strong')
    saved = patch_answers(client, application, stage=5, beneficial_owners_confirmed=True, seasonal=True).json()['application']
    assert saved['answers']['beneficial_owners_confirmed'] is True and saved['answers']['seasonal'] is True
    assert saved['answers']['representative_name'] == FIXTURES['strong']['director_name']


def test_a_mistyped_source_owned_value_is_refused_as_input(client):
    application = draft(client, 'strong')
    for patch in ({'tax_regime': 'FLAT'}, {'employees': -1}, {'employees': '7'}, {'representative_authority_confirmed': 1}):
        refused(patch_answers(client, application, **patch), 422, 'VALIDATION_ERROR')
    assert read(client, application) == application


# --- submission ------------------------------------------------------------------------------------------------------

def test_submission_pins_the_source_values_whatever_the_draft_holds(client, bki_calls):
    from app.applications.models import Application
    application = complete(client, draft(client, 'strong'))
    with client.app.state.test_factory.begin() as db:  # a draft saved before the fields became source-owned
        row = db.get(Application, application['id'])
        row.answers = {**row.answers, 'tax_regime': 'OTHER', 'employees': 999, 'representative_name': 'Подставной',
                       'representative_authority_confirmed': False}
    response = submit(client, application)
    assert response.status_code == 200, response.text
    fixture = FIXTURES['strong']
    expected = {'tax_regime': fixture['tax_regime'], 'employees': fixture['employees'],
                'representative_name': fixture['director_name'], 'representative_authority_confirmed': True}
    result = response.json()['application']
    assert {name: result['answers'][name] for name in SOURCE_OWNED} == expected
    with client.app.state.test_factory() as db:
        row = db.get(Application, application['id'])
        assert {name: row.submitted_input_snapshot['answers'][name] for name in SOURCE_OWNED} == expected
        assert {name: row.answers[name] for name in SOURCE_OWNED} == expected
    assert result['status'] == 'PREAPPROVED' and len(bki_calls) == 1


def test_r3_never_asks_the_client_for_a_value_the_registry_does_not_know(client, bki_calls, monkeypatch):
    without_registry_values(monkeypatch, 'strong')
    application = draft(client, 'strong')
    assert (application['answers']['tax_regime'], application['answers']['employees']) == (None, None)
    assert not set(REGISTRY_FIELDS) & set(application['missing_fields'])
    fields = dialog_fields(client, application)
    assert fields['tax_regime']['source'] == {'name': 'registry', 'status': 'available', 'value': None}
    response = submit(client, complete(client, application))
    assert response.status_code == 200, response.text
    result = response.json()['application']
    assert result['status'] == 'PREAPPROVED' and result['open_info_request'] is None
    (evaluation,) = rows(client, 'Evaluation', application_id=application['id'])
    assert evaluation.input_snapshot['missing_answers'] == []


@pytest.mark.parametrize('registry_values', ['in the payload', 'absent'])
def test_an_unavailable_registry_still_waits_for_the_source(client, bki_calls, monkeypatch, registry_values):
    if registry_values == 'absent':
        without_registry_values(monkeypatch, 'registry_unavailable')
    application = scored(client, submitted(client, 'registry_unavailable'))
    assert (application['status'], application['latest_evaluation']['rule']) == ('WAIT_EXTERNAL', 'R4')
    assert application['open_info_request'] is None and application['allowed_actions'] == ['retry_check', 'cancel']
    assert bki_calls == [] and rows(client, 'InfoRequest', application_id=application['id']) == []
    (first,) = rows(client, 'Evaluation', application_id=application['id'])
    assert first.input_snapshot['missing_answers'] == []
    recovered = scored(client, retry(client, application).json()['application'])
    assert (recovered['status'], recovered['latest_evaluation']['rule']) == ('PREAPPROVED', 'R8') and len(bki_calls) == 1


# --- officer requests and responses ----------------------------------------------------------------------------------

def review(client, officer) -> dict:
    application = claimed(officer, submitted(client, 'medium', answers={'tax_debt_rub': 1}))  # R5 review
    assert application['status'] == 'MANUAL_REVIEW'
    return application


def test_requestable_fields_leave_out_the_source_owned_answers(client, officer):
    fields = detail(officer, review(client, officer))['requestable_fields']
    assert not set(SOURCE_OWNED) & set(fields)
    assert {'actual_activity', 'seasonal', 'beneficial_owners_confirmed', 'monthly_debt_payment_rub'} <= set(fields)


@pytest.mark.parametrize('fields', [[name] for name in SOURCE_OWNED] + [['seasonal', 'employees'], list(SOURCE_OWNED)])
def test_an_officer_cannot_request_a_source_owned_answer(client, officer, fields):
    application = review(client, officer)
    error = refused(request_info(officer, application, fields), 422, 'FIELD_NOT_REQUESTABLE')
    assert set(error['fields']) == {'requested_fields'} and error['fields']['requested_fields']
    assert error['details'] == {'fields': [name for name in fields if name in SOURCE_OWNED]}
    assert rows(client, 'InfoRequest', application_id=application['id']) == [] and decisions(client, application) == []
    assert read(client, application)['status'] == 'MANUAL_REVIEW'
    assert [item['to_status'] for item in history(client, application)][-1] == 'MANUAL_REVIEW'


def test_an_information_response_cannot_set_a_source_owned_answer(client, officer, bki_calls):
    application = ok(request_info(officer, review(client, officer), ['seasonal']))
    before = stored(client, application)
    error = refused(respond(client, application, {'seasonal': True, 'employees': 3}), 422, 'SOURCE_OWNED_FIELDS')
    assert set(error['fields']) == {'employees'}
    assert stored(client, application) == before and read(client, application)['status'] == 'NEED_INFO'
    answered = ok(respond(client, application, {'seasonal': True}))
    assert answered['status'] == 'MANUAL_REVIEW' and answered['answers']['employees'] == FIXTURES['medium']['employees']
    assert len(bki_calls) == 1


def test_no_request_of_any_origin_can_name_a_source_owned_answer(client, officer):
    from app.applications.info_requests import create_info_request
    from app.applications.models import Application
    application = review(client, officer)
    with client.app.state.test_factory() as db:
        row = db.get(Application, application['id'])
        for name in SOURCE_OWNED:
            for officer_id in (None, officer.user['id']):
                with pytest.raises(ValueError):
                    create_info_request(db, row, kind='client_answers', source=None, requested_fields=[name],
                                        question='Вопрос', now=FIXED_NOW, officer_id=officer_id)
        db.rollback()
