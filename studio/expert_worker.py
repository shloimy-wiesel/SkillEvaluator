"""Private entry point: no imports or interactive prompts from the checkout."""

import json
import os
import resource
import ssl
import sys
from contextlib import ExitStack
from pathlib import Path

from skillevaluator.cli import cli
from skillevaluator.embedded import (
    chat_transport,
    embedding_environment,
    embedding_transport,
    report_observer,
    sandbox_preflight,
)
from skillevaluator.reporting.json_reporter import JSONReporter
from skillevaluator.reporting.markdown import MarkdownReporter

def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 << 20, 32 << 20))
    settings = json.load(sys.stdin)
    if settings["live"]:

        def check_sandbox():
            if reason := settings["preflight_error"]:
                raise RuntimeError(reason)

        sandbox_preflight.set(check_sandbox)
    else:
        resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
        resource.setrlimit(resource.RLIMIT_AS, (1536 << 20, 1536 << 20))

    owner = os.getpid()

    def capture(results):
        if os.getpid() != owner:
            return  # Parallel catalog children publish their own native leaf reports.
        Path("studio-result.json").write_text(JSONReporter().render_all(results))
        Path("studio-result.md").write_text(MarkdownReporter().render_all(results))

    report_observer.set(capture)
    embeddings = settings["embeddings"]
    embedding_environment.set(embeddings)
    with ExitStack() as stack:
        for configured, transport in (
            (os.environ.get("SKILL_EVAL_LLM_PROVIDER"), chat_transport),
            (embeddings, embedding_transport),
        ):
            if configured:
                import httpx

                transport.set(
                    stack.enter_context(
                        httpx.Client(verify=ssl.create_default_context(), trust_env=False, follow_redirects=False)
                    )
                )
        cli(prog_name="skillevaluator")


if __name__ == "__main__":
    main()
