"""Common wire format and credential checks for frozen provider settings."""

import json


def seal(workspace, payload):
    return workspace.cipher.encrypt(json.dumps(payload).encode())


def unseal(workspace, blob):
    return json.loads(workspace.cipher.decrypt(blob))


def exposes_credential(settings, *keys):
    public = settings.model_dump_json()
    # Compare JSON string contents, including escapes for quotes and backslashes.
    return any(key and json.dumps(key, ensure_ascii=False)[1:-1] in public for key in keys)
