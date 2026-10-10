"""Repo registration and the deploy pipeline, end to end over HTTP."""

from __future__ import annotations

import json

import pytest

from app.errors import ErrorCode


def _sse_events(text: str) -> list[dict]:
    """Parse an SSE body into dicts tagged with their event name.

    The payloads carry no type field of their own: ``line`` is {seq, text},
    ``step`` is {step, status} and ``done`` is {status, commitSha, ...}, so the
    event name is what distinguishes them.
    """
    events: list[dict] = []
    name = None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            payload = json.loads(line[5:])
            payload["type"] = name
            events.append(payload)
    return events


def _steps(events: list[dict]) -> list[tuple[str, str]]:
    return [(e["step"], e["status"]) for e in events if e["type"] == "step"]


def _text(events: list[dict]) -> str:
    return "\n".join(e.get("text", "") for e in events if e["type"] == "line")


class TestRepoCrud:
    def test_create_reads_default_branch_from_remote(self, client, bare_repo):
        r = client.post("/api/scm/repos", json={"name": "My App!", "url": str(bare_repo)})
        assert r.status_code == 201
        body = r.json()
        assert body["defaultBranch"] == "main"
        # Nothing is cloned until the first deploy.
        assert body["cloned"] is False
        assert body["path"] == "/"
        assert body["composeFile"] == "docker-compose.yml"

    def test_unreachable_remote_is_rejected(self, client):
        r = client.post(
            "/api/scm/repos", json={"name": "x", "url": "file:///nope/nope.git"}
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.REPO_UNREACHABLE

    def test_duplicate_name_gets_its_own_slug(self, client, bare_repo):
        first = client.post("/api/scm/repos", json={"name": "Dup", "url": str(bare_repo)})
        second = client.post("/api/scm/repos", json={"name": "Dup", "url": str(bare_repo)})
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] != second.json()["id"]

    @pytest.mark.parametrize("path", ["../etc", "/a/../../etc"])
    def test_path_escape_rejected(self, client, bare_repo, path):
        r = client.post(
            "/api/scm/repos",
            json={"name": "x", "url": str(bare_repo), "path": path},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.INVALID_PATH

    def test_blank_name_rejected(self, client, bare_repo):
        r = client.post("/api/scm/repos", json={"name": "   ", "url": str(bare_repo)})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.INVALID_NAME

    def test_branches_available_before_clone(self, client, bare_repo):
        repo = client.post(
            "/api/scm/repos", json={"name": "b", "url": str(bare_repo)}
        ).json()
        r = client.get(f"/api/scm/repos/{repo['id']}/branches")
        assert r.status_code == 200
        assert {b["name"] for b in r.json()["branches"]} == {"main", "develop"}

    def test_commits_require_a_clone(self, client, bare_repo):
        repo = client.post(
            "/api/scm/repos", json={"name": "c", "url": str(bare_repo)}
        ).json()
        r = client.get(f"/api/scm/repos/{repo['id']}/commits?branch=main")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == ErrorCode.NOT_CLONED

    def test_patch_renames_but_not_url(self, client, bare_repo):
        repo = client.post(
            "/api/scm/repos", json={"name": "old", "url": str(bare_repo)}
        ).json()
        r = client.patch(
            f"/api/scm/repos/{repo['id']}",
            json={"name": "new", "url": "file:///other.git"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "new"
        # The URL is immutable so an existing clone is never orphaned.
        assert r.json()["url"] == repo["url"]

    def test_patch_normalises_path(self, client, bare_repo):
        repo = client.post(
            "/api/scm/repos", json={"name": "p", "url": str(bare_repo)}
        ).json()
        r = client.patch(f"/api/scm/repos/{repo['id']}", json={"path": "svc/"})
        assert r.json()["path"] == "/svc"

    def test_missing_repo_is_404(self, client):
        assert client.get("/api/scm/repos/nope").status_code == 404

    def test_delete_removes_records(self, client, bare_repo):
        repo = client.post(
            "/api/scm/repos", json={"name": "d", "url": str(bare_repo)}
        ).json()
        assert client.delete(f"/api/scm/repos/{repo['id']}").status_code == 204
        assert client.get("/api/scm/repos").json() == []


class TestDeployPipeline:
    @pytest.fixture(autouse=True)
    def _docker(self, fake_docker, monkeypatch):
        monkeypatch.setenv("PATH", f"{fake_docker}{':'}{__import__('os').environ['PATH']}")

    def _create(self, client, url, **kw):
        payload = {"name": "Deploy Test", "url": str(url), **kw}
        return client.post("/api/scm/repos", json=payload).json()

    def _run_deploy(self, client, repo_id, branch="main", **kw):
        r = client.post(
            f"/api/scm/repos/{repo_id}/deployments", json={"branch": branch, **kw}
        )
        assert r.status_code == 202
        deployment_id = r.json()["id"]
        with client.stream("GET", f"/api/scm/deployments/{deployment_id}/logs") as s:
            body = "".join(s.iter_text())
        detail = client.get(f"/api/scm/deployments/{deployment_id}").json()
        return detail, body

    def test_successful_deploy_records_commit(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        detail, body = self._run_deploy(client, repo["id"])

        assert detail["status"] == "success"
        assert detail["commitSha"] and len(detail["commitSha"]) == 40
        assert detail["commitMessage"] == "first commit"
        assert detail["error"] is None

        events = _sse_events(body)
        assert events[-1]["type"] == "done"
        assert events[-1]["status"] == "success"

        steps = _steps(events)
        assert ("clone", "started") in steps
        assert ("checkout", "succeeded") in steps
        assert ("build", "succeeded") in steps
        assert ("up", "succeeded") in steps
        assert ("networks", "succeeded") in steps

    def test_repo_is_reported_as_cloned_after_deploy(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        self._run_deploy(client, repo["id"])
        assert client.get(f"/api/scm/repos/{repo['id']}").json()["cloned"] is True

    def test_second_deploy_fetches_instead_of_cloning(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        self._run_deploy(client, repo["id"])
        detail, body = self._run_deploy(client, repo["id"])
        assert detail["status"] == "success"
        steps = _steps(_sse_events(body))
        assert ("fetch", "succeeded") in steps
        assert ("clone", "started") not in steps

    def test_failed_build_leaves_stack_untouched(self, client, bare_repo, monkeypatch):
        """The key safety property: build failure must never reach `up`."""
        repo = self._create(client, bare_repo)
        monkeypatch.setenv("FAKE_BUILD_FAIL", "1")

        detail, body = self._run_deploy(client, repo["id"])
        assert detail["status"] == "failed"
        assert "Running containers are unchanged" in detail["error"]

        steps = _steps(_sse_events(body))
        assert ("build", "failed") in steps
        assert not any(s[0] == "up" for s in steps)

    def test_missing_compose_file_fails_at_checkout(self, client, broken_repo):
        repo = self._create(client, broken_repo)
        detail, body = self._run_deploy(client, repo["id"])
        assert detail["status"] == "failed"
        assert "compose file" in detail["error"]
        # The failure is reported at checkout, before build or up run.
        steps = _steps(_sse_events(body))
        assert ("checkout", "failed") in steps
        assert not any(s[0] in ("build", "up") for s in steps)

    def test_concurrent_deploy_is_refused(self, client, bare_repo, monkeypatch):
        repo = self._create(client, bare_repo)
        first = client.post(
            f"/api/scm/repos/{repo['id']}/deployments", json={"branch": "main"}
        )
        assert first.status_code == 202

        second = client.post(
            f"/api/scm/repos/{repo['id']}/deployments", json={"branch": "main"}
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == ErrorCode.DEPLOY_IN_PROGRESS
        assert "deploymentId" in second.json()["error"]["detail"]

        with client.stream(
            "GET", f"/api/scm/deployments/{first.json()['id']}/logs"
        ) as s:
            "".join(s.iter_text())

    def test_deploy_passes_git_env_to_compose(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        _, body = self._run_deploy(client, repo["id"])
        assert "GIT_BRANCH=main" in _text(_sse_events(body))

    def test_compose_argv_is_echoed(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        _, body = self._run_deploy(client, repo["id"])
        text = _text(_sse_events(body))
        assert "docker compose -p deploy-test" in text
        assert "--project-directory" in text

    def test_history_is_newest_first(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        self._run_deploy(client, repo["id"])
        self._run_deploy(client, repo["id"])
        history = client.get(f"/api/scm/repos/{repo['id']}/deployments").json()
        assert len(history) == 2
        assert history[0]["startedAt"] >= history[1]["startedAt"]

    def test_logs_replay_from_offset(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        detail, body = self._run_deploy(client, repo["id"])

        seqs = [e["seq"] for e in _sse_events(body) if "seq" in e]
        assert seqs == sorted(seqs)

        with client.stream(
            "GET", f"/api/scm/deployments/{detail['id']}/logs?offset=2"
        ) as s:
            replayed = "".join(s.iter_text())
        replay_seqs = [e["seq"] for e in _sse_events(replayed) if "seq" in e]
        assert replay_seqs == [n for n in seqs if n > 2]

    def test_cancel_of_settled_deploy_is_rejected(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        detail, _ = self._run_deploy(client, repo["id"])
        r = client.post(f"/api/scm/deployments/{detail['id']}/cancel")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == ErrorCode.INVALID_STATE

    def test_stack_action_rejects_unknown(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        r = client.post(f"/api/scm/repos/{repo['id']}/stack/bogus")
        assert r.status_code == 404

    def test_deploy_unknown_branch_fails(self, client, bare_repo):
        repo = self._create(client, bare_repo)
        detail, _ = self._run_deploy(client, repo["id"], branch="nope")
        assert detail["status"] == "failed"