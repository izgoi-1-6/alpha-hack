"""Applications on the runtime products over HTTP + DB: the stage-2 contract per product, R1 (product bounds, the
per-purpose term maximum, a pledge for a product without collateral, a term for a product without one, machine
eligibility re-checked at submit against the current company), R3 (no term for a product without one, pledge details
once secured), every product's inclusive bounds, the amount input cap at the policy maximum and the facts pinned at
submission, which every later reader uses instead of the live product.

Bounds, purposes, collateral modes, payment models and documents come from catalog_oracle / application_oracle (their
own reading of the data files), never from the code under test.
"""
import json
import pytest
from sqlalchemy import select
import application_oracle as oracle
import catalog_oracle
from datetime import date
from application_helpers import (CONSENTS, FIXED_DATE, LINE, SECURED, TERM, bki_calls, clock, complete, create,
                                 declared_collateral, history, onboard, patch_answers, read, retry, rows, scored,
                                 set_company, snapshot_for, submit)
from document_helpers import accept_all, checklist, completed, storage, upload_all
from officer_helpers import claimed, detail, officer, ok, preapprove, request_info, respond
from recommendation_oracle import FIXTURES, PRODUCTS
from test_identity_company import client

pytestmark = pytest.mark.usefixtures('clock')
GOSCREDIT, UNIVERSAL, FACTORING = 'alfa_goscredit_zont', 'alfa_universal_limit', 'alfa_factoring'
LINE_SECURED, NONREVOLVING_SECURED = 'alfa_revolving_line_secured', 'alfa_nonrevolving_line_secured'
PSK_INVEST, PSK_WORKING, PSK_BORDER = 'psk_invest_subsidy', 'psk_working_capital', 'psk_borderline'
ALL = catalog_oracle.CARD_IDS
SLIDER_MAX = catalog_oracle.POLICY['amount_slider']['max_rub']
MANUFACTURER = 'gov_manufacturer'  # LLC, SME register, Курская область, OKVED 25.62: eligible for every card product
TERM_INPUT = range(1, 121)  # the questionnaire's term input; a product's own range is checked by R1
PLEDGE = declared_collateral(10_000_000, type='real_estate', description='Склад')


def dialog(client, application: dict) -> dict:
    response = client.get(f"/api/v1/applications/{application['id']}/dialog")
    assert response.status_code == 200, response.text
    return response.json()


def stage_two(client, application: dict) -> dict:
    return {field['name']: field for field in dialog(client, application)['stages'][1]['fields']}


def saved(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()['application']


def fresh(client, product_id: str, fixture: str = MANUFACTURER, *, amount: int | None = None, company: str | None = None) -> dict:
    """A draft straight from an amount-only snapshot of the product's minimum, before any stage-2 answer (for a newly
    onboarded fixture company unless `company` is given)."""
    company = company or onboard(client, fixture)
    response = create(client, company, product_id, snapshot_for(client, company, amount or PRODUCTS[product_id]['amount_min_rub']))
    assert response.status_code == 201, response.text
    return response.json()['application']


def stage_two_answers(product_id: str, **changes) -> dict:
    """Stage-2 answers inside the product: its first purpose, its shortest term, a pledge when collateral is required."""
    product = PRODUCTS[product_id]
    answers = {'purpose': product['purposes'][0]}
    if product['term_min_months'] is not None:
        answers['term_months'] = product['term_min_months']
    if product['collateral_mode'] == 'required':
        answers['collateral'] = PLEDGE
    return {**answers, **changes}


def ready(client, product_id: str, fixture: str = MANUFACTURER, *, company: str | None = None, **changes) -> dict:
    """A complete draft of the product: every stage answered, stage 2 inside the product's bounds."""
    application = fresh(client, product_id, fixture, company=company)
    application = saved(patch_answers(client, application, stage=2, **stage_two_answers(product_id, **changes)))
    return complete(client, application)


def consents_of(client, application: dict) -> list:
    from app.models import Consent
    with client.app.state.test_factory() as db:
        return db.scalars(select(Consent).where(Consent.application_id == application['id'])).all()


def refused_correction(client, application: dict, fields: set) -> None:
    """R1 refuses the submission before the consent gate, and nothing is recorded."""
    for consents in (CONSENTS, []):
        response = submit(client, application, consents=consents)
        assert response.status_code == 422 and response.json()['error']['code'] == 'CORRECTION_REQUIRED', response.text
        assert set(response.json()['error']['fields']) == fields
    assert read(client, application)['status'] == 'DRAFT'
    assert rows(client, 'Evaluation', application_id=application['id']) == []


# --- the stage-2 contract --------------------------------------------------------------------------------------------

@pytest.mark.parametrize('product_id', ALL)
def test_stage_two_follows_the_product(client, product_id):
    product = PRODUCTS[product_id]
    application = fresh(client, product_id)
    contract = dialog(client, application)
    fields = {field['name']: field for field in contract['stages'][1]['fields']}
    has_term, mode = product['term_min_months'] is not None, product['collateral_mode']
    assert list(fields) == ['purpose', 'requested_amount_rub'] + (['term_months'] if has_term else []) + \
           ([] if mode == 'none' else ['collateral'])
    assert [option['value'] for option in fields['purpose']['options']] == product['purposes']
    answers = application['answers']
    assert answers['purpose'] == (product['purposes'][0] if len(product['purposes']) == 1 else None)  # a single purpose is preselected
    amount = fields['requested_amount_rub']
    assert (amount['min'], amount['max']) == (product['amount_min_rub'], product['amount_max_rub'])
    assert answers['requested_amount_rub'] == product['amount_min_rub']  # prefilled from the snapshot's amount
    if has_term:
        term = fields['term_months']
        assert (term['min'], term['max']) == oracle.term_range(product_id, answers['purpose']) and term['required'] is True
        assert term['max_by_purpose'] == product['term_max_months_by_purpose']
    else:
        assert 'term_months' not in contract['missing_fields']  # nothing to answer
    if mode != 'none':
        assert fields['collateral']['required'] is (mode == 'required')
    assert 'funding_pattern' not in answers
    assert all(field['name'] != 'funding_pattern' for stage in contract['stages'] for field in stage['fields'])
    summary = application['product']
    assert (summary['collateral_mode'], summary['payment_model']) == (mode, product['payment_model'])
    assert summary['secured'] is (mode == 'required')
    assert summary['required_documents'] == oracle.required_documents(mode == 'required')


def test_the_term_maximum_follows_the_chosen_purpose(client, bki_calls):
    application = ready(client, GOSCREDIT, purpose='working_capital', term_months=36)
    term = stage_two(client, application)['term_months']
    assert (term['min'], term['max']) == oracle.term_range(GOSCREDIT, 'working_capital') == (6, 36)
    assert dialog(client, application)['field_issues'] == {}
    application = saved(patch_answers(client, application, term_months=37))
    issues = dialog(client, application)['field_issues']
    assert set(issues) == {'term_months'} and '36' in issues['term_months'] and 'Пополнение оборотных средств' in issues['term_months']
    refused_correction(client, application, {'term_months'})
    application = saved(patch_answers(client, application, purpose='investment'))  # the same 37 months fit an investment
    assert stage_two(client, application)['term_months']['max'] == oracle.term_range(GOSCREDIT, 'investment')[1] == 60
    assert dialog(client, application)['field_issues'] == {}
    assert bki_calls == []


@pytest.mark.parametrize('product_id', ALL)
def test_every_product_bound_is_inclusive_and_refused_just_outside(client, bki_calls, product_id):
    """Amount min−1/min/max/max+1 and, per purpose, term min−1/min/max/max+1 against the oracle's effective terms.
    A value outside the questionnaire's own input range (amount above the policy maximum, term outside 1–120) is
    refused when it is saved; any other value outside the product is an R1 correction at submit."""
    product = PRODUCTS[product_id]
    application = ready(client, product_id)
    assert dialog(client, application)['field_issues'] == {}

    def judge(field: str, value: int, valid: bool, in_input: bool) -> None:
        nonlocal application
        response = patch_answers(client, application, **{field: value})
        if not in_input:
            assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR', (field, value)
            return
        application = saved(response)
        issues = dialog(client, application)['field_issues']
        assert set(issues) == (set() if valid else {field}), (field, value, issues)
        if not valid:
            refused_correction(client, application, {field})

    low, high = product['amount_min_rub'], product['amount_max_rub']
    for amount, valid in ((low - 1, False), (low, True), (high, True), (high + 1, False)):
        judge('requested_amount_rub', amount, valid, amount <= SLIDER_MAX)
    application = saved(patch_answers(client, application, requested_amount_rub=low))
    for purpose in product['purposes'] if product['term_min_months'] is not None else []:
        shortest, longest = oracle.term_range(product_id, purpose)
        application = saved(patch_answers(client, application, purpose=purpose, term_months=shortest))
        for term, valid in ((shortest - 1, False), (shortest, True), (longest, True), (longest + 1, False)):
            judge('term_months', term, valid, term in TERM_INPUT)
    assert bki_calls == []


def test_the_amount_input_reaches_the_policy_maximum(client):
    application = ready(client, FACTORING)
    for amount in (150_000_001, SLIDER_MAX):  # above the old 150,000,000 input cap, up to the slider's maximum
        application = saved(patch_answers(client, application, requested_amount_rub=amount))
        assert application['requested_amount_rub'] == application['answers']['requested_amount_rub'] == amount
    response = patch_answers(client, application, requested_amount_rub=SLIDER_MAX + 1)
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'


# --- R1: eligibility, a stray pledge, a stray term ------------------------------------------------------------------

@pytest.mark.parametrize('product_id,change,phrase', [
    (PSK_BORDER, {'region': 'Москва'}, 'регионах'), (PSK_BORDER, {'region': None}, 'регион'),
    (GOSCREDIT, {'okved': '64.19'}, 'ОКВЭД'), (GOSCREDIT, {'okved': None}, 'ОКВЭД'),
    (GOSCREDIT, {'msp_registry': False}, 'МСП'), (PSK_INVEST, {'msp_registry': None}, 'МСП'),
])
def test_eligibility_is_rechecked_on_submit_against_the_current_company(client, bki_calls, product_id, change, phrase):
    """The draft was made while the company was eligible; the company data changed since. With the registry source
    available, a failed or an unknown machine-checkable fact refuses the submission on product_id, like can_apply
    refuses the draft button."""
    application = ready(client, product_id)
    assert dialog(client, application)['field_issues'] == {}
    assert client.get(f"/api/v1/companies/{application['company_id']}").json()['precheck']['registry_source_status'] == 'available'
    set_company(client, application['company_id'], **change)
    issues = dialog(client, application)['field_issues']
    assert set(issues) == {'product_id'} and phrase in issues['product_id']
    assert 'product_id' in read(client, application)['missing_fields']
    refused_correction(client, application, {'product_id'})
    assert bki_calls == [] and consents_of(client, application) == []


SME_REGISTER_PRODUCTS = [product_id for product_id, product in PRODUCTS.items() if product['msp_registry_required']
                         and not product['regions']]  # the gov credit and two PSK programs; the border one has a region rule


def test_the_sme_register_products_are_the_three_without_a_region_rule():
    assert sorted(SME_REGISTER_PRODUCTS) == sorted([GOSCREDIT, PSK_INVEST, PSK_WORKING])


@pytest.mark.parametrize('product_id', SME_REGISTER_PRODUCTS)
def test_an_unavailable_registry_waits_for_the_source_instead_of_asking_for_a_correction(client, bki_calls, product_id):
    """A registry that is unavailable uses R4 (it is not missing client input). The SME flag is unknown only because the
    source is down, so R1 lets it through; the check waits without a BKI request, and the retry's recovery confirms the
    flag and scores the application against the pinned product."""
    fixture = FIXTURES['registry_unavailable']
    application = ready(client, product_id, 'registry_unavailable')
    company_url = f"/api/v1/companies/{application['company_id']}"
    assert client.get(company_url).json()['company']['msp_registry'] is None
    assert dialog(client, application)['field_issues'] == {} and application['missing_fields'] == []
    response = submit(client, application)
    assert response.status_code == 200, response.text
    waiting = scored(client, response.json()['application'])
    assert (waiting['status'], waiting['latest_evaluation']['rule'], bki_calls) == ('WAIT_EXTERNAL', 'R4', [])
    result = scored(client, saved(retry(client, waiting)))
    assert client.get(company_url).json()['company']['msp_registry'] is True
    months = oracle.completed_months(date.fromisoformat(fixture['registered_at']), FIXED_DATE)
    total = oracle.score(months, fixture['monthly_revenue_rub'], fixture['previous_monthly_revenue_rub'],
                         fixture['monthly_debt_payment_rub'], fixture['credit_history'])
    limit = oracle.scored_limit(product_id, oracle.risk(total), fixture['monthly_revenue_rub'])
    rule, status, amount = oracle.outcome(product_id, total, limit, PRODUCTS[product_id]['amount_min_rub'])
    assert (result['status'], result['latest_evaluation']['rule'], result['scored_limit_rub']) == (status, rule, limit)
    assert result['preapproved_amount_rub'] == amount and len(bki_calls) == 1


def test_a_failed_fact_still_needs_correction_while_the_registry_is_unavailable(client, bki_calls):
    application = ready(client, PSK_BORDER, 'registry_unavailable')  # Татарстан is outside the border program's regions
    issues = dialog(client, application)['field_issues']
    assert set(issues) == {'product_id'} and 'регионах' in issues['product_id'] and 'МСП' not in issues['product_id']
    refused_correction(client, application, {'product_id'})
    assert bki_calls == []


def test_a_recovery_that_fails_eligibility_is_a_mandatory_stop_without_bki(client, bki_calls, monkeypatch):
    """After the registry recovers, the check re-evaluates eligibility on the current company data;
    a failed fact rejects (R2, reason ELIGIBILITY_FAILED) before any BKI request, and the application stays submitted."""
    from app import companies
    inn = FIXTURES['registry_unavailable']['inn']
    source = companies.SOURCES[inn]
    monkeypatch.setitem(companies.SOURCES, inn, {**source, 'recovery': {**source['recovery'], 'retry_msp_registry': False}})
    application = ready(client, GOSCREDIT, 'registry_unavailable')
    waiting = scored(client, submit(client, application).json()['application'])
    assert (waiting['status'], waiting['latest_evaluation']['rule']) == ('WAIT_EXTERNAL', 'R4')
    result = saved(retry(client, waiting))
    reasons = result['latest_evaluation']['reasons']  # an eligibility stop keeps its own text for the client
    result = scored(client, result)
    assert reasons == result['latest_evaluation']['reasons']
    evaluation = result['latest_evaluation']
    assert (result['status'], evaluation['rule'], evaluation['outcome'], evaluation['score']) == ('REJECTED', 'R2', 'REJECTED', None)
    assert result['scored_limit_rub'] is None and result['preapproved_amount_rub'] is None and result['allowed_actions'] == []
    assert any('МСП' in reason for reason in evaluation['reasons'])
    last = history(client, application)[-1]
    assert (last['from_status'], last['to_status'], last['reason_code']) == ('CHECKING', 'REJECTED', 'ELIGIBILITY_FAILED')
    assert 'МСП' in last['notification']['message']
    first, second = sorted(rows(client, 'Evaluation', application_id=application['id']), key=lambda row: row.sequence)
    assert (first.rule, second.rule, second.sources['bki']) == ('R4', 'R2', None)
    assert second.input_snapshot['eligibility_failures'] and 'МСП' in second.input_snapshot['eligibility_failures'][0]
    assert bki_calls == []
    assert retry(client, result).status_code == 409  # terminal: no way back to DRAFT


def test_an_inactive_company_on_an_sme_register_product_is_corrected_before_r2(client, bki_calls):
    """R1 precedes R2: the inactive fixture is outside the SME register, so an SME-register product needs correction
    (422) where a product without that rule reaches the defensive R2 rejection."""
    corrected = ready(client, GOSCREDIT, 'inactive')
    issues = dialog(client, corrected)['field_issues']
    assert set(issues) == {'product_id'} and 'МСП' in issues['product_id']
    refused_correction(client, corrected, {'product_id'})
    rejected = submit(client, ready(client, TERM, 'inactive', company=corrected['company_id']))
    assert rejected.status_code == 200 and rejected.json()['application']['status'] == 'REJECTED'
    assert scored(client, rejected.json()['application'])['latest_evaluation']['rule'] == 'R2' and bki_calls == []


def edited_catalog(tmp_path, edit) -> 'object':
    from app.products_config import load_config
    catalog = json.loads(catalog_oracle.CATALOG_PATH.read_text(encoding='utf-8'))
    edit(next(entry for entry in catalog['items'] if entry['id'] == PSK_WORKING))
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
    return load_config(path, catalog_oracle.POLICY_PATH)


@pytest.mark.parametrize('case,fixture,phrase', [('closed', MANUFACTURER, 'закрыт'), ('entity', 'medium', 'ООО')])
def test_a_closed_program_or_another_business_form_is_refused_on_submit(client, bki_calls, monkeypatch, tmp_path, case,
                                                                         fixture, phrase):
    from app.recommendations import catalog
    if case == 'closed':
        edited = edited_catalog(tmp_path, lambda item: item.update(limit_status='exhausted'))
    else:  # the program for legal entities only; `medium` is an ИП
        edited = edited_catalog(tmp_path, lambda item: item['eligibility'].update(entity_types=['ЮЛ']))
    monkeypatch.setattr(catalog, 'CONFIG', edited)
    application = ready(client, PSK_WORKING, fixture)  # a direct-API draft: creation does not gate on can_apply
    issues = dialog(client, application)['field_issues']
    assert set(issues) == {'product_id'} and phrase in issues['product_id']
    refused_correction(client, application, {'product_id'})
    assert bki_calls == []


def test_a_pledge_for_a_product_without_collateral_needs_correction(client, bki_calls):
    application = ready(client, TERM, 'strong')
    assert 'collateral' not in stage_two(client, application)
    application = saved(patch_answers(client, application, collateral=declared_collateral()))  # a direct API answer
    issues = dialog(client, application)['field_issues']
    assert set(issues) == {'collateral'} and 'залог' in issues['collateral'].lower()
    refused_correction(client, application, {'collateral'})
    application = saved(patch_answers(client, application, collateral={'status': 'none'}))  # no pledge is no conflict
    assert dialog(client, application)['field_issues'] == {}
    response = submit(client, application)
    assert response.status_code == 200 and response.json()['application']['status'] == 'PREAPPROVED'
    assert len(bki_calls) == 1


def test_a_term_for_a_product_without_one_needs_correction_and_none_is_asked(client, bki_calls):
    application = ready(client, LINE, 'strong')
    assert 'term_months' not in stage_two(client, application)
    assert application['answers']['term_months'] is None and dialog(client, application)['field_issues'] == {}
    application = saved(patch_answers(client, application, term_months=12))
    issues = dialog(client, application)['field_issues']
    assert set(issues) == {'term_months'} and 'не указывается' in issues['term_months']
    refused_correction(client, application, {'term_months'})
    application = saved(patch_answers(client, application, term_months=None))
    response = submit(client, application)
    assert response.status_code == 200, response.text
    result = response.json()['application']
    assert result['status'] == 'PREAPPROVED' and result['answers']['term_months'] is None and len(bki_calls) == 1


# --- R3: an optional pledge ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('collateral,paths', [
    (None, set()), ({'status': 'none'}, set()), ({'status': 'unknown'}, set()),
    ({'status': 'declared'}, {'collateral.type', 'collateral.declared_value_rub', 'collateral.description'}),
    ({'status': 'declared', 'type': 'real_estate', 'declared_value_rub': 10_000_000}, {'collateral.description'}),
])
def test_an_optional_pledge_needs_its_details_only_once_declared(client, bki_calls, collateral, paths):
    application = ready(client, UNIVERSAL)
    if collateral is not None:
        application = saved(patch_answers(client, application, collateral=collateral))
    secured = oracle.is_secured(UNIVERSAL, collateral)
    assert application['product']['secured'] is secured
    assert application['product']['required_documents'] == oracle.required_documents(secured)
    assert set(path for path in application['missing_fields'] if path.startswith('collateral')) == paths
    response = submit(client, application)
    if paths:
        assert response.status_code == 422 and response.json()['error']['code'] == 'NEED_INFO'
        assert set(response.json()['error']['fields']) == paths and bki_calls == []
    else:
        assert response.status_code == 200, response.text
        assert len(bki_calls) == 1


# --- pinned facts ----------------------------------------------------------------------------------------------------

PINNED_KEYS = ('id', 'amount_min_rub', 'amount_max_rub', 'unsecured_cap_rub', 'term_min_months', 'term_max_months',
               'term_max_months_by_purpose', 'collateral_mode', 'annual_rate_bps', 'rate_certainty', 'payment_model')


@pytest.mark.parametrize('product_id,collateral', [
    (TERM, None), (LINE, None), (SECURED, PLEDGE), (LINE_SECURED, PLEDGE), (NONREVOLVING_SECURED, PLEDGE), (UNIVERSAL, None),
    (UNIVERSAL, PLEDGE), (PSK_WORKING, None), (PSK_WORKING, PLEDGE), (FACTORING, None), (PSK_BORDER, None), (PSK_INVEST, None),
])
def test_submission_pins_the_secured_flag_documents_and_effective_terms(client, product_id, collateral):
    application = ready(client, product_id, collateral=collateral)
    response = submit(client, application)
    assert response.status_code == 200, response.text
    result = response.json()['application']
    secured = oracle.is_secured(product_id, collateral)
    (row,) = rows(client, 'Application', id=application['id'])
    pinned = row.submitted_input_snapshot
    assert pinned['secured'] is secured
    assert pinned['required_documents'] == oracle.required_documents(secured)
    expected = PRODUCTS[product_id]
    assert {key: pinned['product'][key] for key in PINNED_KEYS} == {key: expected[key] for key in PINNED_KEYS}
    assert pinned['product']['base_documents'] == catalog_oracle.POLICY['defaults']['base_documents']
    (evaluation,) = rows(client, 'Evaluation', application_id=application['id'])
    assert evaluation.input_snapshot['secured'] is secured and evaluation.input_snapshot['product_id'] == product_id
    assert (result['product']['secured'], result['product']['required_documents']) == (secured, pinned['required_documents'])
    assert result['product']['payment_model'] == expected['payment_model']


def edited_policy(tmp_path):
    """The shipped policy with the universal limit's collateral taken away and one base document dropped: a change the
    pinned facts of an earlier submission must not follow."""
    from app.products_config import load_config
    policy = json.loads(catalog_oracle.POLICY_PATH.read_text(encoding='utf-8'))
    policy['products'][UNIVERSAL]['collateral_mode'] = 'none'
    policy['defaults']['base_documents'] = ['BANK_STATEMENT']
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(policy, ensure_ascii=False), encoding='utf-8')
    return load_config(catalog_oracle.CATALOG_PATH, path)


def test_every_post_submission_reader_uses_the_pinned_facts(client, officer, bki_calls, monkeypatch, tmp_path, storage):
    """Retry, R5, requestable fields, respond-info, preapproval, the checklist and the final bounds of a secured
    universal limit, after the live policy stopped taking collateral for it and dropped a base document."""
    from app.recommendations import catalog
    pledge, requested = declared_collateral(1_000_000, owner_confirmed=False), 2_000_000
    application = ready(client, UNIVERSAL, 'bki_unavailable', purpose='working_capital', collateral=pledge,
                        requested_amount_rub=requested)
    waiting = submit(client, application).json()['application']
    assert waiting['status'] == 'WAIT_EXTERNAL'
    monkeypatch.setattr(catalog, 'CONFIG', edited_policy(tmp_path))
    live = catalog.CONFIG.product(UNIVERSAL)
    assert live['collateral_mode'] == 'none' and live['base_documents'] == ['BANK_STATEMENT']
    reviewed = saved(retry(client, waiting))
    evaluation = rows(client, 'Evaluation', application_id=application['id'])
    latest = max(evaluation, key=lambda row: row.sequence)
    assert reviewed['status'] == 'MANUAL_REVIEW' and 'collateral_unconfirmed' in latest.input_snapshot['review_flags']
    limit = oracle.scored_limit(UNIVERSAL, 'low', 800_000, 1_000_000, secured=True)
    assert limit == min(70_000_000, 2_400_000, 20_000_000 + 700_000) == scored(client, reviewed)['scored_limit_rub']
    assert reviewed['product']['collateral_mode'] == 'optional' and reviewed['product']['secured'] is True
    staff = claimed(officer, reviewed)
    paths = detail(officer, staff)['requestable_fields']
    assert 'collateral' in paths and 'collateral.owner_confirmed' in paths
    asked = ok(request_info(officer, staff, ['collateral.owner_confirmed']))
    answered = ok(respond(client, asked, {'collateral': {'owner_confirmed': False}}))
    flags = max(rows(client, 'Evaluation', application_id=application['id']), key=lambda row: row.sequence).input_snapshot['review_flags']
    assert answered['status'] == 'MANUAL_REVIEW' and 'collateral_unconfirmed' in flags  # still judged as secured
    staff = detail(officer, answered)['application']
    bound = min(requested, limit)
    assert staff['preapproval'] == {'amount_min_rub': PRODUCTS[UNIVERSAL]['amount_min_rub'], 'amount_max_rub': bound, 'blocked_by': None}
    preapproved = ok(preapprove(officer, staff, bound))
    customer = read(client, preapproved)
    assert [item['document_type'] for item in checklist(client, customer)['requirements']] == oracle.required_documents(True)
    customer, documents = upload_all(client, customer)
    staff = claimed(officer, completed(client, customer))
    staff = accept_all(officer, staff, documents, valuation=500_000)
    final = detail(officer, staff)['application']['final_approval']
    verified = oracle.scored_limit(UNIVERSAL, 'low', 800_000, 500_000, secured=True)
    assert final == {'amount_min_rub': PRODUCTS[UNIVERSAL]['amount_min_rub'], 'amount_max_rub': min(bound, verified),
                     'verified_limit_rub': verified, 'blocked_by': None}
    assert len(bki_calls) == 2


@pytest.mark.parametrize('missing', ['product', 'secured', 'required_documents'])
def test_a_submitted_application_without_a_pinned_fact_fails_loudly(missing):
    from app.applications.models import Application
    from app.applications.products import pinned_terms
    from app.recommendations.catalog import CONFIG
    snapshot = {'product': CONFIG.product(TERM), 'secured': False, 'required_documents': ['BANK_STATEMENT', 'FINANCIAL_REPORT']}
    del snapshot[missing]
    with pytest.raises(RuntimeError, match=missing):
        pinned_terms(Application(id='pinned-test', status='CHECKING', submitted_input_snapshot=snapshot))
