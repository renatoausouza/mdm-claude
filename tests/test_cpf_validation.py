from mdm.cpf_validation import is_valid_cpf


def test_valid_formatted_cpf_passes() -> None:
    assert is_valid_cpf("111.444.777-35") is True


def test_valid_unformatted_cpf_passes() -> None:
    assert is_valid_cpf("11144477735") is True


def test_wrong_check_digits_fails() -> None:
    assert is_valid_cpf("111.444.777-99") is False


def test_all_same_digit_fails() -> None:
    assert is_valid_cpf("11111111111") is False


def test_arbitrary_11_digit_number_fails() -> None:
    assert is_valid_cpf("98765432109") is False


def test_wrong_length_fails() -> None:
    assert is_valid_cpf("123") is False
