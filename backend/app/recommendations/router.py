from fastapi import APIRouter
from sqlalchemy import select
from ..clock import iso_utc
from ..companies import get_owned_company, latest_precheck, public_row
from ..errors import ApiError
from ..identity import ClientUser, Db, Now
from . import catalog
from .models import RecommendationSnapshot
from .schemas import NeedInput
from .service import recommend

router=APIRouter(tags=['recommendations'])

def public_snapshot(row: RecommendationSnapshot) -> dict:
    return {'snapshot_id':row.id,'catalog_version':row.catalog_version,'rules_version':row.rules_version,
            'items':row.result,'created_at':iso_utc(row.created_at)}

@router.get('/catalog')
def read_catalog():
    return catalog.public_catalog()

@router.post('/companies/{company_id}/recommendations',status_code=201)
def create_recommendation(company_id: str, data: NeedInput, user: ClientUser, db: Db, now: Now):
    # Serializes source selection against retry, keeping company and precheck coherent.
    company=get_owned_company(db,company_id,user.id,for_update=True)
    precheck=latest_precheck(db,company_id)
    need=data.model_dump()
    source={'company':public_row(company),'precheck':public_row(precheck)}
    config=catalog.config()
    result=recommend(source['company'],source['precheck'],need,config)
    row=RecommendationSnapshot(company_id=company_id,precheck_id=precheck.id,need=need,input_snapshot=source,
                               result=result,catalog_version=config.catalog_version,rules_version=config.rules_version,created_at=now)
    db.add(row)
    db.flush()
    return public_snapshot(row)

@router.get('/companies/{company_id}/recommendations/{snapshot_id}')
def read_recommendation(company_id: str, snapshot_id: str, user: ClientUser, db: Db):
    get_owned_company(db,company_id,user.id)
    row=db.scalar(select(RecommendationSnapshot).where(RecommendationSnapshot.id==snapshot_id,RecommendationSnapshot.company_id==company_id))
    if not row: raise ApiError(404,'RECOMMENDATION_NOT_FOUND','Сохранённая оценка не найдена')
    return public_snapshot(row)
