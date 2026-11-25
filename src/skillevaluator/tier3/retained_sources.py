# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Let trusted orchestrators select original, path-bound evidence outside a job's output root."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_sources: ContextVar[dict[str, Path] | None] = ContextVar("retained_sources", default=None)


@contextmanager
def authorized_sources(selected: dict[str, Path]):
    token = _sources.set(selected)
    try:
        yield
    finally:
        _sources.reset(token)


def source_root(option: str, requested: str, default: Path) -> Path:
    selected = _sources.get()
    if selected is None:
        return default
    candidate = selected.get(option)
    if candidate is None or requested == "latest" or candidate.name != requested or candidate.resolve() != candidate:
        raise ValueError("Selected source does not match authorized retained evidence")
    return candidate.parent
