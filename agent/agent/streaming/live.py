"""Request-local model deltas and a bounded bridge for synchronous workers."""

from contextvars import ContextVar, copy_context
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Callable


CURRENT_STREAM_SINK: ContextVar[Callable | None] = ContextVar("chat_stream_sink", default=None)


def emit_model_event(name: str, payload: dict) -> None:
    sink = CURRENT_STREAM_SINK.get()
    if sink is None:
        return
    from agent.service.access_guard import CURRENT_ACCESS_GUARD
    guard = CURRENT_ACCESS_GUARD.get()
    if guard is None:
        raise RuntimeError("stream_access_guard_missing")
    # Every release boundary rechecks current permissions and evidence versions.
    sink("source", {"evidence_provenance": guard.provenance().model_dump()})
    sink(name, payload)


class StreamCancelled(Exception):
    pass


def threaded_events(produce):
    """Keep ContextVars in one worker; propagate cancellation and backpressure."""
    queue = Queue(maxsize=16)
    cancelled = Event()
    context = copy_context()

    def send(name, value):
        while not cancelled.is_set():
            try:
                queue.put((name, value), timeout=0.1)
                return
            except Full:
                continue
        raise StreamCancelled()

    def work():
        try:
            produce(send)
        except StreamCancelled:
            return
        except Exception as exc:
            send("_exception", exc)
        finally:
            if not cancelled.is_set():
                try:
                    send("_end", None)
                except StreamCancelled:
                    pass

    worker = Thread(target=lambda: context.run(work), daemon=True)
    worker.start()
    try:
        while True:
            try:
                name, value = queue.get(timeout=0.5)
            except Empty:
                continue
            if name == "_end":
                return
            if name == "_exception":
                raise value
            yield name, value
    finally:
        cancelled.set()
