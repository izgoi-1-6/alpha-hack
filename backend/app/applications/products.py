"""Product policies for applications, resolved only from the demo catalog's `products`.

Never from the research archive: three archive entries reuse supported product ids with different, unverified
numbers and `can_apply=false`. Lookups read CATALOG at call time, so a catalog/rules version change is seen at once.
"""
from ..recommendations.catalog import CATALOG
from .models import Application


def current_product(product_id: str) -> dict | None:
    return next((product for product in CATALOG['products'] if product['id'] == product_id), None)


def current_versions() -> tuple[str, str]:
    return CATALOG['catalog_version'], CATALOG['rules_version']


def is_current(catalog_version: str, rules_version: str) -> bool:
    return (catalog_version, rules_version) == current_versions()


def application_product(application: Application) -> dict | None:
    """The policy pinned at submission; for a draft, the live policy of its product (None if withdrawn)."""
    if application.submitted_input_snapshot:
        return application.submitted_input_snapshot['product']
    return current_product(application.product_id)
