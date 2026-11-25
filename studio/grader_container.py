"""Trusted entry point sent to the grader image; never run on the Studio host."""

import base64
import json
import os
import sys
from pathlib import Path

from click.testing import CliRunner

from skillevaluator.tier3.grader_validation import validate_grader


def main():
    request = json.load(sys.stdin)
    suite = Path("/tmp/suite")
    suite.mkdir()
    for name, text in request["files"].items():
        path = suite / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(text))
    args = request["args"] + [str(suite)]
    if request["policy"] is not None:
        Path("/tmp/policy.json").write_text(request["policy"])
        args += ["--qualification-policy", "/tmp/policy.json"]
    os.environ.clear()
    os.environ.update(PATH="/usr/local/bin:/usr/bin:/bin", HOME="/tmp", LANG="C.UTF-8", PYTHON_DOTENV_DISABLED="1")
    runner = CliRunner()
    result = runner.invoke(validate_grader, [*args, "--check-suite"])
    if result.exit_code == 2:
        sys.stdout.write(
            json.dumps([2, {"status": "invalid", "diagnostic": result.output.partition("Error: ")[2][:1000]}, {}])
        )
        return
    preflight = json.loads(result.output)
    if preflight["cases"] * request["repeats"] > 128:
        raise ValueError("attempt limit")
    os.environ.update(request["chat"])
    if request["ca"]:
        Path("/tmp/judge-ca.pem").write_text(request["ca"])
        os.environ["SSL_CERT_FILE"] = "/tmp/judge-ca.pem"
    output = Path("/tmp/output")
    result = runner.invoke(validate_grader, [*args, "--output", str(output)])
    if result.exit_code not in {0, 1}:
        raise ValueError("qualification failed")
    report = json.loads(result.output)
    files = {}
    size = 0
    for path in output.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".txt"}:
            size += path.stat().st_size
            if size > 16 * 1024**2 or len(files) >= 2048:
                raise ValueError("evidence limit")
            files[path.relative_to(output).as_posix()] = path.read_text()
    sys.stdout.write(json.dumps([result.exit_code, report, files]))


if __name__ == "__main__":
    main()
