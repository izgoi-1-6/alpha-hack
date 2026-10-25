"""Staff serialization: the customer's public fields plus the claim owner, score factors, review flags, source
evidence, decisions, all information requests, every document revision with its reviewer, the final approval terms,
the answer paths an officer may request for this product, and a history that names users. Officer-only reads
(role-gated by the router). Unresolved requests on a terminal application are shown as audit rows (`open: false`),
never as actionable.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..companies import latest_precheck, public_row
from ..models import Company, User
from ..applications import stages
from ..applications.info_requests import OFFICER_PATHS
from ..documents import service as documents
from ..documents.models import Document
from ..documents.views import REVIEW_NOTICE, ordered, public_document
from ..applications.models import TERMINAL_STATUSES, Application, Evaluation, InfoRequest, OfficerDecision
from ..applications.products import Terms, application_terms
from ..applications.views import (APPLICATION_FIELDS, company_summary, current_request, history_item, history_rows,
                                  latest_evaluation, missing_fields, plain, product_summary, public_evaluation,
                                  public_info_request)
from .policy import final_terms, preapproval_terms, staff_actions

SUBMITTED_EVIDENCE = ('submitted_at', 'company', 'precheck', 'answers', 'secured', 'required_documents')


def user_ref(user: User | None) -> dict | None:
    return None if user is None else {'id': user.id, 'display_name': user.display_name}


def evaluation_summary(row: Evaluation | None) -> dict | None:
    summary = public_evaluation(row)
    if summary is not None:
        summary.update(factors=row.factors, review_flags=list(row.input_snapshot.get('review_flags', [])))
    return summary


def staff_evaluation(row: Evaluation) -> dict:
    """An immutable evaluation in full: what was scored and the source evidence it used."""
    return {**evaluation_summary(row), 'input_snapshot': row.input_snapshot, 'sources': row.sources}


def staff_info_request(db: Session, row: InfoRequest | None, application: Application) -> dict | None:
    if row is None:
        return None
    return {**public_info_request(row), 'officer': user_ref(row.officer_id and db.get(User, row.officer_id)),
            'open': row.resolved_at is None and application.status not in TERMINAL_STATUSES}


def preapproval_view(application: Application, company: Company, evaluation: Evaluation | None, terms: Terms | None) -> dict | None:
    """The officer's amount bounds while the application is in review, or why preapproval is refused."""
    if application.status != 'MANUAL_REVIEW' or terms is None:
        return None
    bounds, refusal = preapproval_terms(application, company, evaluation, terms.product)
    low, high = bounds or (None, None)
    return {'amount_min_rub': low, 'amount_max_rub': high,
            'blocked_by': None if refusal is None else {'code': refusal[0], 'message': refusal[1]}}


def final_approval_view(application: Application, application_documents: list[Document], evaluation: Evaluation | None,
                        terms: Terms | None) -> dict | None:
    """The officer's final amount bounds while the packet is in review, or why final approval is refused."""
    if application.status != 'DOCS_UPLOADED' or terms is None:
        return None
    return final_terms(application, application_documents, evaluation, terms)


def staff_application(db: Session, application: Application, officer_id: str, company: Company | None = None) -> dict:
    company = company or db.get(Company, application.company_id)
    terms = application_terms(application)
    request = current_request(db, application)
    evaluation = latest_evaluation(db, application.id)
    application_documents = documents.documents_of(db, application.id)
    preapproval = preapproval_view(application, company, evaluation, terms)
    final_approval = final_approval_view(application, application_documents, evaluation, terms)
    reviewable = any(row.status == 'UPLOADED' for row in documents.current_documents(application_documents).values())
    body = {name: plain(getattr(application, name)) for name in APPLICATION_FIELDS}
    body.update(company=company_summary(company), product=product_summary(application, terms),
                latest_evaluation=evaluation_summary(evaluation),
                assignee=user_ref(application.assignee_id and db.get(User, application.assignee_id)),
                allowed_actions=staff_actions(application, officer_id,
                                              preapprovable=preapproval is not None and preapproval['blocked_by'] is None,
                                              reviewable=reviewable,
                                              approvable=final_approval is not None and final_approval['blocked_by'] is None),
                missing_fields=missing_fields(application, company, terms, request),
                open_info_request=staff_info_request(db, request, application), preapproval=preapproval,
                final_approval=final_approval, document_summary=documents.summary(application, application_documents))
    return body


def staff_document(db: Session, document: Document) -> dict:
    return {**public_document(document), 'reviewer': user_ref(document.reviewer_id and db.get(User, document.reviewer_id))}


def requestable_fields(terms: Terms | None) -> list[str]:
    """The answer paths an officer may request for this application: info_requests.OFFICER_PATHS, with the pledge
    paths only for an application that is secured (pinned at submission)."""
    secured = bool(terms and terms.secured)
    return [path for path in OFFICER_PATHS if secured or path.split('.')[0] != 'collateral']


def source_evidence(db: Session, application: Application, company: Company, evaluations: list[Evaluation]) -> dict:
    """The persisted company and latest precheck, the snapshot pinned at submission, the stage-3 answers next to the
    source values (origin tags: source, override = conflict, declared; the submitted answer kept beside the current
    one) and every BKI payload an evaluation used."""
    precheck = latest_precheck(db, company.id)
    snapshot = application.submitted_input_snapshot
    submitted_answers = snapshot['answers'] if snapshot else {}
    finance = {name: {**entry, 'submitted_answer': submitted_answers.get(name)}
               for name, entry in stages.finance_evidence(application.answers, precheck).items()}
    return {'company': public_row(company), 'precheck': public_row(precheck),
            'submitted': None if snapshot is None else {key: snapshot[key] for key in SUBMITTED_EVIDENCE},
            'finance': finance,
            'bki': [{'evaluation_id': row.id, **row.sources['bki']} for row in evaluations if row.sources.get('bki')]}


def staff_history(db: Session, application: Application) -> list[dict]:
    return [{**history_item(entry, note, user), 'actor': user_ref(user)} for entry, note, user in history_rows(db, application)]


def staff_detail(db: Session, application: Application, officer_id: str) -> dict:
    company = db.get(Company, application.company_id)
    evaluations = db.scalars(select(Evaluation).where(Evaluation.application_id == application.id).order_by(Evaluation.sequence)).all()
    decisions = db.execute(select(OfficerDecision, User).join(User, User.id == OfficerDecision.officer_id)
                           .where(OfficerDecision.application_id == application.id).order_by(OfficerDecision.sequence)).all()
    requests = sorted(db.scalars(select(InfoRequest).where(InfoRequest.application_id == application.id)).all(),
                      key=lambda row: (plain(row.created_at), row.resolved_at is None, plain(row.resolved_at) or '', row.id))
    return {'application': staff_application(db, application, officer_id, company),
            'evaluations': [staff_evaluation(row) for row in evaluations],
            'source_evidence': source_evidence(db, application, company, evaluations),
            'decisions': [{'id': row.id, 'officer': user_ref(user), 'phase': row.phase, 'action': row.action,
                           'amount_rub': row.amount_rub, 'reason': row.reason, 'evaluation_id': row.evaluation_id,
                           'created_at': plain(row.created_at)} for row, user in decisions],
            'info_requests': [staff_info_request(db, row, application) for row in requests],
            'history': staff_history(db, application),
            'documents': [staff_document(db, row) for row in ordered(application, documents.documents_of(db, application.id))],
            'document_notice': REVIEW_NOTICE,
            'requestable_fields': requestable_fields(application_terms(application))}
