from datetime import date, datetime
from typing import Literal
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import authority, idempotency
from .clock import iso_utc
from .config import settings
from .errors import ApiError
from .fixtures import FIXTURES, SOURCES, registry_source
from .idempotency import IdempotencyKey
from .identity import Db, Now, ClientUser
from .models import AuthorityVerification, Company, Precheck, Consent
from .schemas import CompanyInput, VersionInput

# v2: the texts no longer call the service a demonstration; a text change is a new version. The UI shows it
# («Версия consent-v2»), so it carries no demo wording either.
CONSENT_VERSION='consent-v2'
CONSENT_TEXTS={
    'ONBOARDING_PROCESSING':'Согласен на обработку данных компании для подбора финансирования.',
    'REGISTRY_LOOKUP':'Разрешаю запросить сведения о компании и её оборотах в реестре и открытых источниках.',
    'APPLICATION_PROCESSING':'Согласен на обработку данных анкеты для рассмотрения заявки.',
    'BKI':'Разрешаю запрос кредитной истории в бюро кредитных историй после отправки заявки.',
}
router=APIRouter(tags=['companies'])

def public_row(row) -> dict:
    """Public company/precheck columns only; never use for User/Session or source fixtures."""
    result={}
    for col in row.__table__.columns:
        if col.name == 'company_version': continue
        value=getattr(row,col.name)
        result[col.name]=iso_utc(value) if isinstance(value,datetime) else value.isoformat() if isinstance(value,date) else value
    return result

def get_owned_company(db: Session, company_id: str, user_id: str, *, for_update: bool=False) -> Company:
    query=select(Company).where(Company.id==company_id,Company.owner_user_id==user_id)
    if for_update: query=query.with_for_update()
    company=db.scalar(query)
    if not company: raise ApiError(404,'COMPANY_NOT_FOUND','Компания не найдена')
    return company

def latest_precheck(db: Session, company_id: str) -> Precheck:
    row=db.scalar(select(Precheck).where(Precheck.company_id==company_id).order_by(Precheck.company_version.desc()))
    if not row: raise ApiError(404,'PRECHECK_NOT_FOUND','Проверка компании не найдена')
    return row

def company_result(db: Session, company: Company) -> dict:
    return {'company':public_row(company),'precheck':public_row(latest_precheck(db,company.id))}

def append_precheck(db: Session, company: Company, source: dict, now: datetime) -> Precheck:
    # Registry facts: eligibility reads the SME-register flag; tax regime and employee count are registry-owned too.
    registry={k:source.get(k) for k in ('name','registered_at','registry_status','okved','region','legal_address','msp_registry','tax_regime','employees')}
    turnover={k:source.get(k) for k in ('monthly_revenue_rub','previous_monthly_revenue_rub','financial_period_end')}
    row=Precheck(company_id=company.id,company_version=company.version,registry_source_status=source['registry_source_status'],turnover_source_status=source['turnover_source_status'],registry_payload=registry,turnover_payload=turnover,monthly_revenue_rub=source.get('monthly_revenue_rub'),previous_monthly_revenue_rub=source.get('previous_monthly_revenue_rub'),financial_period_end=date.fromisoformat(source['financial_period_end']) if source.get('financial_period_end') else None,source_version=FIXTURES['fixture_version'],checked_at=now,synthetic=True)
    db.add(row)
    db.flush()
    return row

def create_company(db: Session, owner_id: str, source: dict, now: datetime, *, verification: AuthorityVerification,
                   seeded: bool=False) -> Company:
    # Data whitelist contains BKI oracle values; only the explicit registry/turnover subset is persisted here.
    company=Company(owner_user_id=owner_id,inn=source['inn'],entity_type='LLC' if len(source['inn'])==10 else 'IP',name=source.get('name'),registered_at=date.fromisoformat(source['registered_at']) if source.get('registered_at') else None,registry_status=source['registry_status'],okved=source.get('okved'),region=source.get('region'),msp_registry=source.get('msp_registry'),legal_address=source.get('legal_address'),fixture_id=source['fixture_id'],business_reference_date=date.fromisoformat(FIXTURES['business_reference_date']) if seeded else now.date(),authority_verification_id=verification.id,version=1,created_at=now,updated_at=now)
    if seeded: company.id=source['id']
    db.add(company)
    db.flush()
    append_precheck(db,company,source,now)
    for code in ('ONBOARDING_PROCESSING','REGISTRY_LOOKUP'):
        db.add(Consent(user_id=owner_id,company_id=company.id,code=code,text_version=CONSENT_VERSION,granted_at=now))
    return company

@router.get('/consents/documents')
def consent_documents(stage: Literal['onboarding','application']):
    codes=('ONBOARDING_PROCESSING','REGISTRY_LOOKUP') if stage=='onboarding' else ('APPLICATION_PROCESSING','BKI')
    return {'items':[{'code':c,'version':CONSENT_VERSION,'text':CONSENT_TEXTS[c]} for c in codes]}

@router.get('/demo/fixtures')
def demo_fixtures(user: ClientUser):
    if not settings.demo_mode: raise ApiError(404,'NOT_FOUND','Страница не найдена')
    return {'items':[{'fixture_id':s['fixture_id'],'inn':s['inn'],'name':s['name'],'entity_type':s['entity_type'],'registry_status':s['registry_status'],'registry_source_status':s['registry_source_status'],'turnover_source_status':s['turnover_source_status']} for s in SOURCES.values()], 'total':len(SOURCES)}

@router.get('/companies')
def list_companies(user: ClientUser, db: Db):
    rows=db.scalars(select(Company).where(Company.owner_user_id==user.id).order_by(Company.created_at,Company.id)).all()
    return {'items':[public_row(c) for c in rows],'total':len(rows)}

@router.post('/companies',status_code=201)
def onboard(data: CompanyInput, user: ClientUser, db: Db, now: Now):
    """A whitelisted ИНН (422 REGISTRY_NOT_FOUND), then the Госуслуги gate (403 AUTHORITY_NOT_VERIFIED: the user's own,
    unused, unexpired verification of this ИНН), then one company per owner and ИНН (409 COMPANY_EXISTS). Any refusal
    rolls back, so a verification is spent only by the company it adds."""
    source=registry_source(data.inn)
    verification=authority.consume(db,user.id,data.inn,data.authority_verification_id,now)
    if db.scalar(select(Company).where(Company.owner_user_id==user.id,Company.inn==data.inn)):
        raise ApiError(409,'COMPANY_EXISTS','Компания уже добавлена. Выберите её в списке.')
    company=create_company(db,user.id,source,now,verification=verification)
    return company_result(db,company)

@router.get('/companies/{company_id}')
@router.get('/companies/{company_id}/precheck')
def read_company(company_id: str, user: ClientUser, db: Db):
    return company_result(db,get_owned_company(db,company_id,user.id))

def recover_precheck(db: Session, company: Company, now: datetime) -> Precheck:
    """One registry/turnover recovery lookup: the fixture's `recovery` block replaces the unavailable or missing
    source values, a new precheck is appended and the company version increments once. The caller holds the company
    row lock. Shared by the company precheck retry and an application's retry-check."""
    source=dict(SOURCES[company.inn])
    recovery=source.get('recovery',{})
    if recovery.get('retry_registry_source_status'):
        source['registry_source_status']=recovery['retry_registry_source_status']
        source['registry_status']=recovery['retry_registry_status']
        if 'retry_msp_registry' in recovery:
            source['msp_registry']=recovery['retry_msp_registry']
    if recovery.get('monthly_revenue_rub') is not None:
        source['monthly_revenue_rub']=recovery['monthly_revenue_rub']
        source['previous_monthly_revenue_rub']=recovery.get('previous_monthly_revenue_rub')
        source['turnover_source_status']='available'
    company.registry_status=source['registry_status']
    company.msp_registry=source.get('msp_registry')
    company.version+=1
    company.updated_at=now
    return append_precheck(db,company,source,now)

@router.post('/companies/{company_id}/precheck/retry')
def retry_precheck(company_id: str, data: VersionInput, request: Request, user: ClientUser, db: Db, now: Now, idempotency_key: IdempotencyKey):
    company=get_owned_company(db,company_id,user.id,for_update=True)
    scope=idempotency.scope_of(request,user.id,idempotency_key,data)
    replayed=idempotency.replay(db,scope)
    if replayed is not None: return replayed
    if data.version != company.version: raise ApiError(409,'VERSION_CONFLICT','Компания уже обновлена. Обновите страницу.')
    recover_precheck(db,company,now)
    return idempotency.remember(db,scope,company_result(db,company),now=now,resource_id=company.id)
