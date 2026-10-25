"""The small, pure rules the configuration is read with: the rate-formula parser, the OKVED deny-entry parser, region
normalisation and the value sets the application supports."""
from decimal import Decimal
import json
import re

PURPOSES = ('working_capital', 'business_development', 'investment', 'refinancing')  # what stage 2 can ask
ENTITY_TYPES = ('IP', 'LLC')
COLLATERAL_MODES = ('none', 'optional', 'required')
PAYMENT_MODELS = ('annuity', 'interest_full_utilization', 'none')
RATE_CERTAINTIES = ('full', 'preferential', 'undisclosed')
ITEM_STATUSES = ('active', 'inactive')  # `limit_status` (open/exhausted/closed) says whether the limit is available
DISPLAY_MODES = ('card', 'badge_on_card')
OKVED_RULE = {'deny_entries': 'leading_code_or_range', 'compare': 'main_okved_class', 'unparsed': 'condition_to_confirm'}
REGION_STEPS = {'casefold': str.casefold, 'yo_to_ye': lambda text: text.replace('ё', 'е').replace('Ё', 'Е'),
                'collapse_spaces': lambda text: ' '.join(text.split())}
FORMULA = re.compile(r'\s*(?:KEY_RATE(?:\s*([+-])\s*(\d+(?:\.\d+)?))?|(\d+(?:\.\d+)?))\s*')
# An OKVED token: a class (`47`), or a subclass or group (`47.11`, `47,11`). A deny entry applies only when it starts
# with a two-digit class or a class range (en dash or hyphen); a subclass names part of a class and is informational.
OKVED_TOKEN = r'\d+(?:[.,]\d+)*'
OKVED_CODE = re.compile(rf'\s*({OKVED_TOKEN})')
OKVED_ENTRY = re.compile(rf'\s*({OKVED_TOKEN})(?:\s*[–-]\s*({OKVED_TOKEN}))?')


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


def is_class(token: str | None) -> bool:
    return token is not None and len(token) == 2 and token.isdigit()


def okved_class(code: str | None) -> str | None:
    """The two-digit class a company's OKVED code belongs to (`46.90` → `46`), or None when it starts with none."""
    match = OKVED_CODE.match(code) if isinstance(code, str) else None
    head = re.split(r'[.,]', match.group(1))[0] if match else None
    return head if is_class(head) else None


def okved_deny(entries: list[str]) -> tuple[list[str], list[str]]:
    """(denied two-digit classes, entries that name no leading class or class range and are only conditions to
    confirm)."""
    classes, unparsed = set(), []
    for entry in entries:
        match = OKVED_ENTRY.match(entry)
        start, end = (match.group(1), match.group(2) or match.group(1)) if match else (None, None)
        if not (is_class(start) and is_class(end)) or int(end) < int(start):
            unparsed.append(entry)
        else:
            classes.update(range(int(start), int(end) + 1))
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


def is_number(value) -> bool:
    """A JSON number (parsed as int or Decimal), not a boolean or a numeric-looking text."""
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def text_present(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def texts(value) -> bool:
    return isinstance(value, list) and all(text_present(entry) for entry in value)


def shown(value) -> str:
    """A value as the file wrote it, for error messages (`"30000000"` for a text, `30000000.5` for a number)."""
    return str(value) if isinstance(value, Decimal) else json.dumps(plain(value), ensure_ascii=False)
