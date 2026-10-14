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


def _redact(arg: str) -> str:
    """Strip ``user:password@`` from anything that looks like a URL.

    A repository registered as ``https://token@host/org/repo.git`` would
    otherwise leak the token into the streamed log and the database.
    """
    scheme, sep, rest = arg.partition("://")
    if not sep or "@" not in rest:
        return arg
    userinfo, _, host = rest.rpartition("@")
    if not userinfo:
        return arg
    user = userinfo.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


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
        # Subscriber queue -> the loop it is awaited on. Lines are appended from
        # a worker thread (see run_streaming), so publishing has to hop back
        # onto the owning loop rather than touching the queue directly.
        self._subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._lock = asyncio.Lock()

    def append(self, text: str) -> LogLine:
        line = LogLine(seq=self._next_seq, text=text)
        self._next_seq += 1
        self._lines.append(line)
        self._publish({"type": "line", "line": {"seq": line.seq, "text": line.text}})
        return line

    def command(self, argv: list[str]) -> None:
        """Echo the command before its output, prefixed with ``$``.

        Credentials embedded in a remote URL are redacted: this text is streamed
        to every client watching the deploy and persisted in ``deployment.log``.
        """
        self.append("$ " + " ".join(_redact(arg) for arg in argv))

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

    def evicted_before(self, offset: int) -> bool:
        """True when the client wants lines the ring has already discarded."""
        return bool(self._lines) and self._lines[0].seq > offset + 1

    def truncation_notice(self, offset: int) -> str:
        return (
            f"! output truncated: lines up to {self._lines[0].seq - 1} are no "
            "longer buffered"
        )

    def _publish(self, event: dict[str, Any]) -> None:
        # The terminal event is what ends a subscriber's stream, so it must
        # never be dropped: a full queue drops the oldest line to make room.
        terminal = event.get("type") == "done"
        for queue, loop in list(self._subscribers.items()):
            self._offer(queue, loop, event, terminal)

    @staticmethod
    def _offer(
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        event: dict[str, Any],
        terminal: bool,
    ) -> None:
        def put() -> None:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                if not terminal:
                    return
                # Make room by discarding the oldest buffered event.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            put()
        else:
            loop.call_soon_threadsafe(put)

    def _register(self) -> tuple[asyncio.Queue, asyncio.AbstractEventLoop]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[queue] = loop
        return queue, loop

    def _unregister(self, queue: asyncio.Queue) -> None:
        self._subscribers.pop(queue, None)

    async def _follow(self, queue: asyncio.Queue) -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("type") == "done":
                    return
        finally:
            self._unregister(queue)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield events as they happen, then stop once the deployment is done.

        A client disconnecting simply abandons the generator; there is nothing
        to clean up because the runner owns all the real state.
        """
        queue, _loop = self._register()
        async for event in self._follow(queue):
            yield event


class DeploymentJob:
    """One in-flight deployment: its log, its process, and its cancellation."""

    def __init__(self, deployment_id: str, repo_id: str) -> None:
        self.id = deployment_id
        self.repo_id = repo_id
        self.log = DeploymentLog()
        # The asyncio child spawned by run_streaming, if one is running.
        self.process: asyncio.subprocess.Process | None = None
        self.cancelled = False
        self.finished = asyncio.Event()

    def cancel(self) -> None:
        """Kill the running compose/git command.

        Cancelling before the ``up`` step means the previously deployed
        containers are left running. Only the flag is set here: the child is
        stopped by whoever owns the loop, since terminating a process from an
        arbitrary thread is not safe.
        """
        self.cancelled = True
        proc = self.process
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()


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
    if not isinstance(data, dict):
        return log

    for entry in data.get("lines", []):
        line = LogLine(seq=entry["seq"], text=entry["text"])
        log._lines.append(line)
        log._next_seq = max(log._next_seq, line.seq + 1)
    for entry in data.get("steps", []):
        log.steps.append(StepEvent(step=entry["step"], status=entry["status"]))
    log.done = data.get("done")
    return log


async def _replay(log: DeploymentLog, offset: int) -> AsyncIterator[dict[str, Any]]:
    """Replay buffered lines from ``offset``, flagging any evicted gap."""
    if log.evicted_before(offset):
        yield {
            "type": "line",
            "line": {"seq": offset, "text": log.truncation_notice(offset)},
        }
    for line in log.lines_from(offset):
        yield {"type": "line", "line": {"seq": line.seq, "text": line.text}}


async def replay_and_follow(
    log: DeploymentLog, offset: int, *, live: bool = False
) -> AsyncIterator[dict[str, Any]]:
    """Yield the saved log from ``offset`` and then live events.

    A deployment that already finished replays its stored log and emits
    ``done`` without touching the runner. Otherwise the replay is followed by
    live events from the running job.

    ``live`` says whether a runner owns this log. Without it there is nothing
    that will ever publish, so a stored log with no terminal payload (a deploy
    interrupted by a restart) gets a synthesised ``done`` instead of hanging.
    """
    if log.done is not None:
        async for event in _replay(log, offset):
            yield event
        for step in log.steps:
            yield {"type": "step", "step": {"step": step.step, "status": step.status}}
        yield {"type": "done", **log.done}
        return

    if not live:
        # Nothing owns this log, so whatever is buffered is all there is.
        async for event in _replay(log, offset):
            yield event
        yield {"type": "done", "status": "failed", "commitSha": None,
               "commitMessage": None,
               "error": "This deployment's output is no longer available."}
        return

    # Subscribe before snapshotting the buffer, otherwise anything published
    # during the replay would be lost: the replay awaits on the client socket,
    # so the runner can finish in that window.
    queue, _loop = log._register()
    highest = offset
    try:
        async for event in _replay(log, offset):
            if event["type"] == "line":
                highest = max(highest, event["line"]["seq"])
            yield event

        # Steps carry no sequence number, so a mid-deploy client sees the whole
        # step list again. It is the full history by design: the client keys
        # them and ignores repeats.
        for step in log.steps:
            yield {"type": "step", "step": {"step": step.step, "status": step.status}}

        async for event in log._follow(queue):
            # The queue may already hold lines the replay just sent.
            if event.get("type") == "line":
                seq = event["line"]["seq"]
                if seq <= highest:
                    continue
                highest = seq
            yield event
            if event.get("type") == "done":
                return
    finally:
        log._unregister(queue)


async def run_streaming(
    job: DeploymentJob,
    argv: list[str],
    *,
    cwd=None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> int:
    """Run a command, feeding each output line into the job's log buffer.

    The child is spawned on the event loop with ``create_subprocess_exec`` so a
    timeout can actually kill it. Running it in a worker thread instead would
    leave the process alive after the timeout fired, still mutating containers
    while the deployment had already been recorded as failed.
    """
    job.log.command(argv)

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    job.process = proc

    async def pump() -> None:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            job.log.append(raw.decode(errors="replace").rstrip("\n"))

    try:
        await asyncio.wait_for(
            pump(), timeout=timeout or settings.compose_timeout_seconds
        )
    except asyncio.TimeoutError:
        job.log.append("! command timed out")
        await _terminate(proc)
        return 124
    finally:
        job.process = None

    return proc.returncode if proc.returncode is not None else await proc.wait()


async def _terminate(proc) -> None:
    """Stop a child and reap it, escalating to SIGKILL if it ignores SIGTERM."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()


def new_deployment_id() -> str:
    return str(uuid.uuid4())