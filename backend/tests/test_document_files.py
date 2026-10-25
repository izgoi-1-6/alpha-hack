"""A08: real upload bytes into private storage. Size (413 while streaming), type agreement and active content (415),
empty/truncated/unparseable files (422), traversal and control-character names, the actual SHA-256, form validation,
and cleanup: after every refused, replayed or rolled-back upload the storage directory holds exactly the expected
files and an empty staging area.

Files are synthetic bytes from document_helpers (hand-written PDF/PNG, Pillow-encoded JPEG), never production helpers.
"""
import hashlib
from uuid import uuid4
import zlib
import pytest
from application_helpers import clock, read
from document_helpers import (HTML, LIMIT, MIB, SVG, docs_url, document_rows, download, jpeg_bytes, pdf_bytes,
                              pdf_of_size, png_bytes, png_chunk, preapproved, sha256, storage, stored, upload, uploaded)
from test_identity_company import client

pytestmark = pytest.mark.usefixtures('clock', 'storage')
HEX_KEY = set('0123456789abcdef')


def refused(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code, response.text


def nothing_kept(client, storage, application: dict) -> None:
    """A refused upload leaves no row, no file (staging included) and the application revision untouched."""
    assert document_rows(client) == [] and stored(storage) == {}
    assert read(client, application)['version'] == application['version']


def test_valid_pdf_png_and_jpeg_are_stored_privately_under_random_keys(client, storage):
    application = preapproved(client)
    files = {'BANK_STATEMENT': (pdf_bytes(), 'Выписка за сентябрь.pdf', 'application/pdf'),
             'FINANCIAL_REPORT': (png_bytes(), 'report.PNG', 'image/png')}
    documents = {}
    for document_type, (content, name, mime) in files.items():
        documents[document_type], application = uploaded(client, application, document_type, content, filename=name, mime=mime)
    jpeg = jpeg_bytes()
    replacement, application = uploaded(client, application, 'FINANCIAL_REPORT', jpeg, filename='scan.jpeg', mime='image/jpeg')
    pdf, png = documents['BANK_STATEMENT'], documents['FINANCIAL_REPORT']
    assert (pdf['media_type'], pdf['size_bytes'], pdf['sha256'], pdf['original_name']) == (
        'application/pdf', len(files['BANK_STATEMENT'][0]), sha256(files['BANK_STATEMENT'][0]), 'Выписка за сентябрь.pdf')
    assert (png['media_type'], png['sha256'], png['original_name']) == ('image/png', sha256(files['FINANCIAL_REPORT'][0]), 'report.PNG')
    assert (replacement['media_type'], replacement['sha256'], replacement['revision']) == ('image/jpeg', sha256(jpeg), 2)
    assert all('storage_key' not in document for document in (pdf, png, replacement))
    rows = {row.id: row for row in document_rows(client)}
    on_disk = stored(storage)
    # Exactly one private file per revision, named by a random hex key unrelated to the upload name, holding the bytes.
    assert set(on_disk) == {row.storage_key for row in rows.values()} and len(on_disk) == 3
    assert all(len(name) == 32 and set(name) <= HEX_KEY for name in on_disk)
    assert on_disk[rows[pdf['id']].storage_key] == files['BANK_STATEMENT'][0]
    assert on_disk[rows[replacement['id']].storage_key] == jpeg
    assert all(sha256(on_disk[row.storage_key]) == row.sha256 for row in rows.values())


def test_a_file_of_exactly_20_mib_is_accepted_and_one_byte_more_is_413(client, storage):
    application = preapproved(client)
    refused(upload(client, application, content=pdf_of_size(LIMIT + 1)), 413, 'FILE_TOO_LARGE')
    nothing_kept(client, storage, application)
    exact = pdf_of_size(LIMIT)
    document, _ = uploaded(client, application, content=exact)
    assert document['size_bytes'] == LIMIT and document['sha256'] == sha256(exact)
    assert list(stored(storage).values()) == [exact]


def test_the_intake_stops_reading_once_the_size_limit_is_passed(storage):
    """The body is never buffered whole: the reader pulls chunks only until the limit is passed, and a declared
    Content-Length above it is refused before any chunk is read. The staged file is removed."""
    from app.documents.intake import receive_upload
    from app.documents.storage import DocumentStorage
    from app.errors import ApiError
    pulled = []

    def endless():
        yield b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        while True:
            pulled.append(1)
            yield b'%' * MIB

    headers = {'content-type': 'multipart/form-data; boundary=b'}
    private = DocumentStorage(storage)
    with pytest.raises(ApiError) as caught, private.staged() as staged:
        receive_upload(endless(), headers, staged)
    assert (caught.value.status, caught.value.code) == (413, 'FILE_TOO_LARGE')
    assert len(pulled) <= LIMIT // MIB + 2 and stored(storage) == {}
    pulled.clear()
    with pytest.raises(ApiError) as caught, private.staged() as staged:
        receive_upload(endless(), {**headers, 'content-length': str(LIMIT + 2 * MIB)}, staged)
    assert caught.value.status == 413 and pulled == [] and stored(storage) == {}


def pdf_with(**options) -> bytes:
    return pdf_bytes(**options)


ACTIVE_PDFS = {
    'javascript': pdf_with(catalog=b'/Names << /JavaScript 5 0 R >> ',
                           objects=(b'<< /Names [(x) 6 0 R] >>', b'<< /S /JavaScript /JS (app.alert(1)) >>')),
    'open_action': pdf_with(catalog=b'/OpenAction 5 0 R ', objects=(b'<< /S /JavaScript /JS (app.alert(1)) >>',)),
    'launch': pdf_with(catalog=b'/OpenAction << /S /Launch /F (calc.exe) >> '),
    'additional_actions': pdf_with(catalog=b'/AA << /WC 5 0 R >> ', objects=(b'<< /S /GoTo /D [3 0 R /Fit] >>',)),
    'embedded_file': pdf_with(catalog=b'/Names << /EmbeddedFiles 5 0 R >> ', objects=(b'<< /Names [] >>',)),
    'rich_media': pdf_with(objects=(b'<< /Type /Annot /Subtype /RichMedia /Rect [0 0 1 1] >>',)),
    # Hex-escaped names (#41 = 'A', #61 = 'a', #53 = 'S') hide /OpenAction and /JavaScript from a byte search; the
    # parsed structure still shows them.
    'escaped_name': pdf_with(catalog=b'/Open#41ction 5 0 R ', objects=(b'<< /S /J#61vaScript /J#53 (app.alert(1)) >>',)),
    # An object outside the cross-reference table: the parser ignores it, a repairing viewer may not.
    'object_outside_xref': pdf_with(comment=b'99 0 obj\n<< /S /Launch /F (calc.exe) >>\nendobj\n'),
    # The same between two streams: skipping stream bodies must stop at each body's own `endstream`.
    'object_between_streams': pdf_with(tail=b'99 0 obj\n<< /S /Launch /F (calc.exe) >>\nendobj\n'
                                            b'100 0 obj\n<< /Length 4 >>\nstream\nabcd\nendstream\nendobj\n'),
}


def image_stream(data: bytes, *, compressed: bool) -> bytes:
    """An 8-bit grey image XObject holding `data` as pixels; compressed means a stored-block deflate stream."""
    body = zlib.compress(data, 0) if compressed else data
    side = int(len(data) ** 0.5)
    return (b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 %s'
            b'/Length %d >>\nstream\n' % (side, len(data) // side, b'/Filter /FlateDecode ' if compressed else b'', len(body))
            + body + b'\nendstream')


def noise(size: int) -> bytes:
    """Deterministic high-entropy bytes, like compressed or scanned image data."""
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(counter.to_bytes(8, 'big')).digest()
        counter += 1
    return bytes(out[:size])


TOKENS = b'/JS /AA\n/OpenAction /Launch(/JavaScript<</EmbeddedFiles[/RichMedia%'


@pytest.mark.parametrize('compressed', [False, True])
def test_stream_data_that_happens_to_look_like_pdf_actions_is_accepted(client, storage, compressed):
    """Pixel or deflate data is arbitrary bytes: a token-like sequence inside a stream body is not active content
    (the raw scan skips stream bodies; the parsed objects are still searched)."""
    from app.documents.validation import ACTIVE_TOKEN, MARKUP
    pixels = noise(2 * MIB) + TOKENS + noise(64 * 1024)
    assert ACTIVE_TOKEN.search(pixels) and not MARKUP.search(pixels)
    content = pdf_bytes(resources=b'/XObject << /Im1 5 0 R >> ', objects=(image_stream(pixels, compressed=compressed),))
    assert len(content) > 2 * MIB
    document, _ = uploaded(client, preapproved(client), content=content)
    assert document['sha256'] == sha256(content) and list(stored(storage).values()) == [content]


@pytest.mark.parametrize('name', sorted(ACTIVE_PDFS))
def test_pdfs_with_active_content_are_415(client, storage, name):
    application = preapproved(client)
    refused(upload(client, application, content=ACTIVE_PDFS[name]), 415, 'MEDIA_NOT_ALLOWED')
    nothing_kept(client, storage, application)


DISAGREEING = {  # (content, filename, client MIME)
    'html_named_pdf': (HTML, 'statement.pdf', 'application/pdf'),
    'svg_named_png': (SVG, 'report.png', 'image/png'),
    'html_named_jpeg': (HTML, 'scan.jpg', 'image/jpeg'),
    'png_bytes_named_pdf': (png_bytes(), 'statement.pdf', 'application/pdf'),
    'pdf_bytes_named_png': (pdf_bytes(), 'report.png', 'image/png'),
    'jpeg_bytes_as_png': (jpeg_bytes(), 'report.png', 'image/png'),
    'pdf_with_png_mime': (pdf_bytes(), 'statement.pdf', 'image/png'),
    'pdf_with_html_mime': (pdf_bytes(), 'statement.pdf', 'text/html'),
    'png_with_octet_stream': (png_bytes(), 'report.png', 'application/octet-stream'),
    'html_file': (HTML, 'page.html', 'text/html'),
    'svg_file': (SVG, 'image.svg', 'image/svg+xml'),
    'executable': (b'MZ\x90\x00' + b'\x00' * 60, 'tool.exe', 'application/octet-stream'),
    'zip_archive': (b'PK\x03\x04' + b'\x00' * 26, 'bundle.zip', 'application/zip'),
    'no_extension': (pdf_bytes(), 'statement', 'application/pdf'),
    'double_extension': (pdf_bytes(), 'statement.pdf.exe', 'application/pdf'),
}
POLYGLOTS = {
    'pdf_with_html_comment': pdf_bytes(comment=b'%<html><body><script>alert(1)</script></body></html>\n'),
    'pdf_with_trailing_zip': pdf_bytes() + b'PK\x03\x04' + b'\x00' * 26,
    'pdf_with_trailing_html': pdf_bytes() + b'<html><script>alert(1)</script></html>',
    'png_with_script_after_iend': png_bytes() + b'<script>alert(1)</script>',
    'png_with_trailing_zip': png_bytes() + b'PK\x03\x04' + b'\x00' * 26,
    'png_with_html_text_chunk': png_bytes(extra_chunks=(png_chunk(b'tEXt', b'Comment\x00<html><script>alert(1)</script>'),)),
    'jpeg_with_trailing_zip': jpeg_bytes() + b'PK\x03\x04' + b'\x00' * 26,
}


@pytest.mark.parametrize('name', sorted(DISAGREEING))
def test_disallowed_or_disagreeing_types_are_415(client, storage, name):
    application = preapproved(client)
    content, filename, mime = DISAGREEING[name]
    refused(upload(client, application, content=content, filename=filename, mime=mime), 415, 'MEDIA_NOT_ALLOWED')
    nothing_kept(client, storage, application)


@pytest.mark.parametrize('name', sorted(POLYGLOTS))
def test_polyglots_and_appended_payloads_are_415(client, storage, name):
    application = preapproved(client)
    kind = 'pdf' if name.startswith('pdf') else 'png' if name.startswith('png') else 'jpeg'
    refused(upload(client, application, content=POLYGLOTS[name], kind=kind), 415, 'MEDIA_NOT_ALLOWED')
    nothing_kept(client, storage, application)


def encrypted_pdf() -> bytes:
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf_bytes())))
    writer.encrypt('demo-password', algorithm='RC4-128')
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


INVALID = {  # (content, kind): an allowed type by name, MIME and magic, but not a usable file
    'empty_pdf': (b'', 'pdf'),
    'empty_png': (b'', 'png'),
    'truncated_pdf': (pdf_bytes()[:-40], 'pdf'),
    'pdf_header_only': (b'%PDF-1.4\n%garbage\n', 'pdf'),
    'pdf_without_pages': (pdf_bytes(pages=False), 'pdf'),
    'encrypted_pdf': (encrypted_pdf(), 'pdf'),
    'truncated_png': (png_bytes()[:-20], 'png'),
    'png_signature_only': (b'\x89PNG\r\n\x1a\n', 'png'),
    'truncated_jpeg': (jpeg_bytes()[: len(jpeg_bytes()) // 2], 'jpeg'),
    'jpeg_markers_only': (b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9', 'jpeg'),
}


@pytest.mark.parametrize('name', sorted(INVALID))
def test_empty_truncated_or_unparseable_files_are_422(client, storage, name):
    application = preapproved(client)
    content, kind = INVALID[name]
    refused(upload(client, application, content=content, kind=kind), 422, 'FILE_INVALID')
    nothing_kept(client, storage, application)


def test_an_image_with_an_excessive_pixel_count_is_422(client, storage):
    """The PNG header claims 20000 x 20000 pixels: decoding it would need gigabytes, so it is refused unparsed."""
    import struct
    header = png_chunk(b'IHDR', struct.pack('>IIBBBBB', 20_000, 20_000, 8, 2, 0, 0, 0))
    bomb = b'\x89PNG\r\n\x1a\n' + header + png_chunk(b'IDAT', b'x\x9c\x03\x00\x00\x00\x00\x01') + png_chunk(b'IEND', b'')
    application = preapproved(client)
    refused(upload(client, application, content=bomb, kind='png'), 422, 'FILE_INVALID')
    nothing_kept(client, storage, application)


def bilevel_png(width: int, height: int) -> bytes:
    """A complete, valid one-bit grey PNG (small on disk, `width x height` pixels when decoded)."""
    import struct
    rows = (b'\x00' + b'\x00' * ((width + 7) // 8)) * height
    return (b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0))
            + png_chunk(b'IDAT', zlib.compress(rows, 9)) + png_chunk(b'IEND', b''))


@pytest.mark.parametrize('width,height', [(7_000, 7_000), (10_000, 9_500)])  # 49 MP and 95 MP, both decodable
def test_a_valid_image_above_40_megapixels_is_422_without_a_warning(client, storage, recwarn, width, height):
    """The 40 MP budget, not Pillow's decompression-bomb guard (a warning from 89 MP), refuses these."""
    application = preapproved(client)
    refused(upload(client, application, content=bilevel_png(width, height), kind='png'), 422, 'FILE_INVALID')
    nothing_kept(client, storage, application)
    assert [str(warning.message) for warning in recwarn] == []


def test_an_image_exactly_at_the_pixel_budget_is_accepted(client, storage):
    document, _ = uploaded(client, preapproved(client), content=bilevel_png(8_000, 5_000), kind='png')  # 40 MP
    assert document['media_type'] == 'image/png' and len(stored(storage)) == 1


LONG = 'х' * 300 + '.pdf'
NAMES = {  # raw upload name bytes → stored original name (paths ignored, control/format characters removed)
    b'../../etc/passwd.pdf': 'passwd.pdf',
    b'..\\..\\Windows\\win.pdf': 'win.pdf',
    b'C:\\Users\\demo\\statement.pdf': 'statement.pdf',
    b'/var/lib/secret/statement.pdf': 'statement.pdf',
    'Выписка «сентябрь» 2026.pdf'.encode(): 'Выписка «сентябрь» 2026.pdf',
    b'bad\tname\x07\x1b.pdf': 'badname.pdf',
    b'\x00null.pdf': 'null.pdf',
    'rtl\u202efdp.pdf'.encode(): 'rtlfdp.pdf',
    'next\u0085line.pdf'.encode(): 'nextline.pdf',
    b'quote\\"and;semi.pdf': 'quote"and;semi.pdf',
    b'%0D%0Aencoded.pdf': '%0D%0Aencoded.pdf',
    LONG.encode(): 'х' * 196 + '.pdf',
}
ATTR_CHARS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$&+-.^_`|~%')


@pytest.mark.parametrize('raw', sorted(NAMES))
def test_upload_names_never_reach_storage_and_downloads_carry_a_safe_disposition(client, storage, raw):
    from urllib.parse import unquote
    from document_helpers import form_fields, raw_upload
    application = preapproved(client)
    response = raw_upload(client, application, form_fields(application) + [(b'file', raw, pdf_bytes(), b'application/pdf')])
    assert response.status_code == 201, response.text
    document = response.json()['document']
    expected = NAMES[raw]
    assert document['original_name'] == expected
    (row,) = document_rows(client)
    assert list(stored(storage)) == [row.storage_key] and set(row.storage_key) <= HEX_KEY
    response = download(client, application, document)
    assert response.status_code == 200 and response.content == pdf_bytes()
    disposition = response.headers['content-disposition']
    assert disposition.startswith('attachment; filename="') and '\r' not in disposition and '\n' not in disposition
    fallback, extended = disposition[len('attachment; filename="'):].split('"; filename*=UTF-8\'\'')
    assert fallback.isascii() and fallback.isprintable() and not set(fallback) & set('"\\/;') and fallback.endswith('.pdf')
    assert set(extended) <= ATTR_CHARS and unquote(extended, encoding='utf-8', errors='strict') == expected


FORM_ERRORS = {  # multipart parts beside a valid file part
    'no_file_part': ('drop_file', []),
    'file_as_plain_field': ('drop_file', [(b'file', None, pdf_bytes(), None)]),
    'empty_filename': ('drop_file', [(b'file', b'', pdf_bytes(), b'application/pdf')]),
    'no_document_type': ('drop_type', []),
    'unknown_document_type': ('drop_type', [(b'document_type', None, b'PASSPORT', None)]),
    'version_not_a_number': ('drop_version', [(b'version', None, b'abc', None)]),
    'version_zero': ('drop_version', [(b'version', None, b'0', None)]),
    'duplicate_version': ('keep', [(b'version', None, b'1', None)]),
    'unknown_field': ('keep', [(b'status', None, b'ACCEPTED', None)]),
    'server_owned_field': ('keep', [(b'verified_value_rub', None, b'5000000', None)]),
}


@pytest.mark.parametrize('name', sorted(FORM_ERRORS))
def test_malformed_upload_forms_are_422_validation_errors(client, storage, name):
    from document_helpers import form_fields, raw_upload
    application = preapproved(client)
    drop, extra = FORM_ERRORS[name]
    parts = form_fields(application) + [(b'file', b'statement.pdf', pdf_bytes(), b'application/pdf')]
    dropped = {'drop_file': b'file', 'drop_type': b'document_type', 'drop_version': b'version'}.get(drop)
    parts = [part for part in parts if part[0] != dropped] + extra
    refused(raw_upload(client, application, parts), 422, 'VALIDATION_ERROR')
    nothing_kept(client, storage, application)


@pytest.mark.parametrize('headers', [b'X-Padding: ' + b'a' * 5000 + b'\r\n',  # one header line above 4 KiB
                                     b''.join(b'X-Extra-%d: 1\r\n' % number for number in range(8)),  # 10 headers
                                     b'X-Same: 1\r\n' * 7])  # 9 headers, one name repeated
def test_oversized_or_too_many_part_headers_are_422(client, storage, headers):
    from document_helpers import BOUNDARY, form_fields, multipart
    application = preapproved(client)
    body, content_type = multipart(form_fields(application))
    file_part = (b'--' + BOUNDARY.encode() + b'\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n'
                 b'Content-Type: application/pdf\r\n' + headers + b'\r\n' + pdf_bytes() + b'\r\n')
    body = body.replace(b'--' + BOUNDARY.encode() + b'--\r\n', file_part + b'--' + BOUNDARY.encode() + b'--\r\n')
    response = client.post(docs_url(application), content=body,
                           headers={'content-type': content_type, 'Idempotency-Key': uuid4().hex})
    refused(response, 422, 'VALIDATION_ERROR')
    nothing_kept(client, storage, application)


def test_the_intake_caps_part_headers_itself(storage):
    """The limit is the intake's own, whatever the parser library's defaults are."""
    from app.documents.intake import HEADER_BYTES, receive_upload
    from app.documents.storage import DocumentStorage
    from app.errors import ApiError
    head = b'--b\r\nContent-Disposition: form-data; name="document_type"\r\nX-Padding: '
    with pytest.raises(ApiError) as caught, DocumentStorage(storage).staged() as staged:
        receive_upload(iter([head, b'a' * HEADER_BYTES, b'\r\n\r\nBANK_STATEMENT\r\n--b--\r\n']),
                       {'content-type': 'multipart/form-data; boundary=b'}, staged)
    assert (caught.value.status, caught.value.code) == (422, 'VALIDATION_ERROR') and stored(storage) == {}


def test_two_files_a_json_body_or_a_missing_key_are_refused(client, storage):
    application = preapproved(client)
    two = client.post(docs_url(application), headers={'Idempotency-Key': uuid4().hex},
                      data={'document_type': 'BANK_STATEMENT', 'version': str(application['version'])},
                      files=[('file', ('a.pdf', pdf_bytes(), 'application/pdf')), ('file', ('b.pdf', pdf_bytes(), 'application/pdf'))])
    refused(two, 422, 'VALIDATION_ERROR')
    as_json = client.post(docs_url(application), headers={'Idempotency-Key': uuid4().hex},
                          json={'document_type': 'BANK_STATEMENT', 'version': application['version']})
    refused(as_json, 422, 'VALIDATION_ERROR')
    no_key = client.post(docs_url(application), data={'document_type': 'BANK_STATEMENT', 'version': str(application['version'])},
                         files={'file': ('a.pdf', pdf_bytes(), 'application/pdf')})
    refused(no_key, 422, 'VALIDATION_ERROR')
    nothing_kept(client, storage, application)


def test_a_document_type_outside_the_product_checklist_is_422(client, storage):
    application = preapproved(client)  # unsecured: no collateral documents
    refused(upload(client, application, 'COLLATERAL_VALUATION'), 422, 'DOCUMENT_TYPE_NOT_ALLOWED')
    nothing_kept(client, storage, application)


def test_an_upload_that_fails_after_its_file_was_placed_leaves_no_file(client, storage, monkeypatch):
    """The bytes move into place only after the row is flushed, and the rollback of the failed request removes them."""
    from fastapi.testclient import TestClient
    from app import idempotency
    from app.main import app

    def broken(*_args, **_kwargs):
        raise RuntimeError('simulated failure after the file was placed')

    application = preapproved(client)
    monkeypatch.setattr(idempotency, 'remember', broken)
    with TestClient(app, headers={'origin': client.headers['origin']}, cookies=client.cookies,
                    raise_server_exceptions=False) as session:
        response = upload(session, application)
    assert response.status_code == 500 and response.json()['error']['code'] == 'INTERNAL_ERROR'
    nothing_kept(client, storage, application)


def test_a_rolled_back_delete_keeps_the_bytes_and_a_committed_one_removes_them(client, storage, monkeypatch):
    from fastapi.testclient import TestClient
    from app import idempotency
    from app.main import app
    from document_helpers import delete
    application = preapproved(client)
    document, application = uploaded(client, application)
    content = dict(stored(storage))
    original = idempotency.remember
    monkeypatch.setattr(idempotency, 'remember', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('simulated')))
    with TestClient(app, headers={'origin': client.headers['origin']}, cookies=client.cookies,
                    raise_server_exceptions=False) as session:
        assert delete(session, application, document).status_code == 500
    assert stored(storage) == content and document_rows(client)[0].status == 'UPLOADED'
    monkeypatch.setattr(idempotency, 'remember', original)
    response = delete(client, application, document)
    assert response.status_code == 200, response.text
    assert stored(storage) == {} and document_rows(client)[0].status == 'DELETED'
    refused(download(client, application, document), 404, 'DOCUMENT_NOT_FOUND')


def test_a_savepoint_release_settles_no_files(client, storage):
    """after_commit also fires when a SAVEPOINT is released; only the outermost transaction may settle files."""
    from sqlalchemy import text
    from app.documents.storage import DocumentStorage
    private = DocumentStorage(storage)
    created, deleted = 'a' * 32, 'b' * 32
    storage.mkdir(parents=True, exist_ok=True)
    (storage / deleted).write_bytes(b'kept unless the deletion commits')
    with client.app.state.test_factory() as db:
        db.execute(text('SELECT 1'))
        with private.staged() as staged:
            staged.write(pdf_bytes())
            private.place(db, staged, created)
        private.remove_after_commit(db, deleted)
        db.begin_nested().commit()  # a savepoint release
        assert sorted(stored(storage)) == [created, deleted]
        db.rollback()  # the outermost transaction does not commit
    assert list(stored(storage)) == [deleted]
    with client.app.state.test_factory() as db:
        db.execute(text('SELECT 1'))
        private.remove_after_commit(db, deleted)
        db.begin_nested().commit()
        assert list(stored(storage)) == [deleted]
        db.commit()
    assert stored(storage) == {}
