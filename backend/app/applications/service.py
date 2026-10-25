"""Customer application commands (create, save answers, submit, retry-check, respond-info, cancel). Each runs on rows
the router has already locked (company first, then application) and after the idempotency replay check; any ApiError
rolls the whole command back.

Submit validates in the spec's order: version, draft, current policy, one active application per company/product,
R1 corrections (the company's current eligibility included), explicit current consents, R3 required answers (skipped
for a known inactive company, which the check rejects through R2). Only then are the consents granted, the inputs and
the decision facts (products.pin: the runtime product, `secured`, `required_documents`) pinned and DRAFT→CHECKING
recorded before the check runs. Retry-check and respond-info decide under the pinned facts.
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
from .checks import recheck_after_response, run_check
from .info_requests import NEED_FIELDS, NEED_FIELDS_MESSAGE, answered_paths, open_info_request, unanswered, unrequested
from .lifecycle import ApplicationChange, expire_if_due, record_creation
from .models import ACTIVE_STATUSES, Application
from .products import current_product, is_current, pin, pinned_terms, terms_for
from .schemas import AnswersPatch, CancelInput, CreateInput, RespondInput, SubmissionConsent, SubmitInput

SUBMISSION_CONSENTS = ('APPLICATION_PROCESSING', 'BKI')
RESPONSE_NOTICE = 'Ответ на запрос получен. Заявка вернулась на рассмотрение кредитному специалисту.'


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
    if item is None:  # overlays and unknown ids never appear in a snapshot
        raise ApiError(422, 'PRODUCT_NOT_SUPPORTED', 'Заявку можно оформить только на продукт из сохранённой оценки.',
                       fields={'product_id': 'Выберите продукт из сохранённой оценки'})
    product = current_product(data.product_id)
    if product is None or not is_current(snapshot.catalog_version, snapshot.rules_version):
        raise stale()
    application = Application(company_id=company.id, product_id=product['id'], recommendation_snapshot_id=snapshot.id,
                              status='DRAFT', answers=stages.prefill(snapshot.need, latest_precheck(db, company.id), product),
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
    corrections = stages.corrections(answers, product, public_row(company))
    if corrections:
        raise ApiError(422, 'CORRECTION_REQUIRED', 'Измените параметры заявки под условия продукта.', fields=corrections)
    if not consents_given(data.consents):
        raise ApiError(422, 'NEED_INFO', 'Отметьте оба согласия текущей версии: на обработку данных заявки и на запрос в БКИ.',
                       fields={'consents': 'Нужны согласия APPLICATION_PROCESSING и BKI версии demo-consent-v1'})
    terms = terms_for(product, answers.get('collateral'))
    if company.registry_status != 'inactive':
        gaps = stages.missing(answers, product, terms.secured)
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
    # A fresh upper estimate replaces the snapshot's older figure (source revenue, else the declared answer).
    application.indicative_limit_rub = scoring.indicative_limit(product, revenue, terms.secured, answers.get('collateral'))
    application.submitted_input_snapshot = {
        'submitted_at': iso_utc(now), 'recommendation_snapshot_id': application.recommendation_snapshot_id,
        'catalog_version': application.catalog_version, 'rules_version': application.rules_version, **pin(terms),
        'company': public_row(company), 'precheck': public_row(precheck), 'answers': dict(answers),
        'consents': [{'id': grant.id, 'code': grant.code, 'text_version': grant.text_version,
                      'granted_at': iso_utc(grant.granted_at)} for grant in grants]}
    change = ApplicationChange(db, application, actor_id=user_id, now=now)
    change.move('CHECKING', reason_code='SUBMITTED',
                reason_text='Анкета отправлена на проверку с согласиями на обработку данных и запрос в БКИ.')
    run_check(db, change, company, terms)


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
    run_check(db, change, company, pinned_terms(application))


def cancel_application(db: Session, application: Application, user_id: str, data: CancelInput, now: datetime) -> None:
    require_version(application, data.version)
    ApplicationChange(db, application, actor_id=user_id, now=now).move(
        'CANCELLED', reason_code='CANCELLED_BY_CLIENT', reason_text=data.reason)


def respond_info(db: Session, application: Application, company: Company, user_id: str, data: RespondInput, now: datetime) -> None:
    """NEED_INFO with an open client_answers request (an officer's or the system's): the owner sets exactly the
    requested answer paths, never a need field (purpose, amount, term: fixed since submission, so the request is never
    rewritten), validated like questionnaire saves and then against the R3 requirements of the pinned terms (a pinned
    secured application keeps its pledge; an answer never makes an application secured). The request records the
    response and is resolved, and `recheck_after_response` scores the revised answers under the pinned terms with the
    stored source evidence (no BKI request) and returns the application to MANUAL_REVIEW with its assignee. The
    submission snapshot and earlier evaluations are never changed."""
    require_version(application, data.version)
    request = open_info_request(db, application.id)
    if application.status != 'NEED_INFO' or request is None:
        raise ApiError(409, 'INVALID_STATUS', 'Ответить можно, когда по заявке запрошены сведения.')
    if request.kind == 'trusted_source':
        raise ApiError(409, 'TRUSTED_SOURCE_REQUIRED', 'Эти сведения приходят только из демо-источника, анкета их не принимает. '
                                                       'Нажмите «Повторить проверку».')
    patch = data.answers.model_dump(mode='json', exclude_unset=True)
    locked = [name for name in patch if name in NEED_FIELDS]
    if locked:  # whatever the request's origin: a system request built from missing answers may name one
        raise ApiError(422, 'NEED_FIELDS_LOCKED', NEED_FIELDS_MESSAGE, fields={name: NEED_FIELDS_MESSAGE for name in locked})
    paths = answered_paths(patch)
    extra = unrequested(request.requested_fields, paths)
    if extra:
        raise ApiError(422, 'ANSWER_NOT_REQUESTED', 'Ответьте только на запрошенные поля.',
                       fields={path: 'Это поле не запрашивалось' for path in extra})
    gaps = unanswered(request.requested_fields, paths)
    if gaps:
        raise ApiError(422, 'NEED_INFO', 'Ответьте на все запрошенные поля.', fields={path: 'Укажите значение' for path in gaps})
    answers = stages.merge(application.answers, patch)
    terms = pinned_terms(application)
    gaps = stages.missing(answers, terms.product, terms.secured)
    if gaps:
        raise ApiError(422, 'NEED_INFO', 'Заполните обязательные поля анкеты.', fields=gaps)
    application.answers = answers
    request.response, request.responded_at, request.resolved_at = data.response, now, now
    recheck_after_response(db, ApplicationChange(db, application, actor_id=user_id, now=now), company, terms,
                           reason_text=data.response, notification=RESPONSE_NOTICE)
