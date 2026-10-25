"""The small, pure rules the configuration is read with: the rate-formula parser, the OKVED deny-entry parser, region
normalisation and the value sets the application supports."""
from decimal import Decimal
import re

PURPOSES = ('working_capital', 'business_development', 'investment', 'refinancing')  # what stage 2 can ask
ENTITY_TYPES = ('IP', 'LLC')
COLLATERAL_MODES = ('none', 'optional', 'required')
PAYMENT_MODELS = ('annuity', 'interest_full_utilization', 'none')
RATE_CERTAINTIES = ('full', 'preferential', 'undisclosed')
OKVED_RULE = {'deny_entries': 'leading_code_or_range', 'compare': 'main_okved_class', 'unparsed': 'condition_to_confirm'}
REGION_STEPS = {'casefold': str.casefold, 'yo_to_ye': lambda text: text.replace('ё', 'е').replace('Ё', 'Е'),
                'collapse_spaces': lambda text: ' '.join(text.split())}
FORMULA = re.compile(r'\s*(?:KEY_RATE(?:\s*([+-])\s*(\d+(?:\.\d+)?))?|(\d+(?:\.\d+)?))\s*')
# A deny entry applies only when it starts with a two-digit class or a class range (en dash or hyphen).
OKVED_ENTRY = re.compile(r'\s*(\d{2})(?!\d)(?:\s*[–-]\s*(\d{2})(?!\d))?')


def parse_rate_formula(formula: str, key_rate: Decimal) -> Decimal:
    """`KEY_RATE`, `KEY_RATE + n`, `KEY_RATE - n` or a plain non-negative number; nothing is evaluated."""
    match = FORMULA.fullmatch(formula)
    if not match:
        raise ValueError(f'unsupported formula {formula!r}')
    sign, offset, number = match.groups()
    if number is not None:
        return Decimal(number)
    if sign is None:
        return key_rate
    return key_rate + Decimal(offset) if sign == '+' else key_rate - Decimal(offset)


def okved_deny(entries: list[str]) -> tuple[list[str], list[str]]:
    """(denied two-digit classes, entries that name no leading class and are only conditions to confirm)."""
    classes, unparsed = set(), []
    for entry in entries:
        match = OKVED_ENTRY.match(entry)
        start = int(match.group(1)) if match else None
        end = int(match.group(2) or start) if match else None
        if match is None or end < start:
            unparsed.append(entry)
        else:
            classes.update(range(start, end + 1))
    return [f'{value:02d}' for value in sorted(classes)], unparsed


def normalize_region(text: str, steps) -> str:
    for step in steps:
        text = REGION_STEPS[step](text)
    return text


def conditions(eligibility: dict, unparsed: list[str]) -> list[dict]:
    """Informational eligibility, shown on the card and never blocking: requirements, the categories of which one must
    apply, and OKVED restrictions stated without a leading class."""
    return ([{'kind': 'requirement', 'text': text} for text in eligibility['requirements']]
            + [{'kind': 'category', 'text': text} for text in eligibility['categories']]
            + [{'kind': 'okved', 'text': text} for text in unparsed])


def plain(value):
    """JSON-safe copy of passthrough catalog data (numbers are parsed as Decimal)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: plain(entry) for key, entry in value.items()}
    if isinstance(value, list):
        return [plain(entry) for entry in value]
    return value


def is_count(value, *, positive: bool = True) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and (value > 0 if positive else value >= 0)


def text_present(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
