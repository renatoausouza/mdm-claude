from mdm.main import resolve_bind_address


def test_explicit_port_zero_is_honored_not_replaced_by_config_default() -> None:
    _, port = resolve_bind_address(host=None, port=0)
    assert port == 0


def test_explicit_empty_host_is_honored_not_replaced_by_config_default() -> None:
    host, _ = resolve_bind_address(host="", port=None)
    assert host == ""


def test_none_falls_back_to_config_defaults() -> None:
    host, port = resolve_bind_address(host=None, port=None)
    assert host != ""
    assert isinstance(port, int)
