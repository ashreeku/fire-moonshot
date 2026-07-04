"""Background job runner for pipeline stages.

Runs one stage at a time in a daemon thread, capturing printed output into a
ring buffer the dashboard polls. Single-job-at-a-time is intentional: stages are
sequential dependencies and share the GPU.
"""
from __future__ import annotations

import threading
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Callable

MAX_LOG_LINES = 5000


@dataclass
class JobState:
    name: str | None = None
    status: str = "idle"  # idle | running | done | failed
    error: str | None = None
    lines: list[str] = field(default_factory=list)
    progress: dict = field(default_factory=dict)


class _LineWriter:
    """File-like object that splits writes into lines and appends to the log."""

    def __init__(self, runner: "JobRunner") -> None:
        self._runner = runner
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._runner._append(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._runner._append(self._buffer)
            self._buffer = ""


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = JobState()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state.status == "running"

    def _append(self, line: str) -> None:
        with self._lock:
            self._state.lines.append(line)
            if len(self._state.lines) > MAX_LOG_LINES:
                del self._state.lines[: len(self._state.lines) - MAX_LOG_LINES]

    def set_progress(self, progress: dict) -> None:
        """Update the current job's progress (e.g. {label, frame, total, video})."""
        with self._lock:
            self._state.progress = dict(progress)

    def start(self, name: str, fn: Callable[[], object]) -> bool:
        """Start ``fn`` in the background. Returns False if a job is running."""
        with self._lock:
            if self._state.status == "running":
                return False
            self._state = JobState(name=name, status="running")

        def _run() -> None:
            writer = _LineWriter(self)
            try:
                with redirect_stdout(writer):
                    fn()
                writer.flush()
                with self._lock:
                    self._state.status = "done"
            except BaseException as exc:  # noqa: BLE001 - surface every failure
                writer.flush()
                tail = traceback.format_exc().strip().splitlines()[-12:]
                with self._lock:
                    self._state.status = "failed"
                    self._state.error = str(exc) or exc.__class__.__name__
                    self._state.lines.extend(tail)

        thread = threading.Thread(target=_run, name=f"job-{name}", daemon=True)
        self._thread = thread
        thread.start()
        return True

    def status(self) -> dict:
        with self._lock:
            return {
                "name": self._state.name,
                "status": self._state.status,
                "error": self._state.error,
                "n_lines": len(self._state.lines),
                "progress": dict(self._state.progress),
            }

    def log_since(self, since: int) -> dict:
        with self._lock:
            since = max(0, since)
            new_lines = self._state.lines[since:]
            return {
                "lines": new_lines,
                "next": len(self._state.lines),
                "status": self._state.status,
                "name": self._state.name,
                "error": self._state.error,
                "progress": dict(self._state.progress),
            }
