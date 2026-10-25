"""The product configuration the app serves, loaded once at start-up from the configured catalog and policy files.

A broken catalog or policy stops the app with every problem and its path. Consumers call `config()` at use time (never
bind CONFIG at import), so a test can swap the module attribute for an edited configuration.
"""
from ..products_config import ProductConfig, configured_paths, load_config

CONFIG = load_config(*configured_paths())


def config() -> ProductConfig:
    return CONFIG


def public_catalog() -> dict:
    return config().public()
