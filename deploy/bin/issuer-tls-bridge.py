#!/usr/bin/env python3
"""Bridge a container network to the loopback-only local OIDC issuer.

Why this exists
---------------
The synthetic staging stack serves the Console over Tailnet HTTPS and the
Core/Console containers talk to the same local OIDC issuer. The issuer tool
binds loopback only (a deliberate rule), and tailscale serve terminates TLS
on the tailnet interface, so a bridge-network container cannot reach the
issuer at the public https URL — the login round trip fails with a
"fetch failed" from the container.

This bridge listens on the docker gateway with the machine's real public
certificate for that hostname and forwards to the issuer on loopback. With
``extra_hosts`` pointing the hostname at the gateway, the container and the
browser see the same issuer URL and therefore the same token issuer string.

Usage::

    issuer-tls-bridge.py <listen-ip> <listen-port> <issuer-port> <cert.pem> <key.pem>

The certificate must be valid for the public hostname the issuer advertises
(``tailscale cert <host>`` produces one). This is a development topology
helper, not a production component.
"""

from __future__ import annotations

import contextlib
import socket
import ssl
import sys
import threading

LISTEN_HOST = sys.argv[1]
LISTEN_PORT = int(sys.argv[2])
TARGET_HOST = "127.0.0.1"
TARGET_PORT = int(sys.argv[3])
CERT = sys.argv[4]
KEY = sys.argv[5]


def _pipe(source: socket.socket, sink: socket.socket) -> None:
    try:
        while True:
            chunk = source.recv(65536)
            if not chunk:
                break
            sink.sendall(chunk)
    except OSError:
        pass
    finally:
        for handle in (source, sink):
            with contextlib.suppress(OSError):
                handle.shutdown(socket.SHUT_RDWR)


def _handle(client: socket.socket) -> None:
    try:
        upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=10)
    except OSError:
        client.close()
        return
    threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=_pipe, args=(upstream, client), daemon=True).start()


def main() -> int:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT, KEY)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((LISTEN_HOST, LISTEN_PORT))
    listener.listen(128)
    print(f"issuer bridge listening on {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}")
    while True:
        client, _ = listener.accept()
        try:
            tls = context.wrap_socket(client, server_side=True)
        except (ssl.SSLError, OSError):
            with contextlib.suppress(OSError):
                client.close()
            continue
        threading.Thread(target=_handle, args=(tls,), daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())
