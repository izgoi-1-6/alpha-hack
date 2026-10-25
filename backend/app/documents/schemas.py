"""Upload form fields and the upload's idempotency digest. Multipart has no JSON body, so the digest is the
document type, the version, the SHA-256 of the received bytes and the stored (sanitized) original name."""
import re
from ..schemas import StrictModel
from .intake import invalid_form
from .models import DOCUMENT_TYPES

VERSION = re.compile(r'[1-9][0-9]{0,8}')


class UploadDigest(StrictModel):
    document_type: str
    version: int
    sha256: str
    original_name: str


def upload_fields(fields: dict[str, str]) -> tuple[str, int]:
    """(document_type, version) from the form's plain fields; 422 VALIDATION_ERROR naming each bad field."""
    errors = {}
    if fields['document_type'] not in DOCUMENT_TYPES:
        errors['document_type'] = 'Выберите документ из перечня'
    if not VERSION.fullmatch(fields['version']):
        errors['version'] = 'Укажите текущую версию заявки'
    if errors:
        raise invalid_form(errors)
    return fields['document_type'], int(fields['version'])
