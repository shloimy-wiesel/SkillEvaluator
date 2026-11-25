"""Private, isolated entry point for the installed doctor's role-specific SDKs."""

import json
import sys

from skillevaluator.cli import cli
from skillevaluator.embedded import embedding_environment

embedding_environment.set(json.load(sys.stdin))
cli(prog_name="skillevaluator")
