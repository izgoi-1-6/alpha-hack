from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal
from fastapi import APIRouter, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .clock import iso_utc
from .config import settings
from .errors import ApiError
from .identity import Db, Now, ClientUser
from .models import Company, Precheck, Consent, IdempotencyRecord
from .schemas import CompanyInput, VersionInput

DATA_PATH = Path(__file__).resolve().parents[2] / 'data' / 'demo-companies.json'
FIXTURES = json.loads(DATA_PATH.read_text())
SOURCES = {c['inn']:c for c in FIXTURES['companies']}
CONSENT_VERSION='demo-consent-v1'
CONSENT_TEXTS={
    'ONBOARDING_PROCESSING':'Согласен на обработку синтетических данных компании для демонстрационного подбора финансирования.',
    'REGISTRY_LOOKUP':'Разрешаю запрос синтетических сведений о компании и оборотах в локальных имитаторах реестра и банка.',
    'APPLICATION_PROCESSING':'Согласен на обработку синтетических данных для демонстрационного рассмотрения заявки.',
    'BKI':'Разрешаю демонстрационный запрос кредитной истории в локальном имитаторе БКИ после отправки заявки.',
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
    registry={k:source.get(k) for k in ('name','registered_at','registry_status','okved','region','legal_address')}
    turnover={k:source.get(k) for k in ('monthly_revenue_rub','previous_monthly_revenue_rub','financial_period_end')}
    row=Precheck(company_id=company.id,company_version=company.version,registry_source_status=source['registry_source_status'],turnover_source_status=source['turnover_source_status'],registry_payload=registry,turnover_payload=turnover,monthly_revenue_rub=source.get('monthly_revenue_rub'),previous_monthly_revenue_rub=source.get('previous_monthly_revenue_rub'),financial_period_end=date.fromisoformat(source['financial_period_end']) if source.get('financial_period_end') else None,source_version=FIXTURES['fixture_version'],checked_at=now,synthetic=True)
    db.add(row)
    db.flush()
    return row

def create_company(db: Session, owner_id: str, source: dict, now: datetime, *, seeded: bool=False) -> Company:
    # Data whitelist contains BKI oracle values; only the explicit registry/turnover subset is persisted here.
    company=Company(owner_user_id=owner_id,inn=source['inn'],entity_type='LLC' if len(source['inn'])==10 else 'IP',name=source.get('name'),registered_at=date.fromisoformat(source['registered_at']) if source.get('registered_at') else None,registry_status=source['registry_status'],okved=source.get('okved'),region=source.get('region'),legal_address=source.get('legal_address'),fixture_id=source['fixture_id'],business_reference_date=date.fromisoformat(FIXTURES['business_reference_date']) if seeded else now.date(),version=1,created_at=now,updated_at=now)
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
    if db.scalar(select(Company).where(Company.owner_user_id==user.id,Company.inn==data.inn)):
        raise ApiError(409,'COMPANY_EXISTS','Компания уже добавлена. Выберите её в списке.')
    source=SOURCES.get(data.inn)
    if not source: raise ApiError(422,'REGISTRY_NOT_FOUND','Компания не найдена в демо-реестре. Проверьте ИНН или выберите демо-профиль.',fields={'inn':'Выберите ИНН из демо-профилей'})
    company=create_company(db,user.id,source,now)
    return company_result(db,company)

@router.get('/companies/{company_id}')
@router.get('/companies/{company_id}/precheck')
def read_company(company_id: str, user: ClientUser, db: Db):
    return company_result(db,get_owned_company(db,company_id,user.id))

@router.post('/companies/{company_id}/precheck/retry')
def retry_precheck(company_id: str, data: VersionInput, request: Request, user: ClientUser, db: Db, now: Now, idempotency_key: Annotated[str,Header(min_length=1,max_length=128)]):
    company=get_owned_company(db,company_id,user.id,for_update=True)
    digest=hashlib.sha256(json.dumps(data.model_dump(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    previous=db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id==user.id,IdempotencyRecord.method=='POST',IdempotencyRecord.path==request.url.path,IdempotencyRecord.key==idempotency_key))
    if previous:
        if previous.request_hash != digest: raise ApiError(409,'IDEMPOTENCY_CONFLICT','Ключ уже использован с другими данными')
        return previous.response_body
    if data.version != company.version: raise ApiError(409,'VERSION_CONFLICT','Компания уже обновлена. Обновите страницу.')
    source=dict(SOURCES[company.inn])
    recovery=source.get('recovery',{})
    if recovery.get('retry_registry_source_status'):
        source['registry_source_status']=recovery['retry_registry_source_status']
        source['registry_status']=recovery['retry_registry_status']
    if recovery.get('monthly_revenue_rub') is not None:
        source['monthly_revenue_rub']=recovery['monthly_revenue_rub']
        source['previous_monthly_revenue_rub']=recovery.get('previous_monthly_revenue_rub')
        source['turnover_source_status']='available'
    company.registry_status=source['registry_status']
    company.version+=1
    company.updated_at=now
    append_precheck(db,company,source,now)
    result=company_result(db,company)
    db.add(IdempotencyRecord(actor_id=user.id,method='POST',path=request.url.path,key=idempotency_key,request_hash=digest,response_status=200,response_body=result,resource_id=company.id,created_at=now))
    db.flush()
    return result
