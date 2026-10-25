"""The runtime model, the configured file paths and the error that lists every configuration problem."""
from dataclasses import dataclass
import os
from pathlib import Path
from .rules import normalize_region

DATA = Path(__file__).resolve().parents[3] / 'data'
DEFAULT_CATALOG_PATH = DATA / 'credit_catalog.json'
DEFAULT_POLICY_PATH = DATA / 'demo-policy.json'


class ConfigError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__('\n'.join(self.errors))


class Problems(list):
    def add(self, path: str, message: str) -> None:
        self.append(f'{path}: {message}')


@dataclass(frozen=True)
class ProductConfig:
    """Products and overlays are plain JSON dicts: they are served by GET /catalog and pinned in snapshots as they are,
    so consumers read them and never change them."""
    catalog_version: str  # stamped: catalog_version+sha8
    rules_version: str  # stamped: rules_version+sha8
    key_rate: dict
    amount_slider: dict
    products: tuple[dict, ...]  # card products in catalog order
    overlays: tuple[dict, ...]
    ranking: dict
    payment_estimate_term_months: int
    region_normalization: tuple[str, ...]

    def product(self, product_id: str) -> dict | None:
        return next((product for product in self.products if product['id'] == product_id), None)

    def region_key(self, text: str) -> str:
        return normalize_region(text, self.region_normalization)

    def public(self) -> dict:
        """The GET /catalog body."""
        return {'catalog_version': self.catalog_version, 'rules_version': self.rules_version, 'key_rate': self.key_rate,
                'amount_slider': self.amount_slider, 'products': list(self.products), 'overlays': list(self.overlays)}


def configured_paths() -> tuple[Path, Path]:
    """The catalog and policy the app loads: `CREDIT_CATALOG_PATH` / `DEMO_POLICY_PATH`, else the data files."""
    return (Path(os.getenv('CREDIT_CATALOG_PATH', DEFAULT_CATALOG_PATH)),
            Path(os.getenv('DEMO_POLICY_PATH', DEFAULT_POLICY_PATH)))
