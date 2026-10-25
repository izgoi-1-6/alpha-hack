"""Customer-facing serialization of applications, the dialog, evaluations, info requests and history.

Staff-only data stays out: assignee, score factors, source payloads and input snapshots, consents, officer ids.
Task 5 adds a staff serializer beside `public_application` that adds those (spec: "Staff detail additionally returns
source snapshots, factors, decisions, claim owner and documents").
"""
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..clock import iso_utc
from ..companies import latest_precheck
from ..errors import ApiError
from ..models import Company
from . import stages
from .info_requests import open_info_request
from .lifecycle import CANCELLABLE
from .models import TERMINAL_STATUSES, Application, Evaluation, InfoRequest, Notification, StatusHistory
from .products import application_product

APPLICATION_FIELDS = ('id', 'company_id', 'product_id', 'recommendation_snapshot_id', 'status', 'current_stage', 'version',
                      'answers', 'submitted_at', 'requested_amount_rub', 'indicative_limit_rub', 'scored_limit_rub',
                      'preapproved_amount_rub', 'final_amount_rub', 'preapproved_at', 'preapproval_expires_at',
                      'catalog_version', 'rules_version', 'created_at', 'updated_at')
PRODUCT_FIELDS = ('id', 'name', 'instrument_type', 'amount_min_rub', 'amount_max_rub', 'term_min_months', 'term_max_months',
                  'annual_rate_bps', 'rate_is_demo', 'collateral_required', 'collateral_ltv_bps', 'required_documents')


def plain(value):
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def company_summary(company: Company) -> dict:
    return {'id': company.id, 'name': company.name, 'inn': company.inn, 'entity_type': company.entity_type,
            'registry_status': company.registry_status}


def product_summary(application: Application, product: dict | None) -> dict:
    return {key: product[key] for key in PRODUCT_FIELDS} if product else {'id': application.product_id}


def allowed_actions(application: Application, company: Company, request: InfoRequest | None) -> list[str]:
    """Commands the client can run now. A known-inactive draft omits submit: the UI must not offer it, although a
    direct submit still meets the defensive R2 check."""
    status, actions = application.status, []
    if status == 'DRAFT':
        actions.append('edit_answers')
        if company.registry_status != 'inactive':
            actions.append('submit')
    if status == 'WAIT_EXTERNAL' or (status == 'NEED_INFO' and request is not None and request.kind == 'trusted_source'):
        actions.append('retry_check')
    if status in CANCELLABLE:
        actions.append('cancel')
    return actions


def blocking_issues(application: Application, company: Company, product: dict | None) -> dict:
    if product is None:
        return {'product_id': 'Продукт больше не доступен: пересчитайте оценку.'}
    return stages.issues(application.answers, product, company.entity_type)


def missing_fields(application: Application, company: Company, product: dict | None, request: InfoRequest | None) -> list[str]:
    """What the client must still supply: a draft's submit blockers, or a client_answers request's fields."""
    if application.status == 'DRAFT':
        return list(blocking_issues(application, company, product))
    if application.status == 'NEED_INFO' and request is not None and request.kind == 'client_answers':
        return list(request.requested_fields)
    return []


def public_evaluation(row: Evaluation | None) -> dict | None:
    if row is None:
        return None
    return {'id': row.id, 'rule': row.rule, 'outcome': row.outcome, 'score': row.score, 'risk': row.risk,
            'scored_limit_rub': row.scored_limit_rub, 'reasons': list(row.reasons), 'created_at': iso_utc(row.created_at)}


def public_info_request(row: InfoRequest | None) -> dict | None:
    if row is None:
        return None
    return {'id': row.id, 'kind': row.kind, 'source': row.source, 'requested_fields': list(row.requested_fields),
            'question': row.question, 'requested_by': 'system' if row.officer_id is None else 'officer',
            'response': row.response, 'responded_at': plain(row.responded_at), 'resolved_at': plain(row.resolved_at),
            'created_at': iso_utc(row.created_at)}


def latest_evaluation(db: Session, application_id: str) -> Evaluation | None:
    return db.scalar(select(Evaluation).where(Evaluation.application_id == application_id)
                     .order_by(Evaluation.sequence.desc()).limit(1))


def current_request(db: Session, application: Application) -> InfoRequest | None:
    """The open request while the application is still in progress (a terminal application has nothing to answer)."""
    return None if application.status in TERMINAL_STATUSES else open_info_request(db, application.id)


def public_application(db: Session, application: Application, company: Company | None = None) -> dict:
    company = company or db.get(Company, application.company_id)
    product = application_product(application)
    request = current_request(db, application)
    body = {name: plain(getattr(application, name)) for name in APPLICATION_FIELDS}
    body.update(company=company_summary(company), product=product_summary(application, product),
                latest_evaluation=public_evaluation(latest_evaluation(db, application.id)),
                allowed_actions=allowed_actions(application, company, request),
                missing_fields=missing_fields(application, company, product, request),
                open_info_request=public_info_request(request), document_summary=None)
    return body


def dialog(db: Session, application: Application) -> dict:
    """The six-stage contract: field descriptors with product bounds and stage-3 source tags, completion flags,
    current answers and what still blocks submission."""
    company = db.get(Company, application.company_id)
    product = application_product(application)
    if product is None:
        raise ApiError(409, 'RECOMMENDATION_STALE', 'Условия продукта изменились. Пересчитайте оценку и создайте новую заявку.')
    request = current_request(db, application)
    blocking = blocking_issues(application, company, product)
    return {'application_id': application.id, 'status': application.status, 'version': application.version,
            'current_stage': application.current_stage, 'steps_total': len(stages.STAGES),
            'company': company_summary(company), 'product': product_summary(application, product),
            'stages': stages.stage_contract(application.answers, product, latest_precheck(db, company.id), blocking),
            'answers': application.answers, 'missing_fields': missing_fields(application, company, product, request),
            'field_issues': blocking if application.status == 'DRAFT' else {},
            'allowed_actions': allowed_actions(application, company, request)}


def public_history(db: Session, application: Application) -> list[dict]:
    rows = db.execute(select(StatusHistory, Notification)
                      .outerjoin(Notification, Notification.status_history_id == StatusHistory.id)
                      .where(StatusHistory.application_id == application.id).order_by(StatusHistory.sequence)).all()
    return [{'id': entry.id, 'application_id': entry.application_id, 'from_status': entry.from_status,
             'to_status': entry.to_status, 'actor_id': entry.actor_id, 'reason_code': entry.reason_code,
             'reason_text': entry.reason_text, 'application_version': entry.application_version,
             'created_at': iso_utc(entry.created_at),
             'notification': None if note is None else {'event_code': note.event_code, 'channel': note.channel,
                                                        'message': note.message, 'simulated': True,
                                                        'created_at': iso_utc(note.created_at)}}
            for entry, note in rows]
