"""Receives a multipart/form-data upload within fixed limits, streaming the one file part straight into a private
staging file: the body is never buffered whole and no system temporary file is used.

Limits: the file part holds at most MAX_FILE_BYTES (20 MiB); one byte more is 413 FILE_TOO_LARGE, detected while
reading. The whole body may exceed that only by ENVELOPE_BYTES (boundaries, part headers, two short fields), and a
declared Content-Length above the body limit is refused before anything is read. Each part may carry at most
HEADER_COUNT headers of at most HEADER_BYTES (name plus value). The form has exactly the parts `file` (with a file
name), `document_type` and `version`, once each; anything else is 422 VALIDATION_ERROR.
"""
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
import anyio
from fastapi import Request
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from ..errors import ApiError
from .models import MAX_FILE_BYTES
from .storage import StagedFile

ENVELOPE_BYTES = 64 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + ENVELOPE_BYTES
FIELD_BYTES = 256
HEADER_BYTES = 4096  # one part header, name plus value
HEADER_COUNT = 8  # headers per part
FIELDS = ('document_type', 'version')
FILE = 'file'


def too_large() -> ApiError:
    return ApiError(413, 'FILE_TOO_LARGE', 'Файл больше 20 МБ. Загрузите файл размером до 20 МБ.')


def invalid_form(fields: dict[str, str]) -> ApiError:
    return ApiError(422, 'VALIDATION_ERROR', 'Проверьте заполненные поля', fields=fields)


@dataclass(frozen=True)
class UploadForm:
    fields: dict[str, str]
    filename: str  # as sent (paths and control characters are dealt with by validation.safe_name)
    content_type: str  # the client's MIME type for the file part, lower-case, without parameters


class _Parts:
    """python-multipart callbacks: file data goes to the staging file, field values are kept (bounded)."""

    def __init__(self, staged: StagedFile):
        self.staged = staged
        self.fields: dict[str, str] = {}
        self.filename: str | None = None
        self.content_type = ''
        self.ended = False
        self._headers: dict[bytes, bytes] = {}
        self._header_count = 0
        self._header_name, self._header_value = bytearray(), bytearray()
        self._part: str | None = None
        self._value = bytearray()

    def on_part_begin(self) -> None:
        self._headers, self._header_count, self._part, self._value = {}, 0, None, bytearray()

    def _header_room(self) -> None:
        if len(self._header_name) + len(self._header_value) > HEADER_BYTES:
            raise invalid_form({FILE: 'Слишком длинный заголовок части формы'})

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]
        self._header_room()

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]
        self._header_room()

    def on_header_end(self) -> None:
        self._headers[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name, self._header_value = bytearray(), bytearray()
        self._header_count += 1
        if self._header_count > HEADER_COUNT:
            raise invalid_form({FILE: 'Слишком много заголовков части формы'})

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._headers.get(b'content-disposition', b''))
        name = options.get(b'name', b'').decode('utf-8', 'replace')
        if b'filename' in options:
            if name != FILE or self.filename is not None:
                raise invalid_form({FILE: 'Отправьте один файл в поле file'})
            self.filename = options[b'filename'].decode('utf-8', 'replace')
            if not self.filename:
                raise invalid_form({FILE: 'Выберите файл'})
            self.content_type = parse_options_header(self._headers.get(b'content-type', b''))[0].decode('latin-1')
            self._part = FILE
        elif name in FIELDS and name not in self.fields:
            self._part = name
        else:
            raise invalid_form({name or 'form': 'Неизвестное или повторное поле формы'})

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._part == FILE:
            if self.staged.size + len(chunk) > MAX_FILE_BYTES:
                raise too_large()
            self.staged.write(chunk)
        elif len(self._value) + len(chunk) > FIELD_BYTES:
            raise invalid_form({self._part: 'Слишком длинное значение'})
        else:
            self._value += chunk

    def on_part_end(self) -> None:
        if self._part != FILE:
            self.fields[self._part] = self._value.decode('utf-8', 'replace')

    def on_end(self) -> None:
        self.ended = True

    def callbacks(self) -> dict:
        return {name: getattr(self, name) for name in ('on_part_begin', 'on_header_field', 'on_header_value', 'on_header_end',
                                                       'on_headers_finished', 'on_part_data', 'on_part_end', 'on_end')}


def receive_upload(chunks: Iterable[bytes], headers: Mapping[str, str], staged: StagedFile) -> UploadForm:
    """Parses the body from `chunks` into `staged` (the file part) and the plain fields; raises 413/422."""
    content_type, options = parse_options_header(headers.get('content-type', ''))
    boundary = options.get(b'boundary')
    if content_type != b'multipart/form-data' or not boundary:
        raise invalid_form({FILE: 'Отправьте файл формой multipart/form-data'})
    declared = headers.get('content-length', '')
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_large()
    parts = _Parts(staged)
    # The library's own limits are only a looser backstop: the intake's limits above apply first.
    parser = MultipartParser(boundary, parts.callbacks(), max_header_count=2 * HEADER_COUNT, max_header_size=2 * HEADER_BYTES)
    received = 0
    try:
        for chunk in chunks:
            received += len(chunk)
            if received > MAX_BODY_BYTES:
                raise too_large()
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError:
        raise invalid_form({FILE: 'Не удалось прочитать форму с файлом'}) from None
    finally:
        close = getattr(chunks, 'close', None)
        if close is not None:
            close()
    staged.finish()
    if not parts.ended or parts.filename is None:
        raise invalid_form({FILE: 'Выберите файл'})
    missing = {name: 'Обязательное поле' for name in FIELDS if name not in parts.fields}
    if missing:
        raise invalid_form(missing)
    return UploadForm(parts.fields, parts.filename, parts.content_type)


def request_chunks(request: Request) -> Iterator[bytes]:
    """The request body as a synchronous iterator for a sync endpoint (an anyio worker thread): each chunk is awaited
    on the event loop, so reading stops wherever the caller stops."""
    stream = request.stream()

    async def pull() -> bytes | None:
        try:
            return await stream.__anext__()
        except StopAsyncIteration:
            return None

    try:
        while (chunk := anyio.from_thread.run(pull)) is not None:
            if chunk:
                yield chunk
    finally:
        anyio.from_thread.run(stream.aclose)
