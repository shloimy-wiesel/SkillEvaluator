"""Transport the pinned suite as data, with no shared filesystem or daemon socket."""

import base64
import contextlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from skillevaluator.public_certificates import public_certificates

from .workspace import WorkspaceError


def require_sandbox(consent):
    if not consent:
        raise WorkspaceError("Explicit consent is required to qualify a project suite.")
    image = os.environ.get("STUDIO_GRADER_IMAGE", "")
    if os.environ.get("STUDIO_LIVE_ENABLED") != "1" or not image or image.startswith("-"):
        raise WorkspaceError("Configure the isolated Docker worker and its trusted grader image.")
    return image


def isolated(ctx, options, args, *, manifest, policy, chat, redact):
    image = require_sandbox(options.sandbox_consent)
    files = {}
    size = 0

    def include(name):
        nonlocal size
        if not isinstance(name, str) or Path(name).is_absolute():
            raise WorkspaceError("Choose a trajectory inside the suite.")
        path = ctx.input_file(str(manifest.parent.relative_to(ctx.root) / name))
        if name not in files:
            size += path.stat().st_size
            if size > 16 * 1024**2 or len(files) >= 1024:
                raise WorkspaceError("Suite exceeds 16 MiB or 1024 files.")
            files[name] = base64.b64encode(path.read_bytes()).decode("ascii")

    include("suite.json")
    try:
        for case in json.loads(base64.b64decode(files["suite.json"]))["cases"]:
            if case["trajectory"] is not None:
                include(case["trajectory"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError("Invalid suite manifest; use Check suite for diagnostics.") from exc
    if policy and policy.stat().st_size > 1024**2:
        raise WorkspaceError("Qualification policy exceeds 1 MiB.")
    ca = os.environ.get("SSL_CERT_FILE") if chat else None
    request = {
        "args": args,
        "files": files,
        "policy": policy.read_text() if policy else None,
        "repeats": options.repeats,
        "ca": public_certificates(ca).decode("ascii") if ca else None,
        "chat": chat or {"OPENAI_API_KEY": "offline-placeholder", "SKILL_EVAL_LLM_BASE_URL": "http://127.0.0.1:1/v1"},
    }
    name = "studio-grader-" + uuid4().hex
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--pull=never",
        "--network",
        "bridge" if chat else "none",
        "--read-only",
        "--user=10001:10001",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=1g",
        "--memory-swap=1g",
        "--cpus=2",
        "--pids-limit=96",
        "--log-driver=none",
        "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=128m,mode=1777",
        "--tmpfs=/data:ro,size=1m",
        "--workdir=/tmp",
        "--entrypoint=/usr/bin/timeout",
        image,
        "-s",
        "KILL",
        "3590",
        "python",
        "-I",
        "-c",
        Path(__file__).with_name("grader_container.py").read_text(),
    ]
    try:
        result = subprocess.run(command, input=json.dumps(request), capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise WorkspaceError(
                "Isolated qualification could not finish. Check the local live image, daemon and suite limits."
            )
        code, payload, files = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise WorkspaceError("Isolated Docker worker unavailable or qualification exceeded its limit.") from exc
    finally:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
    if files:
        with ZipFile(ctx.artifacts / "qualification.zip", "w", ZIP_DEFLATED) as archive:
            for path, text in files.items():
                archive.writestr(path, redact(text, chat))
    return code, json.loads(redact(json.dumps(payload), chat))
