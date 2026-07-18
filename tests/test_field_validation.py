from mdm.field_validation import is_valid_email, is_valid_telephone


def test_valid_email_passes() -> None:
    assert is_valid_email("contato@acme.com.br") is True


def test_email_without_at_sign_fails() -> None:
    assert is_valid_email("not-an-email") is False


def test_valid_telephone_passes() -> None:
    assert is_valid_telephone("(11) 98765-4321") is True


def test_too_short_telephone_fails() -> None:
    assert is_valid_telephone("123") is False


def test_too_long_telephone_fails() -> None:
    assert is_valid_telephone("1" * 20) is False


def test_eight_digit_cep_is_not_a_valid_telephone() -> None:
    # A postal code (CEP) is 8 digits — the same length as an old,
    # too-permissive lower bound used to accept as a phone number.
    assert is_valid_telephone("01310-100") is False
