"""Product terms for applications, resolved from the runtime product configuration (app.recommendations.catalog).

Lookups read the configuration at call time, so an edited catalog or policy (a new stamped version) is seen at once.
A submitted application reads the runtime product pinned in its submission snapshot instead.
"""
from ..recommendations import catalog
from .models import Application


def current_product(product_id: str) -> dict | None:
    return catalog.config().product(product_id)


def current_versions() -> tuple[str, str]:
    config = catalog.config()
    return config.catalog_version, config.rules_version


def is_current(catalog_version: str, rules_version: str) -> bool:
    return (catalog_version, rules_version) == current_versions()


def application_product(application: Application) -> dict | None:
    """The product pinned at submission; for a draft, the live product (None if it left the catalog)."""
    if application.submitted_input_snapshot:
        return application.submitted_input_snapshot['product']
    return current_product(application.product_id)


def collateral_required(product: dict) -> bool:
    """Whether the questionnaire, scoring, documents and the officer treat the application as secured. Until the
    application pins its own `secured` flag (required, or optional with declared collateral), only a product whose
    collateral mode is 'required' is secured; an optional pledge is not counted yet."""
    return product['collateral_mode'] == 'required'


def required_documents(product: dict) -> list[str]:
    """The policy's base documents, plus the collateral documents for a secured product."""
    return [*product['base_documents'], *(product['collateral_documents'] if collateral_required(product) else [])]
