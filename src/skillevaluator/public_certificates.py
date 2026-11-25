"""Prepare an operator's public trust anchors for transport into a sandbox."""

import re
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

_CERT = re.compile(rb"-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----")


def public_certificates(path: str | Path) -> bytes:
    diagnostic = "Configure SSL_CERT_FILE with only public PEM certificates (maximum 2 MiB)."
    path = Path(path)
    try:
        if not path.is_file():
            raise ValueError
        with path.open("rb") as file:
            data = file.read(2 * 1024**2 + 1)
        if len(data) > 2 * 1024**2 or _CERT.sub(b"", data).strip():
            raise ValueError
        certs = [x509.load_pem_x509_certificate(block).public_bytes(Encoding.PEM) for block in _CERT.findall(data)]
        if not certs:
            raise ValueError
        return b"".join(certs)
    except (OSError, ValueError):
        raise ValueError(diagnostic) from None
