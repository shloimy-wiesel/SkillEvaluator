"""Copy only the requested operator settings before a worker changes directory."""

import os
from pathlib import Path

_PATHS = {"SSL_CERT_FILE", "GIT_SSL_CAINFO", "DOCKER_CERT_PATH"}


def operator_env(*names):
    return {
        name: str(Path(value).resolve()) if name in _PATHS else value
        for name in names
        if (value := os.environ.get(name))
    }
