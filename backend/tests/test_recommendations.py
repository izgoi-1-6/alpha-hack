"""Recommendation HTTP contract: product bounds, estimates, fixtures, saved snapshots, no BKI/scoring inputs.

Expected values come from the spec/acceptance documents, the frozen fixture JSON and the exact-arithmetic
oracle in recommendation_oracle.py, never from the recommendation code under test.
"""
from copy import deepcopy
import os
import threading
from uuid import uuid4
import pytest
from sqlalchemy import select, update
from app.models import Company, Precheck
from test_identity_company import client, register, add
from recommendation_oracle import FIXTURES, HELD_OUT, PRODUCTS, annuity_rub, collateral_cap_rub, full_utilization_interest_rub

NEED = {'purpose':'working_capital','funding_pattern':'one_time','requested_amount_rub':1500000,'term_months':12}
TERM = 'alfa_term_loan_unsecured'
LINE = 'alfa_revolving_line_unsecured'
SECURED = 'alfa_term_loan_secured'
# Archive entries that share no id with a supported product (acceptance A03: "six informational research IDs").
INFORMATIONAL = {'alfa_revolving_line_secured','alfa_nonrevolving_line_secured','psk_invest_subsidy',
                 'psk_working_capital','psk_borderline','zont_corpmsp'}
ITEM_KEYS = {'product_id','rank','status','can_apply','indicative_limit_rub','catalog_max_rub','requested_amount_rub',
             'checks','reasons','alternatives','estimated_payment_rub','payment_note'}
CHECK_CODES = ['company_active','entity_type','purpose','funding_pattern','term','amount_min','catalog_max',
               'turnover','collateral','amount_capacity']

def setup(client, inn='9900000017'):
    register(client)
    return add(client, inn).json()['company']['id']

def fixture_company(client, fixture_id):
    register(client)
    response=add(client, FIXTURES[fixture_id]['inn'])
    assert response.status_code == 201, response.text
    return response.json()['company']['id']

def set_revenue(client, company, revenue):
    with client.app.state.test_factory.begin() as db:
        db.scalar(select(Precheck).where(Precheck.company_id==company)).monthly_revenue_rub=revenue

def declared(value, **changes):
    return {'status':'declared','type':'equipment','declared_value_rub':value,'description':'Демо оборудование',
            'owner_confirmed':True,'encumbered':False,**changes}

def recommend(client, company, **changes):
    return client.post(f'/api/v1/companies/{company}/recommendations', json={**NEED, **changes})

def items(response):
    assert response.status_code == 201, response.text
    return {i['product_id']:i for i in response.json()['items']}

def check(item, code):
    return next(c for c in item['checks'] if c['code']==code)

def test_catalog_research_separated(client):
    response=client.get('/api/v1/catalog')  # public, read-only reference data
    assert response.status_code == 200
    catalog=response.json()
    assert catalog['catalog_version']=='demo-2026-10-24-v1' and catalog['rules_version']=='demo-rules-v1'
    assert catalog['products'] == list(PRODUCTS.values())
    assert {p['id'] for p in catalog['products']} == {TERM, LINE, SECURED}
    assert all(p['can_apply'] is True for p in catalog['products'])
    research={i['id']:i for i in catalog['research_items']}
    assert len(catalog['research_items']) == 9 and set(research) == {TERM, LINE, SECURED} | INFORMATIONAL
    assert all(i['can_apply'] is False for i in research.values())

def test_research_archive_limits_never_drive_recommendations(client):
    company=setup(client)
    set_revenue(client,company,100_000_000)  # three times turnover is far above every ceiling
    result=items(recommend(client,company,requested_amount_rub=5_000_000,term_months=48))
    assert set(result) == {TERM, LINE, SECURED} and not set(result) & INFORMATIONAL
    # The archive allows 30m and 12-60 months for the unsecured loan; the demo policy does not.
    assert result[TERM]['catalog_max_rub']==3_000_000 and result[TERM]['indicative_limit_rub']==3_000_000
    assert result[TERM]['can_apply'] is False and check(result[TERM],'catalog_max')['result']=='failed'
    assert result[SECURED]['catalog_max_rub']==6_000_000

def test_snapshot_and_item_contract_shape(client):
    company=setup(client)
    body=recommend(client,company).json()
    assert set(body)=={'snapshot_id','catalog_version','rules_version','items','created_at'}
    assert body['catalog_version']=='demo-2026-10-24-v1' and body['rules_version']=='demo-rules-v1'
    assert body['created_at'].endswith('Z')
    assert sorted(i['product_id'] for i in body['items'])==sorted([TERM,LINE,SECURED])
    for item in body['items']:
        assert set(item)==ITEM_KEYS
        assert [c['code'] for c in item['checks']]==CHECK_CODES
        assert all(c['result'] in ('passed','failed','unknown') and c['text'] for c in item['checks'])
        assert item['status'] in ('fits','needs_info','does_not_fit')
        assert item['requested_amount_rub']==NEED['requested_amount_rub']
        assert item['reasons'] and isinstance(item['alternatives'],list)
        assert 'Предварительная оценка по обороту, не предодобрение' in ' '.join(item['reasons'])

def test_same_need_returns_identical_ranked_items_in_distinct_snapshots(client):
    company=setup(client)
    first,second=recommend(client,company).json(),recommend(client,company).json()
    assert first['items']==second['items'] and first['snapshot_id']!=second['snapshot_id']

@pytest.mark.parametrize('amount,status', [(2399999,'fits'),(2400000,'fits'),(2400001,'does_not_fit')])
def test_known_capacity_boundaries(client, amount, status):
    company=setup(client)
    result=items(recommend(client,company,requested_amount_rub=amount))
    assert result[TERM]['status']==status
    assert result[TERM]['indicative_limit_rub']==2400000
    assert result[TERM]['can_apply'] is True

BOUNDS=[  # product, amount min/max, term min/max: the spec's product table
    (TERM, 300_000, 3_000_000, 6, 36),
    (LINE, 300_000, 3_000_000, 6, 18),
    (SECURED, 500_000, 6_000_000, 12, 60),
]

@pytest.mark.parametrize('product,low,high,shortest,longest', BOUNDS)
def test_amount_and_term_bounds_are_inclusive_for_every_product(client, product, low, high, shortest, longest):
    company=setup(client)
    set_revenue(client,company,10_000_000)  # turnover never binds below the largest ceiling
    base={'funding_pattern':'repeated' if product==LINE else 'one_time','collateral':declared(20_000_000)}
    rate=PRODUCTS[product]['annual_rate_bps']
    def read(amount, months):
        return items(recommend(client,company,**base,requested_amount_rub=amount,term_months=months))[product]
    middle=(shortest+longest)//2
    for amount,valid in [(low-1,False),(low,True),(high,True),(high+1,False)]:
        item=read(amount,middle)
        assert check(item,'amount_min')['result']==('passed' if amount>=low else 'failed'), amount
        assert check(item,'catalog_max')['result']==('passed' if amount<=high else 'failed'), amount
        assert item['can_apply'] is valid, amount
        assert item['status']==('fits' if valid else 'does_not_fit'), amount
        expected=(full_utilization_interest_rub(amount,rate) if product==LINE else annuity_rub(amount,rate,middle)) if valid else None
        assert item['estimated_payment_rub']==expected, amount
    for months,valid in [(shortest-1,False),(shortest,True),(longest,True),(longest+1,False)]:
        item=read(low,months)
        assert check(item,'term')['result']==('passed' if valid else 'failed'), months
        assert item['can_apply'] is valid, months
        assert item['status']==('fits' if valid else 'does_not_fit'), months
        assert (item['estimated_payment_rub'] is not None) is valid, months

def test_personal_capacity_is_not_catalog_ceiling_and_does_not_block_draft(client):
    company=setup(client)
    set_revenue(client,company,200000)
    result=items(recommend(client,company,requested_amount_rub=600001))
    assert result[TERM]['indicative_limit_rub']==600000
    assert result[TERM]['catalog_max_rub']==3000000
    assert result[TERM]['status']=='does_not_fit'
    assert result[TERM]['can_apply'] is True
    assert result[TERM]['alternatives']

def test_turnover_below_product_minimum_is_explained_and_can_still_draft(client):
    company=setup(client)
    set_revenue(client,company,99_999)  # three times turnover: 299,997, just under the 300k minimum
    item=items(recommend(client,company,requested_amount_rub=300_000))[TERM]
    assert item['indicative_limit_rub']==299_997 and item['status']=='does_not_fit' and item['can_apply'] is True
    assert item['estimated_payment_rub'] is None and 'ниже минимальной суммы' in item['payment_note']
    assert not any('меньшей суммы' in text for text in item['reasons'])
    set_revenue(client,company,100_000)  # exactly 300,000: the minimum itself
    item=items(recommend(client,company,requested_amount_rub=300_000))[TERM]
    assert item['indicative_limit_rub']==300_000 and item['status']=='fits'
    assert item['estimated_payment_rub']==annuity_rub(300_000,2350,12)

@pytest.mark.parametrize('revenue',[None,0])
def test_unknown_or_anomalous_turnover_never_invents_capacity(client,revenue):
    company=setup(client)
    set_revenue(client,company,revenue)
    result=items(recommend(client,company))
    for product in (TERM, LINE, SECURED):
        assert result[product]['status']=='needs_info'
        assert result[product]['indicative_limit_rub'] is None
        assert result[product]['estimated_payment_rub'] is None
        assert result[product]['can_apply'] is True

@pytest.mark.parametrize('collateral',[None,{'status':'none'},{'status':'unknown'}])
def test_unknown_collateral_and_founder_is_not_guarantor_consent(client,collateral):
    company=setup(client)
    result=items(recommend(client,company,collateral=collateral))
    assert result[SECURED]['status']=='needs_info'
    assert result[SECURED]['indicative_limit_rub'] is None
    assert result[SECURED]['estimated_payment_rub'] is None
    assert result[SECURED]['can_apply'] is True
    assert any('поручител' in r.lower() for r in result[SECURED]['reasons'])
    assert 'залоге' in result[SECURED]['payment_note']

@pytest.mark.parametrize('owner,encumbered', [(True,False),(False,False),(True,True)])
def test_declared_collateral_ltv_and_review(client,owner,encumbered):
    company=setup(client)
    collateral=declared(2000001,owner_confirmed=owner,encumbered=encumbered)
    result=items(recommend(client,company,requested_amount_rub=1400000,collateral=collateral))
    assert result[SECURED]['indicative_limit_rub']==1400000
    assert result[SECURED]['status']==('fits' if owner and not encumbered else 'needs_info')

@pytest.mark.parametrize('value,limit',[(714_285,499_999),(714_286,500_000),(1_000_000,700_000),(2_000_001,1_400_000),(8_000_000,2_400_000),(1,0)])
def test_secured_limit_is_floor_of_seventy_percent_capped_by_turnover(client,value,limit):
    company=setup(client)  # turnover 800k: three times is 2.4m
    assert limit==min(6_000_000,3*800_000,collateral_cap_rub(value,7000))  # the table agrees with exact arithmetic
    item=items(recommend(client,company,requested_amount_rub=500_000,collateral=declared(value)))[SECURED]
    assert item['indicative_limit_rub']==limit
    # Acceptance boundary: 499,999 is below the 500,000 secured minimum, 500,000 is exactly the minimum.
    fits=limit>=500_000
    assert item['status']==('fits' if fits else 'does_not_fit')
    assert item['estimated_payment_rub']==(annuity_rub(500_000,2150,12) if fits else None)
    assert item['can_apply'] is True

@pytest.mark.parametrize('registry,status',[('inactive','does_not_fit'),('unknown','needs_info')])
def test_registry_gates_application(client,registry,status):
    company=setup(client)
    with client.app.state.test_factory.begin() as db:
        db.get(Company,company).registry_status=registry
    result=items(recommend(client,company))
    assert result[TERM]['status']==status
    assert result[TERM]['can_apply'] is False

def test_inactive_fixture_gives_read_only_results_with_a_failure_reason(client):
    company=fixture_company(client,'inactive')
    result=items(recommend(client,company))
    for item in result.values():
        assert item['status']=='does_not_fit' and item['can_apply'] is False and item['estimated_payment_rub'] is None
        assert check(item,'company_active')['result']=='failed'
        assert any('прекращена' in text for text in item['reasons'])

def test_unavailable_registry_fixture_has_no_fit_until_retry_recovers_it(client):
    company=fixture_company(client,'registry_unavailable')
    before=recommend(client,company).json()
    result={i['product_id']:i for i in before['items']}
    assert not any(i['status']=='fits' for i in result.values())
    assert all(i['can_apply'] is False and check(i,'company_active')['result']=='unknown' for i in result.values())
    assert result[TERM]['status']=='needs_info' and result[TERM]['indicative_limit_rub']==2_400_000  # turnover is known
    retried=client.post(f'/api/v1/companies/{company}/precheck/retry',json={'version':1},headers={'Idempotency-Key':'recover-registry'})
    assert retried.status_code==200 and retried.json()['company']['registry_status']=='active'
    after=items(recommend(client,company))
    assert after[TERM]['status']=='fits' and after[TERM]['can_apply'] is True
    assert client.get(f'/api/v1/companies/{company}/recommendations/{before["snapshot_id"]}').json()==before

def test_missing_turnover_fixture_keeps_cards_with_null_limits_and_allows_a_draft(client):
    company=fixture_company(client,'missing_turnover')
    before=recommend(client,company,requested_amount_rub=1_000_000).json()
    result={i['product_id']:i for i in before['items']}
    assert set(result)=={TERM,LINE,SECURED}
    for item in result.values():
        assert item['indicative_limit_rub'] is None and item['estimated_payment_rub'] is None
        assert item['status']=='needs_info' and item['can_apply'] is True
        assert check(item,'turnover')['result']=='unknown' and any('Оборот неизвестен' in text for text in item['reasons'])
        assert item['alternatives']
    retried=client.post(f'/api/v1/companies/{company}/precheck/retry',json={'version':1},headers={'Idempotency-Key':'recover-turnover'})
    assert retried.status_code==200
    after=items(recommend(client,company,requested_amount_rub=1_000_000))
    assert after[TERM]['indicative_limit_rub']==2_400_000 and after[TERM]['status']=='fits'
    assert client.get(f'/api/v1/companies/{company}/recommendations/{before["snapshot_id"]}').json()==before

def test_medium_fixture_upper_estimate_is_three_times_turnover_and_line_ranks_first(client):
    company=fixture_company(client,'medium')
    need={k:FIXTURES['medium']['need'][k] for k in ('purpose','funding_pattern','requested_amount_rub','term_months')}
    body=recommend(client,company,**need).json()
    assert body['items'][0]['product_id']==LINE
    result={i['product_id']:i for i in body['items']}
    assert result[LINE]['indicative_limit_rub']==result[TERM]['indicative_limit_rub']==1_800_000
    assert result[LINE]['estimated_payment_rub']==full_utilization_interest_rub(500_000,2400)

def test_high_risk_fixture_estimate_is_blind_to_credit_history(client):
    company=fixture_company(client,'high_risk')
    item=items(recommend(client,company,requested_amount_rub=300_000))[TERM]
    assert item['indicative_limit_rub']==900_000 and item['status']=='fits'  # BKI risk is unknown before submission
    assert not any(key in item for key in ('score','risk','approval_probability'))

def test_secured_investment_fixture_limit_is_turnover_bound_below_catalog_ceiling(client):
    company=fixture_company(client,'secured_investment')
    body=recommend(client,company,purpose='investment',funding_pattern='one_time',requested_amount_rub=4_000_000,
                   term_months=36,collateral=declared(8_000_000)).json()
    result={i['product_id']:i for i in body['items']}
    assert body['items'][0]['product_id']==SECURED
    secured=result[SECURED]
    # min(6m ceiling, 3 x 1.5m = 4.5m, 70% of 8m = 5.6m) = 4.5m
    assert secured['indicative_limit_rub']==4_500_000 and secured['catalog_max_rub']==6_000_000
    assert secured['status']=='fits' and secured['can_apply'] is True
    assert secured['estimated_payment_rub']==annuity_rub(4_000_000,2150,36)==151_729
    for other in (TERM,LINE):
        assert result[other]['status']=='does_not_fit' and result[other]['can_apply'] is False
        assert result[other]['estimated_payment_rub'] is None

@pytest.mark.parametrize('with_declared_collateral',[False,True])
@pytest.mark.parametrize('task',HELD_OUT,ids=lambda task:task['id'])
def test_first_ranked_product_matches_the_predeclared_answer_key(client,task,with_declared_collateral):
    fixture=FIXTURES[task['fixture_id']]
    company=fixture_company(client,task['fixture_id'])
    need={key:task[key] for key in ('purpose','funding_pattern','requested_amount_rub','term_months')}
    if with_declared_collateral and fixture['collateral_status']=='declared':
        need['collateral']=declared(fixture['collateral_value_rub'],type=fixture['collateral_type'],
                                    encumbered=fixture['collateral_encumbered'])
    first=recommend(client,company,**need).json()['items'][0]
    assert first['product_id']==task['expected_product_id']

@pytest.mark.parametrize('purpose,pattern,first', [('working_capital','one_time',TERM),('working_capital','repeated',LINE),('investment','one_time',SECURED)])
def test_purpose_pattern_ranking_and_unknown_warning(client,purpose,pattern,first):
    company=setup(client)
    response=recommend(client,company,purpose=purpose,funding_pattern=pattern,collateral=declared(10000000,type='real_estate',description='Демо помещение'))
    result=items(response)
    assert response.json()['items'][0]['product_id']==first
    assert [i['rank'] for i in response.json()['items']]==[1,2,3]
    if purpose=='investment':
        assert result[TERM]['can_apply'] is False
    else:
        other=LINE if first==TERM else TERM
        assert check(result[other],'funding_pattern')['result']=='unknown'
        assert result[other]['status']=='fits'

def test_unsecured_product_ranks_before_cheaper_secured_one_when_both_fit(client):
    company=setup(client)
    body=recommend(client,company,requested_amount_rub=2_000_000,collateral=declared(4_000_000)).json()
    assert [i['status'] for i in body['items'][:2]]==['fits','fits']
    assert [i['product_id'] for i in body['items'][:2]]==[TERM,SECURED]  # secured 21.50% < unsecured 23.50%, yet second

def test_payments_decimal_annuity_and_revolving_interest(client):
    company=setup(client)
    result=items(recommend(client,company))
    assert result[TERM]['estimated_payment_rub']==141477
    assert result[LINE]['estimated_payment_rub']==30000
    assert result[TERM]['payment_note'].startswith('Расчёт на сумму 1 500 000 ₽, срок 12 мес. ')
    assert 'основной долг' in result[LINE]['payment_note'].lower()
    assert 'комисси' in result[TERM]['payment_note'].lower()
    result=items(recommend(client,company,term_months=120))
    assert all(i['estimated_payment_rub'] is None and not i['can_apply'] for i in result.values())

def test_payment_examples_from_the_acceptance_contract(client):
    company=setup(client)
    result=items(recommend(client,company,requested_amount_rub=1_000_000))
    assert result[TERM]['estimated_payment_rub']==94_318  # 1m / 12 months / 23.50%
    result=items(recommend(client,company,funding_pattern='repeated',requested_amount_rub=333_333))
    assert result[LINE]['estimated_payment_rub']==6_667  # ceil(6,666.66): interest rounds up, principal due at maturity

def test_payment_is_calculated_on_the_personal_limit_when_the_request_is_higher(client):
    company=setup(client)
    item=items(recommend(client,company,requested_amount_rub=2_500_000))[TERM]
    assert item['status']=='does_not_fit' and item['can_apply'] is True
    assert item['estimated_payment_rub']==annuity_rub(2_400_000,2350,12)
    assert 'Расчёт на сумму 2 400 000 ₽' in item['payment_note'] and item['requested_amount_rub']==2_500_000

def test_snapshots_are_owned_immutable_and_do_not_include_bki(client):
    company=setup(client)
    before=recommend(client,company)
    items(before)
    payload=deepcopy(before.json())
    url=f'/api/v1/companies/{company}/recommendations/{payload["snapshot_id"]}'
    assert client.get(url).json()==payload
    recommend(client,company,requested_amount_rub=400000)
    client.post(f'/api/v1/companies/{company}/precheck/retry',json={'version':1},headers={'Idempotency-Key':'refresh'})
    assert client.get(url).json()==payload
    from app.recommendations.models import RecommendationSnapshot
    with client.app.state.test_factory() as db:
        row=db.get(RecommendationSnapshot,payload['snapshot_id'])
        assert row.precheck_id
        raw=str(row.input_snapshot).lower()
        assert 'bki' not in raw and 'credit_history' not in raw and 'score' not in raw
        assert row.need=={**NEED,'collateral':None}
    client.post('/api/v1/auth/logout',json={})
    assert client.get(url).status_code==401
    assert recommend(client,company).status_code==401
    register(client,'other@example.test')
    assert client.get(url).status_code==404
    assert recommend(client,company).status_code==404

@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='row locking needs the PostgreSQL integration database')
def test_calculation_waits_for_a_concurrent_source_update_and_uses_the_new_precheck(client):
    company=setup(client)
    outcome={}
    with client.app.state.test_factory() as updater:
        # A retry in progress: it holds the company row lock before it appends the new source data.
        updater.execute(select(Company).where(Company.id==company).with_for_update())
        worker=threading.Thread(target=lambda:outcome.update(response=recommend(client,company)))
        worker.start()
        worker.join(timeout=1)
        assert worker.is_alive(),'the calculation must wait for the company row lock'
        updater.execute(update(Precheck).where(Precheck.company_id==company).values(monthly_revenue_rub=300_000))
        updater.commit()
    worker.join(timeout=15)
    assert not worker.is_alive()
    result=items(outcome['response'])
    # Reading the source before taking the lock would still report the old 800k turnover (2.4m).
    assert result[TERM]['indicative_limit_rub']==900_000

def test_saved_snapshot_keeps_its_policy_version_when_the_catalog_changes(client,monkeypatch):
    from app.recommendations.catalog import CATALOG
    company=setup(client)
    first=recommend(client,company,requested_amount_rub=1_000_000).json()
    url=f'/api/v1/companies/{company}/recommendations/{first["snapshot_id"]}'
    assert next(i for i in first['items'] if i['product_id']==TERM)['estimated_payment_rub']==94_318
    monkeypatch.setitem(CATALOG,'catalog_version','demo-next-test')
    monkeypatch.setitem(CATALOG,'rules_version','demo-rules-next-test')
    monkeypatch.setitem(next(p for p in CATALOG['products'] if p['id']==TERM),'annual_rate_bps',3000)
    second=recommend(client,company,requested_amount_rub=1_000_000).json()
    assert (second['catalog_version'],second['rules_version'])==('demo-next-test','demo-rules-next-test')
    assert next(i for i in second['items'] if i['product_id']==TERM)['estimated_payment_rub']==annuity_rub(1_000_000,3000,12)
    assert client.get(url).json()==first  # served from the saved snapshot, never recomputed from live policy
    assert (first['catalog_version'],first['rules_version'])==('demo-2026-10-24-v1','demo-rules-v1')

_BAD_COLLATERAL={'type':'vehicle','declared_value_rub':1,'description':'Демо'}
@pytest.mark.parametrize('change',[
    {'requested_amount_rub':True},{'requested_amount_rub':1.1},{'requested_amount_rub':150000001},{'requested_amount_rub':'1500000'},
    {'requested_amount_rub':-1},{'requested_amount_rub':0},{'term_months':0},{'term_months':121},{'term_months':12.0},
    {'purpose':'consumer'},{'funding_pattern':'weekly'},{'credit_history':'good'},
    {'annual_rate_bps':100},{'products':[]},{'amount_max_rub':99999999},  # policy is server-owned
    {'collateral':{'status':'declared','declared_value_rub':1000000}},{'collateral':{'status':'none','owner_confirmed':1}},
    {'collateral':{'status':'declared',**{**_BAD_COLLATERAL,'declared_value_rub':0}}},
    {'collateral':{'status':'declared',**{**_BAD_COLLATERAL,'declared_value_rub':True}}},
    {'collateral':{'status':'declared',**{**_BAD_COLLATERAL,'type':'boat'}}},
    {'collateral':{'status':'declared',**{**_BAD_COLLATERAL,'description':'   '}}},
    {'collateral':{'status':'declared',**{**_BAD_COLLATERAL,'description':'я'*501}}},
    {'collateral':{'status':'pledged'}},{'collateral':{'status':'none','guarantor_consent':True}},
])
def test_strict_need_validation(client,change):
    company=setup(client)
    assert recommend(client,company,**change).status_code==422

def test_comparison_input_limits_are_inclusive_and_never_crash(client):
    company=setup(client)
    response=recommend(client,company,requested_amount_rub=150_000_000,term_months=120,collateral=declared(1,description='я'*500))
    assert response.status_code==201
    result=items(response)
    assert all(i['can_apply'] is False and i['estimated_payment_rub'] is None for i in result.values())
    # One RUB of collateral gives a computed zero cap: floor(0.7), not an unknown limit.
    tiny=items(recommend(client,company,requested_amount_rub=600_000,collateral=declared(1)))[SECURED]
    assert tiny['indicative_limit_rub']==0 and tiny['status']=='does_not_fit' and tiny['estimated_payment_rub'] is None

def test_recommendations_never_access_bki_source_or_score(client,monkeypatch):
    company=setup(client)
    from app import companies
    from app.applications import bki
    class ForbiddenSource:
        def __getitem__(self,key):
            pytest.fail('Recommendations must not query external/source fixtures (including BKI)')
        def get(self,*args):
            pytest.fail('Recommendations must use persisted precheck only')
    monkeypatch.setattr(companies,'SOURCES',ForbiddenSource())
    bki.CALLS.clear()
    result=items(recommend(client,company))
    assert bki.CALLS==[]  # the BKI simulator's call log: no request before a consented submission
    assert all('БКИ не запрашивалось' in ' '.join(i['reasons']) for i in result.values())
    assert not any('score' in i or 'approval_probability' in i for i in result.values())

def test_snapshot_company_scope_role_and_origin(client):
    first=setup(client)
    second=add(client,'9900000049').json()['company']['id']
    snapshot=recommend(client,first).json()['snapshot_id']
    assert client.get(f'/api/v1/companies/{second}/recommendations/{snapshot}').status_code==404
    missing=client.get(f'/api/v1/companies/{first}/recommendations/{uuid4()}')
    assert missing.status_code==404 and missing.json()['error']['code']=='RECOMMENDATION_NOT_FOUND'
    assert client.post(f'/api/v1/companies/{first}/recommendations',json=NEED,headers={'origin':'http://evil.test'}).status_code==403
    from app.seed import seed_demo
    with client.app.state.test_factory.begin() as db: seed_demo(db,demo_mode=True)
    client.post('/api/v1/auth/login',json={'email':'officer@demo.local','password':'DemoCredit2026!'})
    assert recommend(client,first).status_code==403
    assert client.get(f'/api/v1/companies/{first}/recommendations/{snapshot}').status_code==403
