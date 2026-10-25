"""`python -m app.products_config check [--catalog P] [--policy P]`: validate catalog/policy edits before a restart.

Exit 0 with a one-line summary, or 1 with every problem and its path. The defaults are the files the app loads
(`CREDIT_CATALOG_PATH` / `DEMO_POLICY_PATH`, else `data/`)."""
import argparse
from pathlib import Path
import sys
from .loader import load_config
from .model import ConfigError, configured_paths


def main(argv: list[str] | None = None) -> int:
    default_catalog, default_policy = configured_paths()
    parser = argparse.ArgumentParser(prog='python -m app.products_config', description='Validate the product catalog and policy.')
    parser.add_argument('command', choices=['check'])
    parser.add_argument('--catalog', default=default_catalog, type=Path)
    parser.add_argument('--policy', default=default_policy, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.catalog, args.policy)
    except ConfigError as error:
        print(f'Config errors ({len(error.errors)}) in {args.catalog} / {args.policy}:')
        for line in error.errors:
            print(f'  {line}')
        return 1
    overlays = len(config.overlays)
    print(f'OK: catalog {config.catalog_version}, rules {config.rules_version}, '
          f'{len(config.products)} products, {overlays} overlay{"" if overlays == 1 else "s"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
