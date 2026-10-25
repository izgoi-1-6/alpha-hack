"""Document routes under /api/v1/applications/{id}/documents: the checklist, upload, delete and complete for the
owning CLIENT (officers 403, other clients 404), and downloads for the owner or any CREDIT_OFFICER (staff reads are
role-scoped; review is the assignee's).

Upload order: authentication, ownership (404, before any byte is read; the read transaction then ends, so streaming
holds no pooled connection), the streamed body into a private staging file (413 while reading, 422 form errors), file
validation (415/422), then commands.run_command with the upload's digest at the time the body has arrived (the clock
from the `get_clock` dependency, called then): locks and lazy expiry, idempotency replay, expired refusal, version,
state, checklist rules, and the file moved into place after its row is flushed. The staging file is removed whatever
happens.
"""
from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from ..applications import commands
from ..applications.lifecycle import get_application, get_owned_application, lock_owned_application, require_application
from ..applications.router import run_command as run_owner_command
from ..applications.views import public_application
from ..clock import get_clock
from ..idempotency import IdempotencyKey
from ..identity import ClientUser, CurrentUser, Db, Now
from ..schemas import VersionInput
from . import intake, service, validation, views
from .schemas import UploadDigest, upload_fields
from .storage import DocumentStorage, get_storage

router = APIRouter(prefix='/applications', tags=['documents'])
Storage = Annotated[DocumentStorage, Depends(get_storage)]
Clock = Annotated[Callable[[], datetime], Depends(get_clock)]
DOWNLOAD_HEADERS = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                    'Content-Security-Policy': "default-src 'none'; sandbox"}


@router.get('/{application_id}/documents')
def read_documents(application_id: str, user: ClientUser, db: Db, now: Now):
    application = get_owned_application(db, application_id, user.id, now)
    return views.checklist(application, service.documents_of(db, application.id))


@router.post('/{application_id}/documents', status_code=201)
def upload_document(application_id: str, request: Request, user: ClientUser, db: Db, clock: Clock,
                    storage: Storage, idempotency_key: IdempotencyKey):
    require_application(db, application_id, owner_id=user.id)
    db.commit()  # ends the read-only transaction: the body streams without holding a connection
    with storage.staged() as staged:
        form = intake.receive_upload(intake.request_chunks(request), request.headers, staged)
        document_type, version = upload_fields(form.fields)
        name = validation.safe_name(form.filename)
        media_type = validation.inspect(name, form.content_type, staged.read_bytes())
        digest = UploadDigest(document_type=document_type, version=version, sha256=staged.sha256, original_name=name)
        now = clock()  # the command applies now: lazy expiry and timestamps use this time, not the request start
        created = {}

        def apply(application, _company):
            created['document'] = service.upload_document(db, storage, application, user.id, digest, staged, media_type, now)

        return commands.run_command(
            db, request, user.id, idempotency_key, digest, now, status=201, apply=apply,
            lock=lambda: lock_owned_application(db, application_id, user.id, now),
            render=lambda application, company: {'document': views.public_document(created['document']),
                                                 'application': public_application(db, application, company)})


@router.get('/{application_id}/documents/{document_id}/download')
def download_document(application_id: str, document_id: str, user: CurrentUser, db: Db, now: Now, storage: Storage):
    application = get_application(db, application_id, now, owner_id=None if user.role == 'CREDIT_OFFICER' else user.id)
    document = service.find_document(db, application.id, document_id)
    path = storage.path(document.storage_key)
    if document.status == 'DELETED' or not path.is_file():
        raise service.not_found()
    return FileResponse(path, media_type=document.media_type,
                        headers={**DOWNLOAD_HEADERS, 'Content-Disposition': views.attachment_disposition(document.original_name)})


@router.delete('/{application_id}/documents/{document_id}')
def delete_document(application_id: str, document_id: str, data: VersionInput, request: Request, user: ClientUser, db: Db,
                    now: Now, storage: Storage, idempotency_key: IdempotencyKey):
    found = {}

    def lock():  # the document must belong to the application before the replay check (an ownership check)
        locked = lock_owned_application(db, application_id, user.id, now)
        found['document'] = service.find_document(db, application_id, document_id, for_update=True)
        return locked

    return commands.run_command(
        db, request, user.id, idempotency_key, data, now, lock=lock,
        apply=lambda application, _company: service.delete_document(db, storage, application, found['document'], user.id,
                                                                    data.version, now),
        render=lambda application, company: {'application': public_application(db, application, company)})


@router.post('/{application_id}/documents/complete')
def complete_documents(application_id: str, data: VersionInput, request: Request, user: ClientUser, db: Db, now: Now,
                       idempotency_key: IdempotencyKey):
    return run_owner_command(application_id, data, request, user, db, now, idempotency_key,
                             lambda application, _company: service.complete_documents(db, application, user.id, data.version, now))
