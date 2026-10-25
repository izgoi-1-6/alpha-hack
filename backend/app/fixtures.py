"""The synthetic fixture file every local mock reads (registry, turnover, BKI, Госуслуги), and the whitelist lookup of a
company ИНН. No real source is ever called: an ИНН outside the file is REGISTRY_NOT_FOUND."""
import json
from pathlib import Path
from .errors import ApiError

DATA_PATH = Path(__file__).resolve().parents[2] / 'data' / 'demo-companies.json'
FIXTURES = json.loads(DATA_PATH.read_text())
SOURCES = {c['inn']: c for c in FIXTURES['companies']}


def registry_source(inn: str) -> dict:
    """The fixture of a whitelisted ИНН, or 422 REGISTRY_NOT_FOUND (nothing is persisted, no real registry call)."""
    source = SOURCES.get(inn)
    if source is None:
        raise ApiError(422, 'REGISTRY_NOT_FOUND', 'Компания не найдена в реестре. Проверьте ИНН или выберите компанию из списка.',
                       fields={'inn': 'Выберите ИНН из списка компаний'})
    return source
