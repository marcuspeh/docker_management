"""Log buffering, SSE replay, cancel and per-repo locking."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services import jobs


async def collect(log: jobs.DeploymentLog, offset: int = 0) -> list[dict]:
    return [event async for event in jobs.replay_and_follow(log, offset)]


class TestLogBuffer:
    async def test_sequences_increment(self):
        log = jobs.DeploymentLog()
        for i in range(3):
            log.append(f"line {i}")
        assert [line.seq for line in log._lines] == [1, 2, 3]

    async def test_ring_buffer_is_bounded(self):
        log = jobs.DeploymentLog(limit=5)
        for i in range(20):
            log.append(f"line {i}")
        assert len(log._lines) == 5
        assert log._lines[-1].text == "line 19"

    async def test_command_is_echoed_with_dollar_prefix(self):
        log = jobs.DeploymentLog()
        log.command(["docker", "compose", "up"])
        assert log._lines[0].text == "$ docker compose up"

    async def test_steps_are_recorded(self):
        log = jobs.DeploymentLog()
        log.step("build", "started")
        log.step("build", "succeeded")
        assert [(s.step, s.status) for s in log.steps] == [
            ("build", "started"),
            ("build", "succeeded"),
        ]


class TestReplay:
    async def test_replays_from_offset(self):
        """A reconnecting client resumes with ?offset= and sees only new lines."""
        log = jobs.DeploymentLog()
        for i in range(5):
            log.append(f"line {i}")
        log.finish({"status": "success", "commitSha": None,
                    "commitMessage": None, "error": None})

        events = await collect(log, offset=2)
        seqs = [e["line"]["seq"] for e in events if e["type"] == "line"]
        assert seqs == [3, 4, 5]
        assert events[-1]["type"] == "done"

    async def test_offset_zero_replays_everything(self):
        log = jobs.DeploymentLog()
        for i in range(3):
            log.append(f"line {i}")
        log.finish({"status": "success", "commitSha": None,
                    "commitMessage": None, "error": None})
        events = await collect(log, offset=0)
        assert len([e for e in events if e["type"] == "line"]) == 3

    async def test_finished_deploy_replays_saved_log(self):
        """A completed deployment still streams its output."""
        log = jobs.DeploymentLog()
        log.append("built")
        log.step("build", "succeeded")
        log.finish({"status": "success", "commitSha": "abc",
                    "commitMessage": "msg", "error": None})

        restored = jobs.load_saved_log(log.snapshot())
        events = await collect(restored, offset=0)
        kinds = [e["type"] for e in events]
        assert "line" in kinds and "step" in kinds
        assert events[-1]["type"] == "done"
        assert events[-1]["commitSha"] == "abc"

    async def test_snapshot_round_trip_preserves_sequence(self):
        log = jobs.DeploymentLog()
        for i in range(4):
            log.append(f"line {i}")
        log.step("up", "started")
        log.finish({"status": "failed", "commitSha": None,
                    "commitMessage": None, "error": "boom"})

        restored = jobs.load_saved_log(log.snapshot())
        assert [l.seq for l in restored._lines] == [1, 2, 3, 4]
        assert restored.done["status"] == "failed"

    @pytest.mark.parametrize("stored", ["", "not json", "{}", "[]"])
    def test_corrupt_stored_log_degrades(self, stored):
        """A malformed log must not break the stream."""
        assert jobs.load_saved_log(stored).done is None

    async def test_live_subscriber_receives_events_then_done(self):
        log = jobs.DeploymentLog()
        received: list[dict] = []

        async def consume():
            async for event in log.subscribe():
                received.append(event)
                if event["type"] == "done":
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)  # let the subscriber register
        log.append("live line")
        log.finish({"status": "success", "commitSha": None,
                    "commitMessage": None, "error": None})
        await asyncio.wait_for(task, timeout=5)

        assert received[-1]["type"] == "done"
        assert any(r.get("line", {}).get("text") == "live line" for r in received)


class TestStreamingAndCancel:
    async def test_streams_output_and_exit_code(self):
        job = jobs.DeploymentJob("d1", "r1")
        rc = await jobs.run_streaming(job, ["/bin/sh", "-c", "echo one; echo two"])
        assert rc == 0
        texts = [line.text for line in job.log._lines]
        assert texts[0].startswith("$ /bin/sh")
        assert "one" in texts and "two" in texts

    async def test_non_zero_exit_is_reported(self):
        job = jobs.DeploymentJob("d2", "r2")
        rc = await jobs.run_streaming(job, ["/bin/sh", "-c", "exit 3"])
        assert rc == 3

    async def test_cancel_kills_the_process(self):
        job = jobs.DeploymentJob("d3", "r3")
        task = asyncio.create_task(
            jobs.run_streaming(job, ["/bin/sh", "-c", "sleep 60"])
        )
        await asyncio.sleep(0.4)
        job.cancel()
        rc = await asyncio.wait_for(task, timeout=20)
        assert job.cancelled is True
        assert rc != 0

    async def test_cancel_is_safe_when_nothing_runs(self):
        jobs.DeploymentJob("d4", "r4").cancel()


class TestRepoLocks:
    async def test_same_repo_is_serialised(self):
        lock = jobs.repo_lock("r1")
        assert jobs.repo_lock("r1") is lock

    async def test_different_repos_are_independent(self):
        assert jobs.repo_lock("r1") is not jobs.repo_lock("r2")