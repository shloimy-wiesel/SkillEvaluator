"""Private entry point: no imports or interactive prompts from the checkout."""

import json
import os
import resource
import ssl
import sys
from contextlib import ExitStack
from functools import partial
from multiprocessing.util import Finalize
from pathlib import Path

from skillevaluator.cli import cli
from skillevaluator.embedded import (
    catalog_initializer,
    chat_transport,
    embedding_environment,
    embedding_transport,
    report_observer,
    sandbox_preflight,
)
from skillevaluator.reporting.json_reporter import JSONReporter
from skillevaluator.reporting.markdown import MarkdownReporter


def configure(settings, stack):
    if settings["live"]:

        def check_sandbox(skill):
            error = settings["members"].get(str(skill), "Skill outside staged catalog.")
            if reason := error or settings["preflight_error"]:
                raise RuntimeError(reason)

        sandbox_preflight.set(check_sandbox)
    embeddings = settings["embeddings"]
    embedding_environment.set(embeddings)
    for configured, transport in (
        (os.environ.get("SKILL_EVAL_LLM_PROVIDER"), chat_transport),
        (embeddings, embedding_transport),
    ):
        if configured:
            import httpx

            transport.set(stack.enter_context(httpx.Client(verify=ssl.create_default_context(), trust_env=False)))


def configure_child(settings):
    stack = ExitStack()
    Finalize(None, stack.close, exitpriority=0)
    configure(settings, stack)


def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 << 20, 32 << 20))
    settings = json.load(sys.stdin)
    if not settings["live"]:
        resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
        resource.setrlimit(resource.RLIMIT_AS, (1536 << 20, 1536 << 20))

    owner = os.getpid()

    def capture(results):
        if os.getpid() != owner:
            return  # Parallel catalog children publish their own native leaf reports.
        Path("studio-result.json").write_text(JSONReporter().render_all(results))
        Path("studio-result.md").write_text(MarkdownReporter().render_all(results))

    report_observer.set(capture)
    with ExitStack() as stack:
        configure(settings, stack)
        if settings["live"]:
            catalog_initializer.set(partial(configure_child, settings))
        cli(prog_name="skillevaluator")


if __name__ == "__main__":
    main()
