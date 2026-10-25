"""Customer application commands. Each runs on rows the router has already locked (company first, then application)
and after the idempotency replay check; any ApiError rolls the whole command back.

Submit validates in the spec's order: version, draft, current policy, one active application per company/product,
R1 corrections, explicit current consents, R3 required answers (skipped for a known inactive company, which the check
rejects through R2). Only then are the consents granted, the inputs pinned and DRAFT→CHECKING recorded before the
check runs.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..clock import iso_utc
from ..companies import CONSENT_VERSION, latest_precheck, public_row, recover_precheck
from ..errors import ApiError
from ..models import Company, Consent
from ..recommendations.models import RecommendationSnapshot
from . import scoring, stages
from .checks import run_check
from .info_requests import open_info_request
from .lifecycle import ApplicationChange, expire_if_due, record_creation
from .models import ACTIVE_STATUSES, Application
from .products import current_product, is_current
from .schemas import AnswersPatch, CancelInput, CreateInput, SubmissionConsent, SubmitInput

SUBMISSION_CONSENTS = ('APPLICATION_PROCESSING', 'BKI')


def stale() -> ApiError:
    return ApiError(409, 'RECOMMENDATION_STALE', 'Условия продуктов изменились. Пересчитайте оценку и выберите продукт заново.')


def require_version(application: Application, version: int) -> None:
    if version != application.version:
        raise ApiError(409, 'VERSION_CONFLICT', 'Заявка уже изменилась. Обновите страницу.')


def require_draft(application: Application) -> None:
    if application.status != 'DRAFT':
        raise ApiError(409, 'INVALID_STATUS', 'Анкету можно менять и отправлять только в черновике.')


def create_application(db: Session, company: Company, user_id: str, data: CreateInput, now: datetime) -> Application:
    """A DRAFT from an owned saved snapshot: the product must be one of the snapshot's (supported) items and the
    snapshot's catalog/rules versions must be current. can_apply is a UI gate; submission enforces R1-R4."""
    snapshot = db.scalar(select(RecommendationSnapshot).where(RecommendationSnapshot.id == data.recommendation_snapshot_id,
                                                              RecommendationSnapshot.company_id == company.id))
    if snapshot is None:
        raise ApiError(404, 'RECOMMENDATION_NOT_FOUND', 'Сохранённая оценка не найдена')
    item = next((entry for entry in snapshot.result if entry['product_id'] == data.product_id), None)
    if item is None:  # research archive and unknown ids never appear in a snapshot
        raise ApiError(422, 'PRODUCT_NOT_SUPPORTED', 'Заявку можно оформить только на демо-продукт из сохранённой оценки.',
                       fields={'product_id': 'Выберите один из трёх демо-продуктов оценки'})
    product = current_product(data.product_id)
    if product is None or not is_current(snapshot.catalog_version, snapshot.rules_version):
        raise stale()
    application = Application(company_id=company.id, product_id=product['id'], recommendation_snapshot_id=snapshot.id,
                              status='DRAFT', answers=stages.prefill(snapshot.need, latest_precheck(db, company.id)),
                              current_stage=1, version=1, requested_amount_rub=snapshot.need['requested_amount_rub'],
                              indicative_limit_rub=item['indicative_limit_rub'], catalog_version=snapshot.catalog_version,
                              rules_version=snapshot.rules_version, created_at=now, updated_at=now)
    db.add(application)
    db.flush()
    record_creation(db, application, actor_id=user_id, now=now)
    return application


def save_answers(db: Session, application: Application, user_id: str, data: AnswersPatch, now: datetime) -> None:
    """A partial save of whitelisted answers (deep-merged) and the stage pointer; a same-state edit."""
    require_version(application, data.version)
    require_draft(application)
    patch = data.answers.model_dump(mode='json', exclude_unset=True)
    application.answers = stages.merge(application.answers, patch)
    application.current_stage = data.current_stage
    if 'requested_amount_rub' in patch:
        application.requested_amount_rub = patch['requested_amount_rub']
    ApplicationChange(db, application, actor_id=user_id, now=now).touch()


def reject_duplicate_active(db: Session, application: Application, now: datetime) -> None:
    """One active submitted application per company and product. Lazy expiry runs first, so an approval that has just
    expired no longer blocks. The company row lock serializes racing submissions; the partial unique index backs it."""
    others = db.scalars(select(Application).where(
        Application.company_id == application.company_id, Application.product_id == application.product_id,
        Application.id != application.id, Application.status.in_(ACTIVE_STATUSES)).order_by(Application.id).with_for_update()).all()
    for other in others:
        expire_if_due(db, other, now)
    active = next((other for other in others if other.status in ACTIVE_STATUSES), None)
    if active is not None:
        raise ApiError(409, 'DUPLICATE_ACTIVE_APPLICATION', 'По этому продукту у компании уже есть заявка в работе.',
                       details={'application_id': active.id})


def consents_given(consents: list[SubmissionConsent]) -> bool:
    """Exactly APPLICATION_PROCESSING and BKI, current text version, explicitly accepted."""
    return (sorted(consent.code for consent in consents) == sorted(SUBMISSION_CONSENTS)
            and all(consent.version == CONSENT_VERSION and consent.accepted for consent in consents))


def submit_application(db: Session, application: Application, company: Company, user_id: str, data: SubmitInput, now: datetime) -> None:
    require_version(application, data.version)
    require_draft(application)
    product = current_product(application.product_id)
    if product is None or not is_current(application.catalog_version, application.rules_version):
        raise stale()
    reject_duplicate_active(db, application, now)
    answers = application.answers
    corrections = stages.corrections(answers, product, company.entity_type)
    if corrections:
        raise ApiError(422, 'CORRECTION_REQUIRED', 'Измените параметры заявки под условия продукта.', fields=corrections)
    if not consents_given(data.consents):
        raise ApiError(422, 'NEED_INFO', 'Отметьте оба согласия текущей версии: на обработку данных заявки и на запрос в БКИ.',
                       fields={'consents': 'Нужны согласия APPLICATION_PROCESSING и BKI версии demo-consent-v1'})
    if company.registry_status != 'inactive':
        gaps = stages.missing(answers, product)
        if gaps:
            raise ApiError(422, 'NEED_INFO', 'Заполните обязательные поля анкеты.', fields=gaps)
    grants = [Consent(user_id=user_id, company_id=company.id, application_id=application.id, code=code,
                      text_version=CONSENT_VERSION, granted_at=now) for code in SUBMISSION_CONSENTS]
    db.add_all(grants)
    db.flush()
    precheck = latest_precheck(db, company.id)
    revenue = stages.finance_evidence(answers, precheck)['monthly_revenue_rub']['value']
    application.submitted_at = now
    application.requested_amount_rub = answers.get('requested_amount_rub')
    # Fresh upper estimate on current sources (the low-risk formula), replacing the snapshot's older figure.
    application.indicative_limit_rub = scoring.scored_limit(product, 'low', revenue, answers.get('collateral'))
    application.submitted_input_snapshot = {
        'submitted_at': iso_utc(now), 'recommendation_snapshot_id': application.recommendation_snapshot_id,
        'catalog_version': application.catalog_version, 'rules_version': application.rules_version, 'product': product,
        'company': public_row(company), 'precheck': public_row(precheck), 'answers': dict(answers),
        'consents': [{'id': grant.id, 'code': grant.code, 'text_version': grant.text_version,
                      'granted_at': iso_utc(grant.granted_at)} for grant in grants]}
    change = ApplicationChange(db, application, actor_id=user_id, now=now)
    change.move('CHECKING', reason_code='SUBMITTED',
                reason_text='Анкета отправлена на проверку с согласиями на обработку данных и запрос в БКИ.')
    run_check(db, change, company, product)


def has_bki_consent(db: Session, application: Application) -> bool:
    return db.scalar(select(Consent.id).where(Consent.application_id == application.id, Consent.code == 'BKI',
                                              Consent.text_version == CONSENT_VERSION).limit(1)) is not None


def retry_check(db: Session, application: Application, company: Company, user_id: str, version: int, now: datetime) -> None:
    """WAIT_EXTERNAL, or NEED_INFO with an open trusted_source request: CHECKING, one recovery lookup when the latest
    precheck has an unavailable registry/turnover source (the company retry path), then the check under the policy
    pinned at submission, using the stored submission BKI consent."""
    require_version(application, version)
    request = open_info_request(db, application.id)
    trusted_gap = application.status == 'NEED_INFO' and request is not None and request.kind == 'trusted_source'
    if application.status != 'WAIT_EXTERNAL' and not trusted_gap:
        raise ApiError(409, 'INVALID_STATUS', 'Повторная проверка доступна, когда заявка ждёт демо-источник.')
    if not has_bki_consent(db, application):
        raise ApiError(409, 'CONSENT_REQUIRED', 'По заявке нет сохранённого согласия на запрос в БКИ.')
    change = ApplicationChange(db, application, actor_id=user_id, now=now)
    change.move('CHECKING', reason_code='RETRY_CHECK', reason_text='Повторная проверка демо-источников по запросу клиента.')
    precheck = latest_precheck(db, company.id)
    if 'unavailable' in (precheck.registry_source_status, precheck.turnover_source_status):
        recover_precheck(db, company, now)
    run_check(db, change, company, application.submitted_input_snapshot['product'])


def cancel_application(db: Session, application: Application, user_id: str, data: CancelInput, now: datetime) -> None:
    require_version(application, data.version)
    ApplicationChange(db, application, actor_id=user_id, now=now).move(
        'CANCELLED', reason_code='CANCELLED_BY_CLIENT', reason_text=data.reason)
