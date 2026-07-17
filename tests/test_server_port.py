import socket

import pytest

from mdm.main import run


def test_run_fails_fast_when_port_already_in_use() -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    port = occupied.getsockname()[1]
    occupied.listen(1)

    try:
        with pytest.raises(SystemExit):
            run(host="127.0.0.1", port=port)
    finally:
        occupied.close()
