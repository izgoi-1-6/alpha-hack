"""What may be stored: upload names and file content («Демонстрационная проверка документов» — a structural demo
check, not antivirus scanning or document verification).

Only PDF, JPEG and PNG. The extension of the sanitized name and the client's MIME type must name the same allowed
type and the magic bytes must agree, else 415 MEDIA_NOT_ALLOWED; an empty file of an allowed type is 422
FILE_INVALID. HTML/SVG/script markup anywhere is 415. The content must then parse with a maintained parser (pypdf in
strict mode with at least one page and no encryption; Pillow verify, then a full decode within a pixel budget), else
422 FILE_INVALID. Data after the format's end (PNG IEND, JPEG EOI, PDF %%EOF) and PDF active content (JavaScript, JS,
OpenAction, AA, Launch, EmbeddedFiles, RichMedia, also hex-escaped or inside object streams) are 415. Active names are
found in the parsed objects and, for objects outside the cross-reference table, as raw tokens in the bytes outside the
data of the stream objects the parser read (compressed or binary stream data matches such tokens by chance, roughly
0.8% per MiB). Every search is linear in the file size.
"""
from dataclasses import dataclass
import io
import re
import unicodedata
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, StreamObject, read_object
from ..errors import ApiError


@dataclass(frozen=True)
class FileType:
    media_type: str
    extensions: tuple[str, ...]
    magic: bytes


PDF = FileType('application/pdf', ('pdf',), b'%PDF-')
JPEG = FileType('image/jpeg', ('jpg', 'jpeg'), b'\xff\xd8\xff')
PNG = FileType('image/png', ('png',), b'\x89PNG\r\n\x1a\n')
TYPES = (PDF, JPEG, PNG)
MAX_NAME_CHARS = 200
MAX_PIXELS = 40_000_000  # an image above this is refused (422) from its header, before anything is decoded
# The explicit MAX_PIXELS check replaces Pillow's decompression-bomb guard, which would warn from 89 MP and raise only
# from 179 MP: every oversized image gets the same 422 and no warning. Nothing else in the process uses Pillow.
Image.MAX_IMAGE_PIXELS = None
# Searched in the lower-cased bytes (ASCII only, as re.IGNORECASE on bytes, at half its worst-case cost).
MARKUP = re.compile(rb'<(?:script|html|svg|iframe|object|embed|body|!doctype)[\s/>]|javascript:')
ACTIVE_NAMES = frozenset({'/JavaScript', '/JS', '/OpenAction', '/AA', '/Launch', '/EmbeddedFiles', '/RichMedia'})
ACTIVE_TOKEN = re.compile(rb'/(?:JavaScript|JS|OpenAction|AA|Launch|EmbeddedFiles|RichMedia)(?=[\s()<>\[\]{}/%]|$)')
PDF_WHITESPACE = b'\x00\t\n\f\r '  # what pypdf skips between a stream's data and `endstream`
ENDSTREAM = b'endstream'
# How far a stream's data is located exactly: at most this many whitespace bytes between the data and `endstream`, and
# spaces between `stream` and its end of line (pypdf allows any number of either). Beyond it, the span is the data's
# length just before `endstream`: still inside the data and the whitespace after it.
STREAM_GAP = 32
PDF_END = re.compile(rb'%%EOF[\r\n\t\f\x00 ]*\Z')
PNG_END = b'\x00\x00\x00\x00IEND\xaeB`\x82'
JPEG_END = b'\xff\xd9'


def not_allowed(message: str) -> ApiError:
    return ApiError(415, 'MEDIA_NOT_ALLOWED', message + ' Можно загрузить только PDF, JPEG или PNG.')


def invalid_file(message: str) -> ApiError:
    return ApiError(422, 'FILE_INVALID', message)


def safe_name(raw: str) -> str:
    """The name to store and show: the last path segment only, NFC, without control or format characters (bidi
    overrides included), whitespace collapsed, at most 200 characters with the extension kept. Never a path."""
    name = unicodedata.normalize('NFC', re.split(r'[/\\]', raw)[-1])
    name = ' '.join(''.join(char for char in name if not unicodedata.category(char).startswith('C')).split())
    if len(name) > MAX_NAME_CHARS:
        stem, dot, extension = name.rpartition('.')
        keep = len(extension) + 1 if dot and len(extension) <= 10 else 0
        name = (stem[:MAX_NAME_CHARS - keep] + dot + extension) if keep else name[:MAX_NAME_CHARS]
    if not name:
        raise ApiError(422, 'VALIDATION_ERROR', 'Проверьте заполненные поля', fields={'file': 'Укажите имя файла'})
    return name


def file_type(name: str, client_type: str) -> FileType:
    extension = name.rpartition('.')[2].lower() if '.' in name else ''
    kind = next((kind for kind in TYPES if extension in kind.extensions), None)
    if kind is None:
        raise not_allowed('Тип файла не поддерживается.')
    if client_type != kind.media_type:
        raise not_allowed('Тип файла не совпадает с его расширением.')
    return kind


def inspect(name: str, client_type: str, data: bytes) -> str:
    """The stored media type of an acceptable file; raises 415/422 otherwise."""
    kind = file_type(name, client_type)
    if not data:
        raise invalid_file('Файл пустой.')
    if not data.startswith(kind.magic):
        raise not_allowed('Содержимое файла не соответствует его типу.')
    if MARKUP.search(data.lower()):
        raise not_allowed('Файл содержит HTML-разметку или сценарий.')
    if kind is PDF:
        check_pdf(data)
    else:
        check_image(data, 'JPEG' if kind is JPEG else 'PNG', JPEG_END if kind is JPEG else PNG_END)
    return kind.media_type


def pdf_names(reader: PdfReader) -> set[str]:
    """Every name used as a key or value in the trailer and every indirect object of the file (object streams
    included); pypdf decodes #xx escapes."""
    names: set[str] = set()
    seen: set[tuple[int, int]] = set()
    pending: list = [reader.trailer]
    pending += [IndirectObject(number, generation, reader) for generation, numbers in reader.xref.items() for number in numbers]
    pending += [IndirectObject(number, 0, reader) for number in reader.xref_objStm]
    while pending:
        item = pending.pop()
        if isinstance(item, IndirectObject):
            if (item.idnum, item.generation) in seen:
                continue
            seen.add((item.idnum, item.generation))
            item = item.get_object()
        if isinstance(item, DictionaryObject):  # raw dict access: entries stay unresolved, subclasses cannot reinterpret
            names.update(str(key) for key in dict.keys(item))
            pending.extend(dict.values(item))
        elif isinstance(item, ArrayObject):
            pending.extend(item)
        elif isinstance(item, NameObject):
            names.add(str(item))
    return names


def stream_spans(reader: PdfReader, data: bytes) -> list[tuple[int, int]]:
    """Where the data of each stream object in the cross-reference table lies in the file, as the parser read it.

    The object is read again from its offset (after the first read, pypdf's xref holds the offset it actually used),
    which leaves the reader just after the `endstream` that closed the data. The data, as many bytes as the parser
    read, ends at that keyword or within the whitespace before it, so every span lies inside the object's own data
    and the whitespace after it. Text that merely looks like a stream (in a comment, in a string, in a dictionary or
    outside every object) is never skipped. Linear: each stream object is read once more and located in constant
    time. (pypdf keeps a stream's raw bytes in `_data`; the version is pinned.)"""
    source = io.BytesIO(data)
    spans = []
    for generation, numbers in reader.xref.items():
        for number, offset in numbers.items():
            if not isinstance(reader.get_object(IndirectObject(number, generation, reader)), StreamObject):
                continue
            source.seek(offset)
            reader.read_object_header(source)
            item = read_object(source, reader)
            end = source.tell() - len(ENDSTREAM)
            if isinstance(item, StreamObject) and data[end:end + len(ENDSTREAM)] == ENDSTREAM:
                spans.append(data_span(data, end, len(item._data)))
    return spans


def data_span(data: bytes, end: int, size: int) -> tuple[int, int]:
    """The `size` bytes of stream data closed by `endstream` at `end`: for the fewest whitespace bytes in between
    whose data starts right after a `stream` keyword, else the bytes just before `endstream`. Either never starts
    before the actual data (the true gap is always a candidate), so nothing before the data is ever skipped."""
    for gap in range(STREAM_GAP + 1):
        stop = end - gap
        if gap and data[stop] not in PDF_WHITESPACE:
            break
        if stop - size >= 0 and keyword_ends_at(data, stop - size):
            return stop - size, stop
    return end - size, end


def keyword_ends_at(data: bytes, position: int) -> bool:
    """Whether a `stream` keyword and its end of line end at `position` as pypdf reads them: `stream`, spaces, then
    LF, CR LF or a CR not followed by LF (spaces counted up to STREAM_GAP)."""
    if data[position - 1:position] == b'\n':
        eol = position - 2 if data[max(position - 2, 0):position - 1] == b'\r' else position - 1
    elif data[position - 1:position] == b'\r' and data[position:position + 1] != b'\n':
        eol = position - 1
    else:
        return False
    keyword = eol
    while keyword > eol - STREAM_GAP and data[keyword - 1:keyword] == b' ':
        keyword -= 1
    return data[max(keyword - 6, 0):keyword] == b'stream'


def without_spans(data: bytes, spans: list[tuple[int, int]]) -> bytes:
    """The bytes outside every span, with a space where each (merged) span was."""
    pieces, position = [], 0
    for start, stop in sorted(spans):
        if start > position:
            pieces.append(data[position:start])
        position = max(position, stop)
    pieces.append(data[position:])
    return b' '.join(pieces)


def check_pdf(data: bytes) -> None:
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise invalid_file('PDF защищён паролем: его содержимое нельзя проверить.')
        if len(reader.pages) < 1:
            raise invalid_file('В PDF нет страниц.')
        active = pdf_names(reader) & ACTIVE_NAMES
        spans = stream_spans(reader, data)
    except ApiError:
        raise
    except Exception:
        raise invalid_file('PDF повреждён или обрезан.') from None
    if active or ACTIVE_TOKEN.search(without_spans(data, spans)):
        raise not_allowed('PDF содержит активное содержимое (сценарии, автозапуск или вложенные файлы).')
    if not PDF_END.search(data[-1024:]):
        raise not_allowed('После окончания PDF есть посторонние данные.')


def check_image(data: bytes, image_format: str, end_marker: bytes) -> None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != image_format:
                raise invalid_file('Изображение не читается.')
            if image.width * image.height > MAX_PIXELS:
                raise invalid_file('Изображение слишком большое для проверки.')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except ApiError:
        raise
    except Exception:
        raise invalid_file('Изображение повреждено или обрезано.') from None
    if not data.endswith(end_marker):
        raise not_allowed('После окончания изображения есть посторонние данные.')
