import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / 'data'
CATALOG = json.loads((DATA / 'demo-products.json').read_text())
RESEARCH = json.loads((DATA / 'catalog.research.json').read_text())

def public_catalog() -> dict:
    return {'catalog_version': CATALOG['catalog_version'], 'rules_version': CATALOG['rules_version'],
            'notice': CATALOG['notice'], 'products': CATALOG['products'], 'research_items': RESEARCH['items']}
