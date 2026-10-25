"""Synthetic document bytes and HTTP helpers for the document, final-decision and handoff tests.

Files are built here, independently of the code under test: PDFs and PNGs are written byte by byte (hand-computed
xref offsets, zlib + CRC chunks), JPEGs come from Pillow's encoder. Nothing is a real document and nothing contains
personal data. Private storage is a pytest tmp directory injected through the storage dependency, so every test can
assert exactly which files exist.
"""
from datetime import datetime, timezone
import hashlib
import io
import struct
import zlib
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import select
from application_helpers import submitted
from officer_helpers import claimed, staff_command

MIB = 1024 * 1024
LIMIT = 20 * MIB  # spec: a single file of at most 20 MiB
DEADLINE = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)  # FIXED_NOW (2026-10-24 12:00 UTC) + 14 days
UNSECURED_DOCS = ['BANK_STATEMENT', 'FINANCIAL_REPORT']
SECURED_DOCS = ['BANK_STATEMENT', 'FINANCIAL_REPORT', 'COLLATERAL_OWNERSHIP', 'COLLATERAL_VALUATION']
HTML = b'<!DOCTYPE html><html><body><script>alert(1)</script></body></html>'
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="1"/></svg>'


# --- synthetic files -------------------------------------------------------------------------------------------------

def pdf_bytes(*, catalog: bytes = b'', objects: tuple[bytes, ...] = (), text: bytes = b'Demo', padding: int = 0,
              comment: bytes = b'', pages: bool = True) -> bytes:
    """A minimal one-page PDF 1.4 with a correct cross-reference table. `catalog` adds catalog entries, `objects`
    extra indirect objects (numbered from 5), `padding` spaces inside the page content stream; `pages=False` leaves
    the page tree empty (the page object stays, unreferenced)."""
    content = b'BT /F1 12 Tf 20 100 Td (' + text + b') Tj ET\n' + b' ' * padding
    bodies = [b'<< /Type /Catalog /Pages 2 0 R ' + catalog + b'>>',
              b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>' if pages else b'<< /Type /Pages /Kids [] /Count 0 >>',
              b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>',
              b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream', *objects]
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n' + comment)
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(bodies) + 1)
    out += b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(bodies) + 1, xref)
    return bytes(out)


def pdf_of_size(size: int) -> bytes:
    """A valid PDF of exactly `size` bytes (spaces padded into the content stream; offsets recomputed)."""
    base = len(pdf_bytes())
    padding = size - base
    for _ in range(3):  # the /Length and offset digits grow with the padding
        data = pdf_bytes(padding=padding)
        padding += size - len(data)
    data = pdf_bytes(padding=padding)
    assert len(data) == size
    return data


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(width: int = 4, height: int = 3, *, extra_chunks: tuple[bytes, ...] = ()) -> bytes:
    rows = b''.join(b'\x00' + b'\xc8\x14\x14' * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + b''.join(extra_chunks) + png_chunk(b'IDAT', zlib.compress(rows)) + png_chunk(b'IEND', b''))


def jpeg_bytes(width: int = 16, height: int = 16) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (width, height), (200, 20, 20)).save(out, 'JPEG')
    return out.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- private storage -------------------------------------------------------------------------------------------------

@pytest.fixture
def storage(client, tmp_path) -> Path:
    """Private storage in a per-test directory (imported lazily so a missing module fails per test)."""
    from app.documents.storage import DocumentStorage, get_storage
    root = tmp_path / 'private-documents'
    client.app.dependency_overrides[get_storage] = lambda: DocumentStorage(root)
    return root


def stored(root: Path) -> dict[str, bytes]:
    """Every file under the storage root, staging included, by relative path."""
    if not root.exists():
        return {}
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def document_rows(client, **where) -> list:
    from app.documents.models import Document
    with client.app.state.test_factory() as db:
        query = select(Document)
        for key, value in where.items():
            query = query.where(getattr(Document, key) == value)
        return sorted(db.scalars(query).all(), key=lambda row: (row.document_type, row.revision))


# --- HTTP ------------------------------------------------------------------------------------------------------------

def docs_url(application: dict, suffix: str = '') -> str:
    return f"/api/v1/applications/{application['id']}/documents{suffix}"


FILES = {'pdf': (pdf_bytes, 'statement.pdf', 'application/pdf'), 'png': (png_bytes, 'report.png', 'image/png'),
         'jpeg': (jpeg_bytes, 'scan.jpg', 'image/jpeg')}


def upload(client, application: dict, document_type: str = 'BANK_STATEMENT', content: bytes | None = None, *,
           kind: str = 'pdf', filename: str | None = None, mime: str | None = None, version: int | str | None = None,
           key: str | None = None, data: dict | None = None):
    build, default_name, default_mime = FILES[kind]
    files = {'file': (default_name if filename is None else filename, build() if content is None else content,
                      default_mime if mime is None else mime)}
    fields = {'document_type': document_type, 'version': str(application['version'] if version is None else version)}
    return client.post(docs_url(application), files=files, data={**fields, **(data or {})},
                       headers={'Idempotency-Key': key or uuid4().hex})


BOUNDARY = 'demo-boundary-7f3a'


def multipart(parts: list[tuple[bytes, bytes | None, bytes, bytes | None]]) -> tuple[bytes, str]:
    """A hand-built multipart/form-data body: (name, filename or None for a plain field, content, Content-Type).
    Names reach the server byte for byte (no client-side escaping)."""
    out = bytearray()
    for name, filename, content, mime in parts:
        out += b'--' + BOUNDARY.encode() + b'\r\nContent-Disposition: form-data; name="' + name + b'"'
        if filename is not None:
            out += b'; filename="' + filename + b'"'
        out += b'\r\n' + (b'Content-Type: ' + mime + b'\r\n' if mime else b'') + b'\r\n' + content + b'\r\n'
    out += b'--' + BOUNDARY.encode() + b'--\r\n'
    return bytes(out), f'multipart/form-data; boundary={BOUNDARY}'


def raw_upload(client, application: dict, parts, *, key: str | None = None):
    body, content_type = multipart(parts)
    return client.post(docs_url(application), content=body,
                       headers={'content-type': content_type, 'Idempotency-Key': key or uuid4().hex})


def form_fields(application: dict, document_type: bytes = b'BANK_STATEMENT') -> list:
    return [(b'document_type', None, document_type, None), (b'version', None, str(application['version']).encode(), None)]


def uploaded(client, application: dict, document_type: str = 'BANK_STATEMENT', content: bytes | None = None, **options) -> tuple[dict, dict]:
    response = upload(client, application, document_type, content, **options)
    assert response.status_code == 201, response.text
    body = response.json()
    return body['document'], body['application']


def checklist(client, application: dict) -> dict:
    response = client.get(docs_url(application))
    assert response.status_code == 200, response.text
    return response.json()


def download(session, application: dict, document: dict):
    return session.get(docs_url(application, f"/{document['id']}/download"))


def delete(client, application: dict, document: dict, *, version: int | None = None, key: str | None = None):
    return client.request('DELETE', docs_url(application, f"/{document['id']}"),
                          json={'version': version or application['version']}, headers={'Idempotency-Key': key or uuid4().hex})


def complete_docs(client, application: dict, *, version: int | None = None, key: str | None = None):
    return client.post(docs_url(application, '/complete'), json={'version': version or application['version']},
                       headers={'Idempotency-Key': key or uuid4().hex})


def completed(client, application: dict) -> dict:
    response = complete_docs(client, application)
    assert response.status_code == 200, response.text
    return response.json()['application']


def upload_all(client, application: dict, types: list[str] | None = None) -> tuple[dict, dict[str, dict]]:
    """Uploads a valid file for every required document; returns the latest application and the documents."""
    documents = {}
    for index, document_type in enumerate(types or application['product']['required_documents']):
        documents[document_type], application = uploaded(client, application, document_type,
                                                         kind=('pdf', 'png', 'jpeg')[index % 3])
    return application, documents


def review(officer, application: dict, document: dict, decision: str = 'accept', reason: str = 'Демонстрационная проверка: документ читается.',
           *, verified_value_rub: int | None = None, key: str | None = None, version: int | None = None, extra: dict | None = None):
    body = {'decision': decision, 'reason': reason, **(extra or {})}
    if verified_value_rub is not None:
        body['verified_value_rub'] = verified_value_rub
    return staff_command(officer, application, f"documents/{document['id']}/review", body, key=key, version=version)


def reviewed(officer, application: dict, document: dict, decision: str = 'accept', **options) -> tuple[dict, dict]:
    response = review(officer, application, document, decision, **options)
    assert response.status_code == 200, response.text
    body = response.json()
    return body['document'], body['application']


def approve(officer, application: dict, amount: int, reason: str = 'Документы приняты: окончательное демо-решение.', **options):
    return staff_command(officer, application, 'approve', {'amount_rub': amount, 'reason': reason}, **options)


def link(client, application: dict, *, key: str | None = None, body: dict | None = None):
    return client.post('/api/v1/integrations/alfa-business/link', json=body or {'application_id': application['id']},
                       headers={'Idempotency-Key': key or uuid4().hex})


# --- journeys --------------------------------------------------------------------------------------------------------

def preapproved(client, fixture: str = 'strong', **need) -> dict:
    """An automatically preapproved application (unassigned): strong 2,000,000 or secured_investment 4,000,000."""
    application = submitted(client, fixture, **need)
    assert application['status'] == 'PREAPPROVED', application
    return application


def in_review(client, officer, fixture: str = 'strong') -> tuple[dict, dict[str, dict]]:
    """Every required document uploaded, the packet completed (DOCS_UPLOADED) and the case claimed by the officer."""
    application, documents = upload_all(client, preapproved(client, fixture))
    application = claimed(officer, completed(client, application))
    return application, documents


def accept_all(officer, application: dict, documents: dict[str, dict], *, valuation: int | None = None) -> dict:
    for document_type, document in documents.items():
        value = valuation if document_type == 'COLLATERAL_VALUATION' else None
        _, application = reviewed(officer, application, document, verified_value_rub=value)
    return application
