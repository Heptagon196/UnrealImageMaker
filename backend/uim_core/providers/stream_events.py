from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

_stream_event_callback: ContextVar[Callable[[str], None] | None] = ContextVar("uim_stream_event_callback", default=None)


@contextmanager
def codex_stream_events(callback: Callable[[str], None] | None) -> Iterator[None]:
    token = _stream_event_callback.set(callback)
    try:
        yield
    finally:
        _stream_event_callback.reset(token)


def emit_stream_event(summary: str) -> None:
    callback = _stream_event_callback.get()
    if callback and summary:
        callback(summary)
