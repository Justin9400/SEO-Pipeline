import socket

import pytest


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    original = socket.socket.connect

    def blocked(sock, address):
        # Windows asyncio implements its internal wakeup pipe with loopback sockets.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original(sock, address)
        raise AssertionError("Network calls are forbidden in automated tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
