"""Document serialization: the public document (never the storage key or the reviewer's identity), the checklist,
and the attachment Content-Disposition for downloads. Staff documents add the reviewer in app.officer.views."""
import string
from ..applications.models import Application
from ..applications.views import plain
from .models import Document
from .service import current_documents, required_types

PUBLIC_FIELDS = ('id', 'application_id', 'document_type', 'revision', 'original_name', 'media_type', 'size_bytes', 'sha256',
                 'status', 'review_reason', 'verified_value_rub', 'created_at', 'reviewed_at')
REVIEW_NOTICE = ('Демонстрационная проверка документов: тип и структура файла проверяются автоматически, содержание — '
                 'кредитным специалистом. Это не антивирусная проверка и не проверка подлинности.')
# RFC 5987 attr-char: sent as is in filename*; everything else is percent-encoded UTF-8.
ATTR_CHARS = frozenset(string.ascii_letters + string.digits + "!#$&+-.^_`|~")


def public_document(document: Document) -> dict:
    body = {name: plain(getattr(document, name)) for name in PUBLIC_FIELDS}
    body['download_url'] = None if document.status == 'DELETED' else (
        f'/api/v1/applications/{document.application_id}/documents/{document.id}/download')
    return body


def ordered(application: Application, documents: list[Document]) -> list[Document]:
    """Checklist order, then revision."""
    order = {kind: index for index, kind in enumerate(required_types(application))}
    return sorted(documents, key=lambda document: (order.get(document.document_type, len(order)), document.document_type,
                                                   document.revision))


def checklist(application: Application, documents: list[Document]) -> dict:
    current = current_documents(documents)
    return {'notice': REVIEW_NOTICE,
            'requirements': [{'document_type': kind, 'required': True,
                              'current_document': public_document(current[kind]) if kind in current else None}
                             for kind in required_types(application)],
            'items': [public_document(document) for document in ordered(application, documents)]}


def attachment_disposition(name: str) -> str:
    """`attachment` with a printable-ASCII fallback (no quotes, backslashes, slashes or semicolons) and the exact
    UTF-8 name in RFC 5987 `filename*`; names are already free of control characters (validation.safe_name)."""
    fallback = ''.join(char if ' ' <= char <= '~' and char not in '"\\/;' else '_' for char in name)
    encoded = ''.join(char if char in ATTR_CHARS else ''.join(f'%{byte:02X}' for byte in char.encode()) for char in name)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
