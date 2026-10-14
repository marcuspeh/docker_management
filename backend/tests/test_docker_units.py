"""Container and network mapping, exercised without a Docker daemon."""

from __future__ import annotations

import pytest

from app.services import docker_service


class FakeContainer:
    def __init__(self, *, name="web-1", project="my-app", service="web",
                 self_label="false", ports=None, networks=None, state="running"):
        self.id = ((name.replace("-", "") * 12).ljust(64, "0"))[:64]
        self.short_id = self.id[:12]
        labels = {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
        }
        if self_label != "false":
            labels["portal.self"] = self_label
        self.attrs = {
            "Id": self.id,
            "Name": f"/{name}",
            "Created": "2026-10-01T10:00:00.000000000Z",
            "Config": {"Image": "nginx:1.27", "Labels": labels},
            "State": {
                "Status": state,
                "ExitCode": 0 if state == "running" else 137,
                "StartedAt": "2026-10-01T10:00:05.000000000Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
            },
            "NetworkSettings": {
                "Networks": {n: {} for n in (networks or ["app_default"])},
                "Ports": ports if ports is not None else {
                    "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}],
                    "443/tcp": None,
                },
            },
        }


class TestContainerMapping:
    def test_identity_and_labels(self):
        out = docker_service.container_to_out(
            FakeContainer(), {"my-app": "repo-1"}
        )
        assert out.id == out.full_id[:12]
        assert len(out.full_id) == 64
        assert out.name == "web-1"
        assert out.image == "nginx:1.27"
        assert out.state == "running"

    def test_repo_id_comes_from_compose_project_label(self):
        out = docker_service.container_to_out(
            FakeContainer(project="my-app"), {"my-app": "repo-1"}
        )
        assert out.repo_id == "repo-1"
        assert out.service == "web"

    def test_unknown_project_has_no_repo_id(self):
        out = docker_service.container_to_out(
            FakeContainer(project="other"), {"my-app": "repo-1"}
        )
        assert out.repo_id is None

    def test_ports(self):
        out = docker_service.container_to_out(FakeContainer())
        by_port = {p.container_port: p for p in out.ports}
        assert by_port[80].host_port == 8080
        assert by_port[80].host_ip == "0.0.0.0"
        assert by_port[80].protocol == "tcp"
        # An unpublished port still appears, with no host binding.
        assert by_port[443].host_port is None

    def test_udp_port_protocol(self):
        out = docker_service.container_to_out(
            FakeContainer(ports={"53/udp": [{"HostIp": "", "HostPort": "5353"}]})
        )
        assert out.ports[0].protocol == "udp"
        assert out.ports[0].container_port == 53

    def test_networks_and_timestamps(self):
        out = docker_service.container_to_out(
            FakeContainer(networks=["a", "b"])
        )
        assert sorted(out.networks) == ["a", "b"]
        assert out.created_at.year == 2026
        assert out.started_at is not None

    def test_exited_container_keeps_exit_code(self):
        out = docker_service.container_to_out(FakeContainer(state="exited"))
        assert out.state == "exited"
        assert out.exit_code == 137

    @pytest.mark.parametrize("label", ["true", "True"])
    def test_self_container_detected(self, label):
        assert docker_service.is_self(FakeContainer(self_label=label)) is True

    def test_other_container_not_self(self):
        assert docker_service.is_self(FakeContainer()) is False

    def test_container_without_labels_is_not_self(self):
        container = FakeContainer()
        container.attrs["Config"]["Labels"] = {}
        assert docker_service.is_self(container) is False


class FakeNetwork:
    def __init__(self, name, *, builtin=False, compose=False):
        labels = {"com.docker.compose.project": "proj"} if compose else {}
        self.attrs = {
            "Id": (name * 8)[:64],
            "Name": name,
            "Driver": "bridge",
            "Scope": "local",
            "Internal": False,
            "Labels": labels,
            "IPAM": {"Config": [{"Subnet": "172.20.0.0/16"}]},
            "Containers": {"c1": {}, "c2": {}},
        }


class TestNetworkMapping:
    @pytest.mark.parametrize("name", ["bridge", "host", "none"])
    def test_builtin_networks_flagged(self, name):
        out = docker_service._network_to_out(FakeNetwork(name, builtin=True))
        assert out.builtin is True

    def test_compose_managed_detected_from_label(self):
        out = docker_service._network_to_out(FakeNetwork("app_default", compose=True))
        assert out.compose_managed is True

    def test_default_suffix_alone_is_not_compose_managed(self):
        """Ownership comes from the label, so a user's `_default` stays deletable."""
        out = docker_service._network_to_out(FakeNetwork("my-app_default"))
        assert out.compose_managed is False

    def test_user_network_is_plain(self):
        out = docker_service._network_to_out(FakeNetwork("shared"))
        assert out.builtin is False
        assert out.compose_managed is False

    def test_subnet_and_container_count(self):
        out = docker_service._network_to_out(FakeNetwork("shared"))
        assert out.subnet == "172.20.0.0/16"
        assert out.container_count == 2


class TestLogFollowers:
    """Two followers are needed because the SDK merges stdout and stderr."""

    class LoggingContainer:
        def __init__(self, with_stderr=True):
            self.attrs = {"Id": "a" * 64}
            self.with_stderr = with_stderr

        def logs(self, stdout=True, stderr=False, timestamps=False,
                 tail="all", since=None, follow=False):
            ts = "2026-10-01T10:05:00.000000000Z"
            if stdout:
                yield f"{ts} out one\n"
                yield f"{ts} out two\n"
            if stderr and self.with_stderr:
                yield f"{ts} err line\n"

    async def _drain(self, container):
        from app.services import docker_service as svc

        original = svc.resolve_container
        svc.resolve_container = lambda cid: container
        try:
            events = []
            async for ev in svc.stream_logs("x", tail=10):
                events.append(ev)
                if ev["type"] == "end":
                    break
            return events
        finally:
            svc.resolve_container = original

    async def test_stdout_and_stderr_are_tagged_separately(self):
        events = await self._drain(self.LoggingContainer())
        tagged = {e["stream"] for e in events if e["type"] == "log"}
        assert tagged == {"stdout", "stderr"}

    async def test_timestamps_are_parsed(self):
        events = await self._drain(self.LoggingContainer())
        first = next(e for e in events if e["type"] == "log")
        assert first["time"].startswith("2026-10-01T10:05:00")

    async def test_tty_container_reports_everything_as_stdout(self):
        """With a TTY there is no separate stderr stream, which is expected."""
        events = await self._drain(self.LoggingContainer(with_stderr=False))
        assert all(e["stream"] == "stdout" for e in events if e["type"] == "log")

    async def test_stream_ends_with_end_event(self):
        events = await self._drain(self.LoggingContainer())
        assert events[-1]["type"] == "end"