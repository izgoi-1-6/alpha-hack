"""Product terms for applications: the runtime product (app.recommendations.catalog) and the facts an application is
decided under.

Before submission the terms follow the live product and the current answers: the application is secured when the
product requires collateral, or takes it optionally and a pledge is declared, and it then requires the policy's
collateral documents next to the base ones. Submission pins these facts — the runtime product with its effective terms,
`secured` and `required_documents` — into the submission snapshot, and every later reader (scoring on retry and after
an information response, R5, the documents checklist, the officer's bounds and requestable fields) reads the pinned
values, never the live product. A submitted application without them fails loudly.
"""
from dataclasses import dataclass
from ..recommendations import catalog
from .models import Application

PINNED = ('product', 'secured', 'required_documents')


@dataclass(frozen=True)
class Terms:
    product: dict  # the runtime product: effective amounts, terms, collateral mode, rate, payment model, policy values
    secured: bool
    required_documents: list[str]


def current_product(product_id: str) -> dict | None:
    return catalog.config().product(product_id)


def current_versions() -> tuple[str, str]:
    config = catalog.config()
    return config.catalog_version, config.rules_version


def is_current(catalog_version: str, rules_version: str) -> bool:
    return (catalog_version, rules_version) == current_versions()


def is_secured(product: dict, collateral) -> bool:
    """Collateral mode required, or optional with a declared pledge."""
    mode = product['collateral_mode']
    return mode == 'required' or (mode == 'optional' and isinstance(collateral, dict) and collateral.get('status') == 'declared')


def terms_for(product: dict, collateral) -> Terms:
    """The terms before submission: the live product with the pledge currently declared."""
    secured = is_secured(product, collateral)
    return Terms(product, secured, [*product['base_documents'], *(product['collateral_documents'] if secured else [])])


def pin(terms: Terms) -> dict:
    """The submission snapshot's pinned facts."""
    return {'product': terms.product, 'secured': terms.secured, 'required_documents': list(terms.required_documents)}


def pinned_terms(application: Application) -> Terms:
    snapshot = application.submitted_input_snapshot or {}
    missing = [key for key in PINNED if key not in snapshot]
    if missing:
        raise RuntimeError(f'application {application.id} ({application.status}) has no pinned {", ".join(missing)}')
    return Terms(snapshot['product'], snapshot['secured'], list(snapshot['required_documents']))


def application_terms(application: Application) -> Terms | None:
    """The pinned terms once submitted; before (a draft, or one cancelled unsubmitted) the live product with the current
    answers, or None when the product has left the catalog."""
    if application.submitted_at is not None:
        return pinned_terms(application)
    product = current_product(application.product_id)
    return None if product is None else terms_for(product, (application.answers or {}).get('collateral'))
