from mdm.cnpj_validation import is_valid_cnpj


def test_valid_formatted_cnpj_passes() -> None:
    assert is_valid_cnpj("11.222.333/0001-81") is True


def test_valid_unformatted_cnpj_passes() -> None:
    assert is_valid_cnpj("11222333000181") is True


def test_wrong_check_digits_fails() -> None:
    assert is_valid_cnpj("11.222.333/0001-99") is False


def test_all_same_digit_fails() -> None:
    assert is_valid_cnpj("11111111111111") is False


def test_arbitrary_14_digit_number_fails() -> None:
    # e.g. an order number or barcode fragment that happens to be 14 digits
    assert is_valid_cnpj("98765432109876") is False


def test_wrong_length_fails() -> None:
    assert is_valid_cnpj("123") is False
