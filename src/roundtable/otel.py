"""OpenTelemetry on this computer only (wave 9).

A stub with its frozen signature: Helper w9-local fills it. Each model call, tool call and task as a span in
``<home>/traces/<day>.jsonl`` (the OTLP JSON shape); nothing leaves the computer unless the owner types an
address. Until it is filled a span does nothing at all.
"""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def span(home, name: str, **attrs):
    """One span around the ``with`` block (stub: nothing is written)."""
    yield None
