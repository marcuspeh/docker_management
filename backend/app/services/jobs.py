"""Deployment job runner: log buffering, SSE fan-out and cancellation.

Log state lives in memory because the service runs a single uvicorn worker. Each
line is numbered so a reconnecting client can resume with ``?offset=``, and the
whole buffer is persisted once the deployment finishes so a completed deploy can
still replay its output.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

#: Re-exported for the startup recovery sweep in main.py.
RUNNING_STATUSES = ("queued", "running")


@dataclass
class LogLine:
    seq: int
    text: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StepEvent:
    step: str
    status: str  # started | succeeded | failed


class DeploymentLog:
    """Ring buffer of numbered lines plus the events needed for a live stream.

    The ring keeps memory bounded during a long build; :meth:`snapshot` is what
    gets persisted so a finished deployment replays from any offset.
    """

    def __init__(self, limit: int = settings.log_buffer_lines) -> None:
        self._lines: deque[LogLine] = deque(maxlen=limit)
        self._next_seq = 1
        self.steps: list[StepEvent] = []
        self.done: dict[str, Any] | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    def append(self, text: str) -> LogLine:
        line = LogLine(seq=self._next_seq, text=text)
        self._next_seq += 1
        self._lines.append(line)
        self._publish({"type": "line", "line": {"seq": line.seq, "text": line.text}})
        return line

    def command(self, argv: list[str]) -> None:
        """Echo the command before its output, prefixed with ``$``."""
        self.append("$ " + " ".join(argv))

    def step(self, name: str, status: str) -> None:
        event = StepEvent(step=name, status=status)
        self.steps.append(event)
        self._publish({"type": "step", "step": {"step": name, "status": status}})

    def finish(self, payload: dict[str, Any]) -> None:
        self.done = payload
        self._publish({"type": "done", **payload})

    def snapshot(self) -> str:
        """Persistable representation: numbered lines plus terminal state."""
        return json.dumps(
            {
                "lines": [
                    {"seq": line.seq, "text": line.text} for line in self._lines
                ],
                "steps": [
                    {"step": s.step, "status": s.status} for s in self.steps
                ],
                "done": self.done,
            }
        )

    def lines_from(self, offset: int) -> list[LogLine]:
        return [line for line in self._lines if line.seq > offset]

    def _publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield events as they happen, then stop once the deployment is done.

        A client disconnecting simply abandons the generator; there is nothing
        to clean up because the runner owns all the real state.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("type") == "done":
                    return
        finally:
            self._subscribers.discard(queue)


class DeploymentJob:
    """One in-flight deployment: its log, its process, and its cancellation."""

    def __init__(self, deployment_id: str, repo_id: str) -> None:
        self.id = deployment_id
        self.repo_id = repo_id
        self.log = DeploymentLog()
        self.process: subprocess.Popen | None = None
        self.cancelled = False
        self.finished = asyncio.Event()

    def cancel(self) -> None:
        """Kill the running compose/git command.

        Cancelling before the ``up`` step means the previously deployed
        containers are left running.
        """
        self.cancelled = True
        if self.process is not None and self.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()


# Live jobs, keyed by deployment id.
_jobs: dict[str, DeploymentJob] = {}

# One lock per repo: deploys and stack actions serialise per repo while
# different repos proceed in parallel.
_repo_locks: dict[str, asyncio.Lock] = {}


def repo_lock(repo_id: str) -> asyncio.Lock:
    lock = _repo_locks.get(repo_id)
    if lock is None:
        lock = asyncio.Lock()
        _repo_locks[repo_id] = lock
    return lock


def active_job_for_repo(repo_id: str) -> DeploymentJob | None:
    for job in _jobs.values():
        if job.repo_id == repo_id and not job.finished.is_set():
            return job
    return None


def get_job(deployment_id: str) -> DeploymentJob | None:
    return _jobs.get(deployment_id)


def new_job(deployment_id: str, repo_id: str) -> DeploymentJob:
    job = DeploymentJob(deployment_id, repo_id)
    _jobs[deployment_id] = job
    return job


def release_job(deployment_id: str) -> None:
    _jobs.pop(deployment_id, None)


def load_saved_log(stored: str) -> DeploymentLog:
    """Rebuild a log from its persisted form so a finished deploy can replay."""
    log = DeploymentLog()
    try:
        data = json.loads(stored or "{}")
    except json.JSONDecodeError:
        return log

    for entry in data.get("lines", []):
        line = LogLine(seq=entry["seq"], text=entry["text"])
        log._lines.append(line)
        log._next_seq = max(log._next_seq, line.seq + 1)
    for entry in data.get("steps", []):
        log.steps.append(StepEvent(step=entry["step"], status=entry["status"]))
    log.done = data.get("done")
    return log


async def replay_and_follow(
    log: DeploymentLog, offset: int
) -> AsyncIterator[dict[str, Any]]:
    """Yield the saved log from ``offset`` and then live events.

    A deployment that already finished replays its stored log and emits
    ``done`` without touching the runner. Otherwise the replay is followed by
    live events from the running job.
    """
    if log.done is not None:
        for line in log.lines_from(offset):
            yield {"type": "line", "line": {"seq": line.seq, "text": line.text}}
        for step in log.steps:
            yield {"type": "step", "step": {"step": step.step, "status": step.status}}
        yield {"type": "done", **log.done}
        return

    for line in log.lines_from(offset):
        yield {"type": "line", "line": {"seq": line.seq, "text": line.text}}

    # Steps already emitted before this client connected are replayed too, so a
    # mid-deploy subscriber sees the same sequence as one present from the start.
    for step in log.steps:
        yield {"type": "step", "step": {"step": step.step, "status": step.status}}

    async for event in log.subscribe():
        yield event


async def run_streaming(
    job: DeploymentJob,
    argv: list[str],
    *,
    cwd=None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> int:
    """Run a command, feeding each output line into the job's log buffer.

    Blocking read and process management run in a worker thread so the event
    loop keeps serving SSE clients while a build is in progress.
    """
    job.log.command(argv)

    def _pump() -> int:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        job.process = proc
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                job.log.append(raw.rstrip("\n"))
        finally:
            proc.stdout.close()
            proc.wait()
        job.process = None
        return proc.returncode

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_pump), timeout=timeout or settings.compose_timeout_seconds
        )
    except asyncio.TimeoutError:
        job.log.append("! command timed out")
        return 124


def new_deployment_id() -> str:
    return str(uuid.uuid4())