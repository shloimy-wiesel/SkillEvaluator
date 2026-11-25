"""Private entry point: no imports or interactive prompts from the checkout."""

import json
import os
import resource
import ssl
import sys
from contextlib import ExitStack
from pathlib import Path

from skillevaluator.cli import cli
from skillevaluator.embedded import chat_transport, embedding_environment, embedding_transport, report_observer
from skillevaluator.reporting.json_reporter import JSONReporter
from skillevaluator.reporting.markdown import MarkdownReporter

resource.setrlimit(resource.RLIMIT_FSIZE, (32 << 20, 32 << 20))
resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
resource.setrlimit(resource.RLIMIT_AS, (1536 << 20, 1536 << 20))


def capture(results):
    Path("studio-result.json").write_text(JSONReporter().render_all(results))
    Path("studio-result.md").write_text(MarkdownReporter().render_all(results))


report_observer.set(capture)
embeddings = json.load(sys.stdin)
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
