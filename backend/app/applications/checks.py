"""One submitted check: reads the persisted company/source state and the frozen answers, calls the BKI simulator at
most once, stores an immutable Evaluation with its source evidence, opens or closes system InfoRequests and moves the
application to the outcome through the transition service.

Submission and retry-check run it on a CHECKING application while the command holds the company and application row
locks; registry/turnover mocks are never called here (the latest persisted precheck is read). An information response
runs `recheck_after_response` instead, which reuses the latest complete BKI report and calls no simulator.
"""
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..clock import iso_utc
from ..companies import latest_precheck
from ..models import Company, Precheck
from . import bki, scoring, stages
from .info_requests import create_info_request, open_info_request
from .lifecycle import PREAPPROVAL_TTL, ApplicationChange, preapproval_notice
from .models import Application, Evaluation
from .products import Terms

SCORED_ANSWERS = ('purpose', 'requested_amount_rub', 'term_months', 'collateral', 'monthly_debt_payment_rub', 'tax_debt_rub',
                  'legal_proceedings')


def iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def check_input(application: Application, company: Company, precheck: Precheck, terms: Terms) -> scoring.CheckInput:
    """The terms are the ones pinned at submission. Business age counts completed months from registration to the
    company's business reference date (the fixture date for seeded companies, the onboarding date otherwise)."""
    registered, reference = company.registered_at, company.business_reference_date
    return scoring.CheckInput(
        product=terms.product, secured=terms.secured, registry_status=company.registry_status,
        registry_source_status=precheck.registry_source_status, turnover_source_status=precheck.turnover_source_status,
        age_months=scoring.completed_months(registered, reference) if registered and reference else None,
        finance=stages.finance_evidence(application.answers, precheck), answers=application.answers,
        missing_answers=tuple(stages.missing(application.answers, terms.product, terms.secured)))


def bki_attempts(db: Session, application_id: str) -> int:
    """BKI requests already made for the application: the highest attempt recorded in its persisted evaluations
    (survives restarts; an evaluation that reuses an earlier report repeats that report's attempt)."""
    return max((sources['bki']['attempt'] for sources in
                db.scalars(select(Evaluation.sources).where(Evaluation.application_id == application_id))
                if sources.get('bki')), default=0)


def complete_report(report: dict | None) -> bool:
    return report is not None and report['status'] != 'unavailable' and all(
        report.get(category) is not None for category in scoring.BKI_CATEGORIES)


def outcome_notification(decision: scoring.Decision, application: Application) -> str | None:
    if decision.outcome == 'PREAPPROVED':
        return preapproval_notice(application)
    if decision.outcome == 'REJECTED':
        return 'По заявке принят отказ. ' + decision.reasons[0]
    if decision.outcome in ('WAIT_EXTERNAL', 'NEED_INFO'):
        return decision.reasons[0]
    return None


def record_evaluation(db: Session, application: Application, company: Company, precheck: Precheck,
                      check: scoring.CheckInput, decision: scoring.Decision, bki_payload: dict | None, *, now,
                      trusted_review: bool, client_response: bool = False) -> Evaluation:
    """Stores one immutable Evaluation: what was scored (input snapshot with the product and secured flag, finance
    evidence, scored answers, age, review flags) and the source evidence it used (precheck registry/turnover, the BKI
    payload)."""
    sequence = (db.scalar(select(func.max(Evaluation.sequence)).where(Evaluation.application_id == application.id)) or 0) + 1
    evaluation = Evaluation(
        application_id=application.id, sequence=sequence, score=decision.score, risk=decision.risk, factors=decision.factors,
        rule=decision.rule, scored_limit_rub=decision.scored_limit_rub, outcome=decision.outcome,
        reasons=list(decision.reasons), created_at=now,
        input_snapshot={
            'trusted_source_review': trusted_review, 'client_response': client_response, 'product_id': check.product['id'],
            'secured': check.secured,
            'catalog_version': application.catalog_version, 'rules_version': application.rules_version,
            'company': {'registry_status': company.registry_status, 'entity_type': company.entity_type,
                        'registered_at': iso_date(company.registered_at),
                        'business_reference_date': iso_date(company.business_reference_date)},
            'age_months': check.age_months, 'finance': check.finance,
            'answers': {name: application.answers.get(name) for name in SCORED_ANSWERS},
            'missing_answers': list(check.missing_answers), 'review_flags': list(decision.flags)},
        sources={
            'registry': {'precheck_id': precheck.id, 'source_status': precheck.registry_source_status,
                         'registry_status': company.registry_status, 'checked_at': iso_utc(precheck.checked_at)},
            'turnover': {'precheck_id': precheck.id, 'source_status': precheck.turnover_source_status, **stages.source_finance(precheck)},
            'bki': bki_payload})
    db.add(evaluation)
    db.flush()
    return evaluation


def run_check(db: Session, change: ApplicationChange, company: Company, terms: Terms) -> Evaluation:
    application, now = change.application, change.now
    precheck = latest_precheck(db, company.id)
    check = check_input(application, company, precheck, terms)
    request = open_info_request(db, application.id)
    trusted_review = request is not None and request.kind == 'trusted_source'
    decision = scoring.before_bki(check)
    report = None
    if decision is None:
        report = bki.request_report(company.inn, bki_attempts(db, application.id) + 1)
        decision = scoring.after_bki(check, report, trusted_source_review=trusted_review)
    evaluation = record_evaluation(db, application, company, precheck, check, decision,
                                   None if report is None else {**report, 'requested_at': iso_utc(now)},
                                   now=now, trusted_review=trusted_review)
    if decision.info_request:
        wanted = decision.info_request
        if request is None or (request.kind, request.source) != (wanted['kind'], wanted['source']):
            create_info_request(db, application, now=now, **wanted)
    elif trusted_review and request.source == 'bki' and complete_report(report):
        request.resolved_at = now  # fresh trusted-source evidence closes the request; the outcome is reviewed or rejected
    application.scored_limit_rub = decision.scored_limit_rub
    if decision.outcome == 'PREAPPROVED':
        application.preapproved_amount_rub = decision.preapproved_amount_rub
        application.preapproved_at = now
        application.preapproval_expires_at = now + PREAPPROVAL_TTL
    change.move(decision.outcome, reason_code=decision.rule, reason_text=' '.join(decision.reasons),
                notification=outcome_notification(decision, application), by_system=True)
    return evaluation


def latest_bki_evidence(db: Session, application_id: str) -> tuple[str, dict] | None:
    """The newest complete BKI report among the application's evaluations, with the id of the evaluation whose
    request produced it: the trusted evidence a re-check reuses instead of requesting the BKI again."""
    for evaluation_id, sources in db.execute(select(Evaluation.id, Evaluation.sources).where(Evaluation.application_id == application_id)
                                             .order_by(Evaluation.sequence.desc())):
        report = sources.get('bki')
        if complete_report(report):
            return report.get('reused_from_evaluation_id', evaluation_id), report
    return None


def flags_on_record(db: Session, application_id: str) -> set[str]:
    return {flag for snapshot in db.scalars(select(Evaluation.input_snapshot).where(Evaluation.application_id == application_id))
            for flag in snapshot.get('review_flags', [])}


def recheck_after_response(db: Session, change: ApplicationChange, company: Company, terms: Terms, *, reason_text: str,
                           notification: str) -> Evaluation:
    """After an information response: a new evaluation from the revised answers with the latest trusted source
    evidence (the persisted precheck and the latest complete BKI report, reused without a new request; earlier
    evaluations and the submission snapshot stay as they are), then NEED_INFO→MANUAL_REVIEW as the client's step.
    The assignee, if any, is kept: the same officer reviews the answer."""
    application, now = change.application, change.now
    precheck = latest_precheck(db, company.id)
    check = check_input(application, company, precheck, terms)
    evidence = latest_bki_evidence(db, application.id)
    report = None if evidence is None else evidence[1]
    decision = scoring.after_response(check, report, flags_on_record(db, application.id))
    payload = None if evidence is None else {**report, 'reused_from_evaluation_id': evidence[0]}
    evaluation = record_evaluation(db, application, company, precheck, check, decision, payload, now=now,
                                   trusted_review=False, client_response=True)
    application.scored_limit_rub = decision.scored_limit_rub
    change.move('MANUAL_REVIEW', reason_code='INFO_PROVIDED', reason_text=reason_text, notification=notification)
    return evaluation
