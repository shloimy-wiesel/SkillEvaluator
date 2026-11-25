"""Run a fixed offline hook in an isolated interpreter, without importing the repository."""

import json
import logging
import os
import resource
import sys
from contextlib import redirect_stdout
from pathlib import Path

from skillevaluator.logging_config import setup_logging
from skillevaluator.precommit import collect_skill_roots, run_precommit

if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (768 << 20, 768 << 20))
    data = json.load(sys.stdin)
    root = Path(data["root"])
    paths = data["paths"]
    for name in paths:
        if (root / name).resolve() != root / name:
            sys.exit("Linked input")
    roots = collect_skill_roots(paths, cwd=root)
    for skill in roots:
        if not skill.is_relative_to(root) or any(path.is_symlink() for path in skill.rglob("*")):
            sys.exit("Linked skill")
    # Engine logs may contain repository text. Return only allowlisted diagnostics.
    with Path(os.devnull).open("w") as discard, redirect_stdout(discard):
        setup_logging(verbose=data["verbose"])
        result = run_precommit(
            data["check"],
            paths,
            cwd=root,
            min_score=data["min_score"],
            quality_config=Path(data["quality_config"]) if data["quality_config"] else None,
        )
    detail = (
        {
            "level": logging.getLevelName(logging.getLogger().getEffectiveLevel()),
            "skills": len(roots),
            "paths": len(paths),
        }
        if data["verbose"]
        else None
    )
    json.dump((*result, detail), sys.stdout)
