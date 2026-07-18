import re

_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_WEIGHTS_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def _check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def is_valid_cnpj(value: str) -> bool:
    """Brazilian CNPJ mod-11 check-digit validation — used to reject
    arbitrary 14-digit numbers (order numbers, barcode fragments) that the
    regex's unformatted fallback pattern would otherwise accept as a CNPJ."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 14:
        return False
    if digits == digits[0] * 14:
        return False

    first_check = _check_digit(digits[:12], _WEIGHTS_1)
    second_check = _check_digit(digits[:12] + first_check, _WEIGHTS_2)
    return digits[12] == first_check and digits[13] == second_check
