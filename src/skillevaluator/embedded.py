# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Caller-scoped transports and result observers for embedded CLI workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skillevaluator.models.result import ValidationResult

chat_transport: ContextVar[Any] = ContextVar("chat_transport", default=None)
embedding_transport: ContextVar[Any] = ContextVar("embedding_transport", default=None)
embedding_environment: ContextVar[Mapping[str, str] | None] = ContextVar("embedding_environment", default=None)
report_observer: ContextVar[Callable[[list[ValidationResult]], None] | None] = ContextVar(
    "report_observer", default=None
)

# An embedding host may require an operator-managed sandbox for live work.
sandbox_preflight: ContextVar[Callable[[Path], None] | None] = ContextVar("sandbox_preflight", default=None)
# Embedded hosts can install process-local transports and policy in fresh catalog children.
catalog_initializer: ContextVar[Callable[[], None] | None] = ContextVar("catalog_initializer", default=None)
