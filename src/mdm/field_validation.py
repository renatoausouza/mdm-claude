import re

# Shared with regex_candidates.py, which scans free text for candidate emails
# with the same pattern (via finditer) — kept in one place so the two don't
# drift out of sync on what counts as an email shape.
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(value))


def is_valid_telephone(value: str) -> bool:
    # Brazilian numbers: 10-11 digits with area code (landline/mobile), or
    # 12-13 with the +55 country code. A lower bound of 8 (dropped from an
    # earlier version) also accepted 8-digit CEPs (postal codes) as valid
    # phone numbers.
    digits = re.sub(r"\D", "", value)
    return 10 <= len(digits) <= 13
