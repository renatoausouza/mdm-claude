import re

_WEIGHTS_1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
_WEIGHTS_2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]


def _check_digit(digits: str, weights: list[int]) -> str:
    total = sum(int(d) * w for d, w in zip(digits, weights))
    remainder = total % 11
    return "0" if remainder < 2 else str(11 - remainder)


def is_valid_cpf(value: str) -> bool:
    """Brazilian CPF mod-11 check-digit validation — same purpose as
    cnpj_validation.is_valid_cnpj, but CPFs are individuals (Client domain,
    #8) rather than companies, with their own 11-digit length and weights."""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11:
        return False
    if digits == digits[0] * 11:
        return False

    first_check = _check_digit(digits[:9], _WEIGHTS_1)
    second_check = _check_digit(digits[:9] + first_check, _WEIGHTS_2)
    return digits[9] == first_check and digits[10] == second_check
