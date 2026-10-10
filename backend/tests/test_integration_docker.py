"""Integration tests against a real Docker daemon.

Run with ``pytest -m docker``. Skipped automatically when no daemon is
reachable, so the unit suite stays green on a machine without Docker.
"""

from __future__ import annotations

import textwrap

import pytest

from .conftest import requires_docker

pytestmark = [pytest.mark.docker, requires_docker]

COMPOSE_FIXTURE = textwrap.dedent(
    """
    services:
      web:
        image: nginx:alpine
        command: ["sh", "-c", "echo started; sleep 300"]
    """
)

BROKEN_COMPOSE = textwrap.dedent(
    """
    services:
      web:
        image: nginx:alpine
        command: ["sh", "-c", "exit 1"]
    """
)


def _make_repo(tmp_path, compose_body: str, name: str = "Fixture") -> str:
    """A bare git repo whose main branch holds the given compose file."""
    import subprocess

    remote = tmp_path / f"{name}.git"
    work = tmp_path / f"{name}-work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True,
                   capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(work)], check=True,
                   capture_output=True)
    (work / "docker-compose.yml").write_text(compose_body)
    subprocess.run(["git", "-C", str(work), "add", "."], check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "-C", str(work), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "fixture"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True,
                   capture_output=True)
    return str(remote)


def _deploy(client, repo_id, branch="main"):
    import json

    r = client.post(f"/api/scm/repos/{repo_id}/deployments", json={"branch": branch})
    assert r.status_code == 202, r.text
    deployment_id = r.json()["id"]
    with client.stream("GET", f"/api/scm/deployments/{deployment_id}/logs") as s:
        s.join_text_stream = None
        body = "".join(s.iter_text())
    events = [json.loads(l[5:]) for l in body.splitlines() if l.startswith("data:")]
    detail = client.get(f"/api/scm/deployments/{deployment_id}").json()
    return detail, events


class TestRealDeploy:
    def test_deploy_brings_up_containers(self, client, tmp_path):
        repo = client.post(
            "/api/scm/repos",
            json={"name": "Fixture", "url": _make_repo(tmp_path, COMPOSE_FIXTURE)},
        ).json()

        detail, _ = _deploy(client, repo["id"])
        assert detail["status"] == "success", detail
        assert detail["commitSha"]

        containers = client.get(f"/api/containers?all=true&repoId={repo['id']}").json()
        assert len(containers) == 1
        assert containers[0]["state"] == "running"
        assert containers[0]["service"] == "web"

        client.delete(f"/api/scm/repos/{repo['id']}?teardown=true")

    def test_failed_build_leaves_previous_container_running(self, client, tmp_path):
        """A broken compose must not disturb what is already deployed."""
        repo = client.post(
            "/api/scm/repos",
            json={"name": "Fixture", "url": _make_repo(tmp_path, COMPOSE_FIXTURE)},
        ).json()

        first, _ = _deploy(client, repo["id"])
        assert first["status"] == "success"

        before = client.get(f"/api/containers?all=true&repoId={repo['id']}").json()
        assert before and before[0]["state"] == "running"

        # Redeploy the same repo from a commit whose compose file is broken.
        import subprocess

        remote = repo["url"]
        work = tmp_path / "update"
        subprocess.run(["git", "clone", remote, str(work)], check=True,
                       capture_output=True)
        (work / "docker-compose.yml").write_text(BROKEN_COMPOSE)
        subprocess.run(["git", "-C", str(work), "add", "."], check=True,
                       capture_output=True)
        subprocess.run(
            ["git", "-C", str(work), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-m", "break"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True,
                       capture_output=True)

        second, _ = _deploy(client, repo["id"])
        assert second["status"] == "failed"

        after = client.get(f"/api/containers?all=true&repoId={repo['id']}").json()
        assert after and after[0]["state"] == "running"

        client.delete(f"/api/scm/repos/{repo['id']}?teardown=true")

    def test_network_attachment_survives_redeploy(self, client, tmp_path):
        repo = client.post(
            "/api/scm/repos",
            json={"name": "Fixture", "url": _make_repo(tmp_path, COMPOSE_FIXTURE)},
        ).json()
        _deploy(client, repo["id"])

        network = client.post("/api/networks", json={"name": "attach-test-net"}).json()
        container = client.get(f"/api/containers?repoId={repo['id']}").json()[0]

        r = client.post(
            f"/api/networks/{network['id']}/connect",
            json={"containerIds": [container["id"]]},
        )
        assert r.json()["connected"] == [container["id"]]

        _deploy(client, repo["id"])

        after = client.get(f"/api/containers?repoId={repo['id']}").json()[0]
        assert "attach-test-net" in after["networks"]

        client.delete(f"/api/networks/{network['id']}")
        client.delete(f"/api/scm/repos/{repo['id']}?teardown=true")

    def test_builtin_network_delete_is_refused(self, client):
        r = client.delete("/api/networks/bridge")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "PROTECTED"


class TestRealContainers:
    def test_logs_tag_stdout_and_stderr(self, client, tmp_path):
        compose = textwrap.dedent(
            """
            services:
              web:
                image: nginx:alpine
                command: ["sh", "-c", "echo to-stdout; echo to-stderr >&2; sleep 300"]
            """
        )
        repo = client.post(
            "/api/scm/repos",
            json={"name": "Logs", "url": _make_repo(tmp_path, compose, "Logs")},
        ).json()
        _deploy(client, repo["id"])

        container = client.get(f"/api/containers?repoId={repo['id']}").json()[0]
        import json

        with client.stream(
            "GET", f"/api/containers/{container['id']}/logs?tail=50"
        ) as s:
            body = "".join(s.iter_text())
        events = [json.loads(l[5:]) for l in body.splitlines() if l.startswith("data:")]

        streams = {e.get("stream") for e in events if "stream" in e}
        assert "stdout" in streams
        assert any(
            e.get("stream") == "stdout" and "to-stdout" in e.get("msg", "")
            for e in events
        )
        assert any(
            e.get("stream") == "stderr" and "to-stderr" in e.get("msg", "")
            for e in events
        )

        client.delete(f"/api/scm/repos/{repo['id']}?teardown=true")

    def test_stop_and_start(self, client, tmp_path):
        repo = client.post(
            "/api/scm/repos",
            json={"name": "Lifecycle", "url": _make_repo(tmp_path, COMPOSE_FIXTURE,
                                                          "Lifecycle")},
        ).json()
        _deploy(client, repo["id"])
        container = client.get(f"/api/containers?repoId={repo['id']}").json()[0]

        stopped = client.post(f"/api/containers/{container['id']}/stop", json={"timeout": 1})
        assert stopped.status_code == 200
        assert stopped.json()["state"] in ("exited", "stopped")

        started = client.post(f"/api/containers/{container['id']}/start")
        assert started.status_code == 200
        assert started.json()["state"] == "running"

        restarted = client.post(f"/api/containers/{container['id']}/restart")
        assert restarted.status_code == 200

        # Short and full ids are both accepted.
        assert client.post(f"/api/containers/{container['fullId']}/stop",
                           json={"timeout": 1}).status_code == 200

        client.delete(f"/api/scm/repos/{repo['id']}?teardown=true")

    def test_log_download(self, client, tmp_path):
        repo = client.post(
            "/api/scm/repos",
            json={"name": "Download", "url": _make_repo(tmp_path, COMPOSE_FIXTURE,
                                                         "Download")},
        ).json()
        _deploy(client, repo["id"])
        container = client.get(f"/api/containers?repoId={repo['id']}").json()[0]

        r = client.get(f"/api/containers/{container['id']}/logs/download?tail=all")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")

        client.delete(f"/api/scm/repos/{repo['id']}?teardown=true")