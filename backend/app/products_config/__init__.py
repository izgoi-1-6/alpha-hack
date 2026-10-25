"""The product configuration: `data/credit_catalog.json` (product facts) and `data/demo-policy.json` (demo decision
rules), validated together into the one runtime model every consumer reads.

The catalog is authoritative for amounts, terms, rates, purposes and eligibility. The policy fills a catalog `null`
(its per-product setting, else its default) and may tighten a stated value, never weaken it. Card products of the
policy's applyable kinds become runtime products; overlays become badges. `load_config` is pure: it reads the two
files and returns a ProductConfig, or raises ConfigError listing every problem with its path, for example
`items[alfa_factoring].amount.max: null, no policy fallback`. Versions are stamped `version+sha8(file bytes)`, so any
edit makes earlier snapshots and drafts stale. The app loads the configured paths once at start-up
(app.recommendations.catalog); `python -m app.products_config check [--catalog P] [--policy P]` validates edits.

Modules: rules (parsers, supported values), model (ProductConfig, ConfigError, paths), policy (policy-file and
slider checks), items (catalog items to runtime products and overlays), loader (load_config), __main__ (the CLI).
"""
from .loader import load_config
from .model import DEFAULT_CATALOG_PATH, DEFAULT_POLICY_PATH, ConfigError, ProductConfig, configured_paths
from .rules import PURPOSES, normalize_region, okved_class, okved_deny, parse_rate_formula

__all__ = ['DEFAULT_CATALOG_PATH', 'DEFAULT_POLICY_PATH', 'PURPOSES', 'ConfigError', 'ProductConfig', 'configured_paths',
           'load_config', 'normalize_region', 'okved_class', 'okved_deny', 'parse_rate_formula']
