"""Catalog items to runtime products and overlays: enum membership, policy fallbacks for nulls (a policy setting may
only tighten a stated value), rates from the key-rate formula, explanation texts and eligibility."""
from decimal import Decimal
from .model import Problems
from .rules import COLLATERAL_MODES, PURPOSES, conditions, is_count, okved_deny, parse_rate_formula, plain, text_present


class ItemBuilder:
    def __init__(self, catalog: dict, policy: dict, problems: Problems, *, key_rate: Decimal | None,
                 overlay_items: dict, card_ids: list[str]):
        self.enums, self.policy, self.problems, self.key_rate = catalog.get('enums') or {}, policy, problems, key_rate
        self.defaults = policy.get('defaults') or {}
        self.settings = policy.get('products') or {}
        self.payment_models = policy.get('payment_models') or {}
        self.overlay_items, self.card_ids = overlay_items, card_ids
        self.missing_models: set[str] = set()  # instrument types of card products without a payment model

    def guarded(self, label: str, build):
        """Runs one item's build; a structurally broken entry is reported instead of crashing the load."""
        try:
            return build()
        except (KeyError, TypeError, AttributeError, IndexError) as error:
            self.problems.add(label, f'malformed entry ({type(error).__name__}: {error})')
            return None

    def check_enum(self, path: str, value, enum: str) -> bool:
        if value not in self.enums.get(enum, ()):
            self.problems.add(path, f'unknown value {value!r}')
            return False
        return True

    def check_common(self, entry: dict, label: str) -> None:
        """Enum membership for every item; card products may only name purposes the questionnaire can ask."""
        self.check_enum(f'{label}.kind', entry['kind'], 'kind')
        self.check_enum(f'{label}.instrument_type', entry['instrument_type'], 'instrument_type')
        self.check_enum(f'{label}.limit_status', entry['limit_status'], 'limit_status')
        self.check_enum(f'{label}.rate.type', entry['rate']['type'], 'rate_type')
        if entry.get('source') is not None:
            self.check_enum(f'{label}.source.confidence', entry['source']['confidence'], 'confidence')
        for index, name in enumerate(entry['eligibility']['entity_types']):
            self.check_enum(f'{label}.eligibility.entity_types[{index}]', name, 'entity_types')
        for index, purpose in enumerate(entry['purposes']):
            path = f'{label}.purposes[{index}]'
            if self.check_enum(path, purpose, 'purposes') and entry['kind'] != 'overlay' and purpose not in PURPOSES:
                self.problems.add(path, f'{purpose!r} is not supported by the application')

    def resolve(self, settings: dict, label: str, product_id: str, catalog_value, catalog_path: str, key: str,
                default_key: str, bound: str, fallbacks: list[str]):
        """The catalog value, a tighter policy setting, or for a null the policy's setting or default."""
        if catalog_value is None:
            value = settings.get(key, self.defaults.get(default_key))
            if value is None:
                self.problems.add(f'{label}.{catalog_path}', 'null, no policy fallback')
            else:
                fallbacks.append(key)
            return value
        if key in settings:
            value = settings[key]
            if is_count(value) and (value < catalog_value if bound == 'min' else value > catalog_value):
                self.problems.add(f'policy.products.{product_id}.{key}', f'{value} weakens the catalog {bound} {catalog_value}')
            return value
        return catalog_value

    def product(self, entry: dict, label: str) -> dict:
        problems, product_id = self.problems, entry['id']
        settings, fallbacks = self.settings.get(product_id, {}), []
        amount, term = entry['amount'], entry['term']

        def resolve(value, path, key, default_key, bound):
            return self.resolve(settings, label, product_id, value, path, key, default_key, bound, fallbacks)
        amount_min = resolve(amount['min'], 'amount.min', 'amount_min_rub', 'amount_min_rub', 'min')
        amount_max = resolve(amount['max'], 'amount.max', 'amount_max_rub', 'amount_max_rub_if_null', 'max')
        if is_count(amount_min) and is_count(amount_max) and amount_min > amount_max:
            problems.add(f'{label}.amount', f'min {amount_min} is above max {amount_max}')
        unsecured = amount.get('max_unsecured')
        if unsecured is not None and is_count(amount_max) and unsecured > amount_max:
            problems.add(f'{label}.amount.max_unsecured', f'{unsecured} is above max {amount_max}')
        if term['unlimited']:
            term_min = term_max = None
            if term['min_months'] is not None or term['max_months'] is not None:
                problems.add(f'{label}.term', 'unlimited with month bounds')
        else:
            term_min = resolve(term['min_months'], 'term.min_months', 'term_min_months', 'term_min_months', 'min')
            term_max = resolve(term['max_months'], 'term.max_months', 'term_max_months', 'term_max_months', 'max')
            if is_count(term_min) and is_count(term_max) and term_min > term_max:
                problems.add(f'{label}.term', f'min {term_min} is above max {term_max}')
        by_purpose = dict(term.get('max_months_by_purpose') or {})
        for purpose, months in by_purpose.items():
            path = f'{label}.term.max_months_by_purpose.{purpose}'
            if purpose not in entry['purposes']:
                problems.add(path, 'not a purpose of this product')
            elif term_min is None or term_max is None or not is_count(months) or not term_min <= months <= term_max:
                problems.add(path, f'{months} is outside {term_min}–{term_max}')
        mode = self.collateral_mode(entry, label, settings, fallbacks)
        display = entry['display']
        for key in ('summary', 'best_for'):
            if not text_present(display.get(key)):
                problems.add(f'{label}.display.{key}', 'missing explanation text')
        features = display.get('features')
        if not isinstance(features, list) or not 3 <= len(features) <= 5 or not all(map(text_present, features)):
            problems.add(f'{label}.display.features', '3–5 explanation bullets required')
        model = self.payment_models.get(entry['instrument_type'])
        if model is None:
            self.missing_models.add(entry['instrument_type'])
        self.check_guarantee(entry, label)
        eligibility = entry['eligibility']
        denied, unparsed = okved_deny(eligibility['okved_deny_main'])
        defaults = self.defaults
        return {
            'id': product_id, 'name': entry['name'], 'aliases': list(entry.get('aliases') or []), 'kind': entry['kind'],
            'instrument_type': entry['instrument_type'], 'lender': entry.get('lender'),
            'program_operator': entry.get('program_operator'), 'legal_basis': entry.get('legal_basis'),
            'status': entry['status'], 'limit_status': entry['limit_status'],
            'applyable': entry['status'] == 'active' and entry['limit_status'] == 'open',
            'display': {'headline': display.get('headline'), 'summary': display.get('summary'),
                        'features': list(features or []), 'best_for': display.get('best_for')},
            'purposes': list(entry['purposes']), 'entity_types': self.entity_types(eligibility),
            'amount_min_rub': amount_min, 'amount_max_rub': amount_max, 'amount_max_unsecured_rub': unsecured,
            # The most lent without collateral: none for a secured product, the catalog's unsecured cap, else the maximum.
            'unsecured_cap_rub': 0 if mode == 'required' else unsecured if unsecured is not None else amount_max,
            'tranche_min_rub': amount.get('tranche_min'), 'tranche_max_rub': amount.get('tranche_max'),
            'term_min_months': term_min, 'term_max_months': term_max, 'term_max_months_by_purpose': by_purpose,
            'term_note': term.get('note'), **self.rate(entry, label, term_max), 'payment_model': model,
            'collateral_mode': mode, 'collateral_ltv_bps': defaults.get('collateral_ltv_bps'),
            'low_risk_revenue_multiple': defaults.get('low_risk_revenue_multiple'),
            'medium_risk_revenue_multiple': defaults.get('medium_risk_revenue_multiple'),
            'medium_risk_cap_rub': defaults.get('medium_risk_cap_rub'),
            'base_documents': list(defaults.get('base_documents') or []),
            'collateral_documents': list(defaults.get('collateral_documents') or []),
            'eligibility': {'msp_registry_required': eligibility['msp_registry_required'],
                            'regions_allow': list(eligibility['regions_allow']), 'okved_denied_classes': denied},
            'conditions_to_confirm': conditions(eligibility, unparsed),
            'overlay_ids': [overlay_id for overlay_id, (overlay, _) in self.overlay_items.items()
                            if product_id in (overlay['display'].get('applies_to') or [])],
            'usage_restrictions': list(entry.get('usage_restrictions') or []), 'fees': plain(entry.get('fees')),
            'process': plain(entry.get('process')), 'source': plain(entry.get('source')),
            'priority': settings.get('priority', defaults.get('priority')), 'fallbacks': fallbacks}

    def collateral_mode(self, entry: dict, label: str, settings: dict, fallbacks: list[str]) -> str | None:
        """required (the catalog requires it), none or optional (it does not); a catalog null needs the policy's mode."""
        required = entry['collateral']['required']
        mode = settings.get('collateral_mode')
        if mode is None:
            if required is None:
                self.problems.add(f'{label}.collateral.required', 'null, no policy fallback')
            return {True: 'required', False: 'none', None: None}[required]
        if required is None:
            fallbacks.append('collateral_mode')
        elif required is True and mode != 'required' and mode in COLLATERAL_MODES:
            self.problems.add(f"policy.products.{entry['id']}.collateral_mode", f"{mode!r} weakens the catalog's required collateral")
        return mode

    def rate(self, entry: dict, label: str, term_max: int | None) -> dict:
        """One period from month 1. A disclosed percent must equal its formula at the key rate and be whole basis
        points; a period ending before the product's longest term is a preferential rate."""
        rate, problems = entry['rate'], self.problems
        periods = rate['periods']
        result = {'annual_rate_bps': None, 'rate_certainty': None, 'rate_preferential_months': None,
                  'rate_formula': None, 'rate_note': rate.get('note')}
        if rate['type'] not in ('fixed', 'formula', 'undisclosed'):
            if rate['type'] in self.enums.get('rate_type', ()):
                problems.add(f'{label}.rate.type', f"{rate['type']!r} is not supported for a card product")
            return result
        if len(periods) != 1 or periods[0]['from_month'] != 1:
            problems.add(f'{label}.rate.periods', 'exactly one period from month 1 is supported')
            return result
        period, path = periods[0], f'{label}.rate.periods[0]'
        percent, formula = period['rate_percent'], period['rate_formula']
        result['rate_formula'] = formula
        if rate['type'] == 'undisclosed':
            if percent is not None:
                problems.add(f'{path}.rate_percent', 'set for an undisclosed rate')
            return {**result, 'rate_certainty': 'undisclosed'}
        if percent is None:
            problems.add(f'{path}.rate_percent', 'null for a disclosed rate')
            return result
        percent = Decimal(percent)
        if formula is not None and self.key_rate is not None:
            try:
                computed = parse_rate_formula(formula, self.key_rate)
            except ValueError as error:
                problems.add(f'{path}.rate_formula', str(error))
            else:
                if computed != percent:
                    problems.add(f'{path}.rate_percent', f'{percent} does not equal {formula} = {computed}')
        elif rate['type'] == 'formula' and formula is None:
            problems.add(f'{path}.rate_formula', 'missing for a formula rate')
        bps = percent * 100
        if bps != bps.to_integral_value():
            problems.add(f'{path}.rate_percent', f'{percent} is not a whole number of basis points')
        to_month = period['to_month']
        preferential = to_month if to_month is not None and (term_max is None or to_month < term_max) else None
        return {**result, 'annual_rate_bps': int(bps), 'rate_preferential_months': preferential,
                'rate_certainty': 'preferential' if preferential else 'full'}

    def entity_types(self, eligibility: dict) -> list[str]:
        mapping = self.policy.get('entity_types') or {}
        return [mapping[name] for name in eligibility['entity_types'] if name in mapping]

    def check_guarantee(self, entry: dict, label: str) -> None:
        overlay_id = entry['collateral'].get('guarantee_overlay')
        if overlay_id is None:
            return
        path = f'{label}.collateral.guarantee_overlay'
        if overlay_id not in self.overlay_items:
            self.problems.add(path, f'unknown overlay {overlay_id!r}')
        elif entry['id'] not in (self.overlay_items[overlay_id][0]['display'].get('applies_to') or []):
            self.problems.add(path, f'{overlay_id} does not list this product in display.applies_to')

    def overlay(self, entry: dict, label: str) -> dict:
        """A badge on the cards it applies to; the policy adds the text for collateral-required cards and the products
        exempt from its OKVED restriction."""
        problems, display, overlay_id = self.problems, entry['display'], entry['id']
        if display['as'] != 'badge_on_card':
            problems.add(f'{label}.display.as', 'an overlay renders as badge_on_card')
        applies_to = list(display.get('applies_to') or [])
        for index, product_id in enumerate(applies_to):
            if product_id not in self.card_ids:
                problems.add(f'{label}.display.applies_to[{index}]', f'unknown product {product_id!r}')
        if not text_present(display.get('headline')):
            problems.add(f'{label}.display.headline', 'missing badge text')
        badge = (self.policy.get('overlay_badges') or {}).get(overlay_id, {})
        exempt = list(badge.get('okved_exempt_products') or [])
        for index, product_id in enumerate(exempt):
            if product_id not in applies_to:
                problems.add(f'policy.overlay_badges.{overlay_id}.okved_exempt_products[{index}]',
                             f"{product_id!r} is not in the overlay's applies_to")
        eligibility, collateral = entry['eligibility'], entry['collateral']
        denied, unparsed = okved_deny(eligibility['okved_deny_main'])
        return {
            'id': overlay_id, 'name': entry['name'], 'kind': entry['kind'], 'instrument_type': entry['instrument_type'],
            'program_operator': entry.get('program_operator'), 'status': entry['status'],
            'limit_status': entry['limit_status'], 'applies_to': applies_to, 'badge_text': display.get('headline'),
            'badge_text_collateral_required': badge.get('text_collateral_required') or display.get('headline'),
            'coverage_pct_max': plain(collateral.get('coverage_pct_max')),
            'coverage_amount_max_rub': plain(collateral.get('coverage_amount_max')),
            'entity_types': self.entity_types(eligibility),
            'eligibility': {'msp_registry_required': eligibility['msp_registry_required'],
                            'regions_allow': list(eligibility['regions_allow']), 'okved_denied_classes': denied},
            'okved_exempt_products': exempt, 'conditions_to_confirm': conditions(eligibility, unparsed),
            'fees': plain(entry.get('fees')), 'process': plain(entry.get('process')), 'source': plain(entry.get('source'))}
