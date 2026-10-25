"""The document checklist and the customer's document commands (upload, delete, complete), plus recording an
officer's review on a document row. Commands run on rows the router has locked (company, then application) after the
idempotency replay; any ApiError rolls the whole command back, and storage follows the transaction (storage.py).

Checklist rules (spec "Documents and final decision"): the requirements are the pinned product's
`required_documents`; each has at most one current revision (UPLOADED, ACCEPTED or REJECTED). Uploads and deletions
are allowed in PREAPPROVED and DOCS_REWORK only (DOCS_UPLOADED freezes the packet); an UPLOADED or REJECTED current
revision may be replaced or deleted, an ACCEPTED one never. Completion needs every requirement present and none
rejected. Uploads never move the preapproval deadline.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..errors import ApiError
from ..applications.lifecycle import ApplicationChange
from ..applications.models import Application
from ..applications.products import application_product
from ..applications.service import require_version
from .models import CURRENT_STATUSES, Document
from .schemas import UploadDigest
from .storage import DocumentStorage, StagedFile

UPLOAD_STATES = frozenset({'PREAPPROVED', 'DOCS_REWORK'})
LABELS = {'BANK_STATEMENT': 'Банковская выписка', 'FINANCIAL_REPORT': 'Финансовая отчётность',
          'COLLATERAL_OWNERSHIP': 'Документ о праве собственности на залог', 'COLLATERAL_VALUATION': 'Отчёт об оценке залога'}


def required_types(application: Application) -> list[str]:
    product = application_product(application)
    return list(product['required_documents']) if product else []


def documents_of(db: Session, application_id: str) -> list[Document]:
    return list(db.scalars(select(Document).where(Document.application_id == application_id)
                           .order_by(Document.document_type, Document.revision)))


def current_documents(documents: list[Document]) -> dict[str, Document]:
    return {document.document_type: document for document in documents if document.status in CURRENT_STATUSES}


def packet(application: Application, documents: list[Document]) -> tuple[list[str], list[str]]:
    """(missing, rejected) requirement types, in checklist order."""
    current = current_documents(documents)
    required = required_types(application)
    return ([kind for kind in required if kind not in current],
            [kind for kind in required if kind in current and current[kind].status == 'REJECTED'])


def summary(application: Application, documents: list[Document]) -> dict | None:
    """The checklist in numbers once the application reached the document phase (null before preapproval).
    `current_uploaded` counts requirements with a current document whatever its review; `accepted` and `rejected`
    count those reviewed so; `can_complete` holds only where completion is allowed now."""
    if application.preapproved_at is None:
        return None
    current = current_documents(documents)
    required = required_types(application)
    missing, rejected = packet(application, documents)
    return {'required_total': len(required), 'current_uploaded': sum(kind in current for kind in required),
            'accepted': sum(kind in current and current[kind].status == 'ACCEPTED' for kind in required),
            'rejected': len(rejected), 'missing': missing,
            'can_complete': application.status in UPLOAD_STATES and not missing and not rejected}


def customer_actions(application: Application, documents: list[Document]) -> list[str]:
    """The document commands the owner can run now (inserted before `cancel` in allowed_actions)."""
    if application.status not in UPLOAD_STATES:
        return []
    current = current_documents(documents)
    actions = []
    if any(kind not in current or current[kind].status != 'ACCEPTED' for kind in required_types(application)):
        actions.append('upload_document')
    if any(document.status in ('UPLOADED', 'REJECTED') for document in current.values()):
        actions.append('delete_document')
    missing, rejected = packet(application, documents)
    if not missing and not rejected:
        actions.append('complete_documents')
    return actions


def not_found() -> ApiError:
    return ApiError(404, 'DOCUMENT_NOT_FOUND', 'Документ не найден')


def find_document(db: Session, application_id: str, document_id: str, *, for_update: bool = False) -> Document:
    """A document of this application (any status), or 404."""
    query = select(Document).where(Document.id == document_id, Document.application_id == application_id)
    document = db.scalar(query.with_for_update() if for_update else query)
    if document is None:
        raise not_found()
    return document


def accepted_error() -> ApiError:
    return ApiError(409, 'DOCUMENT_ACCEPTED', 'Принятый документ нельзя заменить или удалить.')


def require_upload_state(application: Application) -> None:
    if application.status not in UPLOAD_STATES:
        raise ApiError(409, 'INVALID_STATUS', 'Документы загружают и удаляют после предварительного одобрения или при '
                                              'доработке комплекта; отправленный комплект ждёт проверки.')


def upload_document(db: Session, storage: DocumentStorage, application: Application, user_id: str, form: UploadDigest,
                    staged: StagedFile, media_type: str, now: datetime) -> Document:
    """A new current revision for the requirement: an UPLOADED/REJECTED current revision is superseded (its content
    stays readable), an ACCEPTED one refuses. The bytes move into place after the row is flushed."""
    require_version(application, form.version)
    require_upload_state(application)
    if form.document_type not in required_types(application):
        message = 'Этот документ не входит в перечень для продукта заявки.'
        raise ApiError(422, 'DOCUMENT_TYPE_NOT_ALLOWED', message, fields={'document_type': message})
    revisions = [document for document in documents_of(db, application.id) if document.document_type == form.document_type]
    current = current_documents(revisions).get(form.document_type)
    if current is not None and current.status == 'ACCEPTED':
        raise accepted_error()
    if current is not None:
        current.status = 'SUPERSEDED'
        db.flush()  # the partial unique index admits one current revision at a time
    document = Document(application_id=application.id, document_type=form.document_type,
                        revision=max((row.revision for row in revisions), default=0) + 1, original_name=form.original_name,
                        media_type=media_type, size_bytes=staged.size, sha256=staged.sha256,
                        storage_key=storage.new_key(), status='UPLOADED', created_at=now)
    db.add(document)
    db.flush()
    storage.place(db, staged, document.storage_key)
    ApplicationChange(db, application, actor_id=user_id, now=now).touch()
    return document


def delete_document(db: Session, storage: DocumentStorage, application: Application, document: Document, user_id: str,
                    version: int, now: datetime) -> None:
    """Marks an UPLOADED or REJECTED current revision DELETED; its bytes are removed once the transaction commits."""
    require_version(application, version)
    require_upload_state(application)
    if document.status == 'DELETED':
        raise not_found()
    if document.status == 'ACCEPTED':
        raise accepted_error()
    if document.status == 'SUPERSEDED':
        raise ApiError(409, 'DOCUMENT_NOT_CURRENT', 'Удалить можно только текущий файл документа; прежние версии хранятся в истории.')
    document.status = 'DELETED'
    storage.remove_after_commit(db, document.storage_key)
    ApplicationChange(db, application, actor_id=user_id, now=now).touch()


def complete_documents(db: Session, application: Application, user_id: str, version: int, now: datetime) -> None:
    """PREAPPROVED/DOCS_REWORK → DOCS_UPLOADED (the client's step) once every requirement is present and none is
    rejected."""
    require_version(application, version)
    require_upload_state(application)
    missing, rejected = packet(application, documents_of(db, application.id))
    if missing or rejected:
        raise ApiError(409, 'DOCUMENTS_INCOMPLETE', 'Загрузите все обязательные документы и замените отклонённые.',
                       details={'missing': missing, 'rejected': rejected})
    ApplicationChange(db, application, actor_id=user_id, now=now).move(
        'DOCS_UPLOADED', reason_code='DOCUMENTS_SUBMITTED', reason_text='Клиент передал комплект документов на проверку.')


def record_review(document: Document, *, accepted: bool, reason: str, reviewer_id: str, now: datetime,
                  verified_value_rub: int | None) -> None:
    """An officer's review on the row itself, atomically: status, reviewer, time, reason and (only for an accepted
    valuation) the verified value."""
    document.status = 'ACCEPTED' if accepted else 'REJECTED'
    document.reviewer_id, document.reviewed_at, document.review_reason = reviewer_id, now, reason
    document.verified_value_rub = verified_value_rub
