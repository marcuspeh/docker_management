"""Docker access through the Python SDK.

The SDK covers containers, logs and networks. Compose build/up/down go through
the CLI instead, because they need streaming progress output. Every call is
blocking, so each is wrapped in a worker thread.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

from ..config import settings
from ..errors import ApiError, ErrorCode
from ..schemas import ContainerOut, NetworkOut, PortOut

_client: docker.DockerClient | None = None

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"

BUILTIN_NETWORKS = {"bridge", "host", "none"}


def get_client() -> docker.DockerClient:
    """Shared SDK client bound to the host daemon via the mounted socket."""
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url=settings.docker_socket)
    return _client


async def _in_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))


def reset_client() -> None:
    """Drop the cached client. Used by tests and after a daemon restart."""
    global _client
    if _client is not None:
        with_close = getattr(_client, "close", None)
        if with_close:
            with_close()
    _client = None


def wrap_docker_error(exc: Exception, action: str) -> ApiError:
    if isinstance(exc, NotFound):
        return ApiError(ErrorCode.NOT_FOUND, "Resource not found.")
    return ApiError(
        ErrorCode.DOCKER_ERROR,
        f"Docker failed to {action}.",
        {"stderr": str(exc)},
    )


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def _ping_sync() -> dict[str, Any]:
    try:
        client = get_client()
        client.ping()
        return {
            "reachable": True,
            "serverVersion": client.version().get("Version"),
        }
    except DockerException:
        return {"reachable": False, "serverVersion": None}
    except Exception:
        return {"reachable": False, "serverVersion": None}


async def ping_docker() -> dict[str, Any]:
    """Report daemon reachability for /api/health."""
    return await _in_thread(_ping_sync)


# --------------------------------------------------------------------------- #
# Containers
# --------------------------------------------------------------------------- #
def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        raw = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ports(container) -> list[PortOut]:
    """Map NetworkSettings.Ports, which is ``{"80/tcp": [bindings] | None}``."""
    ports: list[PortOut] = []
    raw = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}

    for key, bindings in raw.items():
        container_port, _, protocol = key.partition("/")
        host_port = host_ip = None
        if bindings:
            first = bindings[0]
            host_port = first.get("HostPort")
            host_ip = first.get("HostIp")
        try:
            port_number = int(container_port)
        except ValueError:
            continue
        ports.append(
            PortOut(
                container_port=port_number,
                host_port=int(host_port) if host_port else None,
                host_ip=host_ip,
                protocol=protocol if protocol in ("tcp", "udp") else "tcp",
            )
        )
    return ports


def container_to_out(
    container, slug_to_repo: dict[str, str] | None = None
) -> ContainerOut:
    """Map an SDK container onto the API shape.

    ``com.docker.compose.project`` is the only link between a stored repo and a
    live container, so it is what ties a container back to its repo.
    """
    attrs = container.attrs
    labels = attrs.get("Config", {}).get("Labels") or {}
    state = (attrs.get("State") or {}).get("Status") or "unknown"
    project = labels.get(COMPOSE_PROJECT_LABEL)
    service = labels.get(COMPOSE_SERVICE_LABEL)

    networks = list(
        ((attrs.get("NetworkSettings") or {}).get("Networks") or {}).keys()
    )

    return ContainerOut(
        id=container.short_id,
        full_id=container.id,
        name=(attrs.get("Name") or "").lstrip("/"),
        image=(attrs.get("Config", {}).get("Image") or ""),
        state=state if state in {
            "running", "exited", "paused", "restarting", "created", "dead"
        } else "exited",
        status=(attrs.get("State") or {}).get("Status") or state,
        exit_code=(attrs.get("State") or {}).get("ExitCode"),
        ports=_ports(container),
        networks=networks,
        created_at=_parse_time(attrs.get("Created")) or datetime.now(timezone.utc),
        started_at=_parse_time((attrs.get("State") or {}).get("StartedAt")),
        finished_at=_parse_time((attrs.get("State") or {}).get("FinishedAt")),
        repo_id=(slug_to_repo or {}).get(project) if project else None,
        service=service,
    )


def resolve_container(container_id: str):
    """Look up a container by short or full id."""
    client = get_client()
    try:
        return client.containers.get(container_id)
    except NotFound:
        # Fall back to a prefix search for ids Docker does not index exactly.
        for container in client.containers.list(all=True):
            if container.id.startswith(container_id) or container.short_id == container_id:
                return container
    raise ApiError(ErrorCode.NOT_FOUND, "Container not found.")


def is_self(container) -> bool:
    labels = (container.attrs.get("Config") or {}).get("Labels") or {}
    return str(labels.get(settings.self_label, "")).lower() == "true"


def require_mutable_container(container_id: str):
    """Resolve a container, refusing the portal's own."""
    container = resolve_container(container_id)
    if is_self(container):
        raise ApiError(
            ErrorCode.PROTECTED,
            "The portal's own container cannot be modified.",
        )
    return container


def _list_containers_sync(
    all_: bool,
    network: str | None,
    repo_id: str | None,
    query: str | None,
    slug_to_repo: dict[str, str] | None,
) -> list[ContainerOut]:
    client = get_client()
    containers = client.containers.list(all=all_)

    out: list[ContainerOut] = []
    for container in containers:
        if is_self(container):
            continue
        item = container_to_out(container, slug_to_repo)
        if network and network not in item.networks:
            continue
        if repo_id and item.repo_id != repo_id:
            continue
        if query:
            needle = query.lower()
            if (
                needle not in item.name.lower()
                and needle not in item.full_id.lower()
                and needle not in item.image.lower()
            ):
                continue
        out.append(item)
    return out


async def list_containers(
    *,
    all_: bool = False,
    network: str | None = None,
    repo_id: str | None = None,
    query: str | None = None,
    slug_to_repo: dict[str, str] | None = None,
) -> list[ContainerOut]:
    return await _in_thread(
        _list_containers_sync, all_, network, repo_id, query, slug_to_repo
    )


def _list_project_containers_sync(slug: str) -> list[ContainerOut]:
    client = get_client()
    return [
        container_to_out(container)
        for container in client.containers.list(
            all=True, filters={"label": f"{COMPOSE_PROJECT_LABEL}={slug}"}
        )
    ]


async def list_project_containers(slug: str) -> list[ContainerOut]:
    """Containers belonging to a compose project, used for deploy detail."""
    return await _in_thread(_list_project_containers_sync, slug)


def _container_action_sync(container_id: str, action: str, timeout: int | None) -> Any:
    container = resolve_container(container_id)
    if action == "stop":
        return container.stop(timeout=timeout) if timeout is not None else container.stop()
    if action == "start":
        return container.start()
    if action == "restart":
        return container.restart()
    raise ApiError(ErrorCode.INVALID_STATE, f"Unknown container action: {action}")


async def container_action(
    container_id: str, action: str, timeout: int | None = None
) -> Any:
    container = require_mutable_container(container_id)
    try:
        if action == "stop":
            await _in_thread(
                container.stop, timeout if timeout is not None else 10
            )
        elif action == "start":
            await _in_thread(container.start)
        elif action == "restart":
            await _in_thread(container.restart)
        else:
            raise ApiError(
                ErrorCode.INVALID_STATE, f"Unknown container action: {action}"
            )
    except APIError as exc:
        raise wrap_docker_error(exc, action) from exc
    except DockerException as exc:
        raise wrap_docker_error(exc, action) from exc

    container.reload()
    return container_to_out(container)


# --------------------------------------------------------------------------- #
# Networks
# --------------------------------------------------------------------------- #
def _network_to_out(network, slug_to_compose: dict[str, str] | None = None) -> NetworkOut:
    attrs = network.attrs
    ipam = (attrs.get("IPAM") or {}).get("Config") or []
    subnet = ipam[0].get("Subnet") if ipam else None
    labels = attrs.get("Labels") or {}
    name = attrs.get("Name") or ""

    project = labels.get(COMPOSE_PROJECT_LABEL)
    compose_managed = bool(project) or name.endswith("_default")

    return NetworkOut(
        id=attrs.get("Id") or network.id,
        name=name,
        driver=attrs.get("Driver") or "bridge",
        scope=attrs.get("Scope") or "local",
        subnet=subnet,
        internal=bool(attrs.get("Internal")),
        builtin=name in BUILTIN_NETWORKS,
        compose_managed=compose_managed,
        container_count=len(attrs.get("Containers") or {}),
    )


def _list_networks_sync() -> list[NetworkOut]:
    return [_network_to_out(net) for net in get_client().networks.list()]


async def list_networks() -> list[NetworkOut]:
    return await _in_thread(_list_networks_sync)


def _create_network_sync(name: str, driver: str, internal: bool) -> Any:
    client = get_client()
    try:
        client.networks.get(name)
    except NotFound:
        pass
    else:
        raise ApiError(
            ErrorCode.NAME_TAKEN, f"A network named {name} already exists."
        )
    return client.networks.create(name, driver=driver, internal=internal)


async def create_network(name: str, driver: str = "bridge", internal: bool = False) -> NetworkOut:
    try:
        network = await _in_thread(_create_network_sync, name, driver, internal)
    except ApiError:
        raise
    except DockerException as exc:
        if "already exists" in str(exc).lower():
            raise ApiError(
                ErrorCode.NAME_TAKEN, f"A network named {name} already exists."
            ) from exc
        raise wrap_docker_error(exc, "create the network") from exc
    return _network_to_out(network)


def resolve_network(network_id: str):
    client = get_client()
    try:
        return client.networks.get(network_id)
    except NotFound:
        for network in client.networks.list():
            if network.attrs.get("Id") == network_id or network.attrs.get("Name") == network_id:
                return network
    raise ApiError(ErrorCode.NOT_FOUND, "Network not found.")


def require_mutable_network(network_id: str):
    """Resolve a network, refusing built-in and compose-owned networks."""
    network = resolve_network(network_id)
    described = _network_to_out(network)
    if described.builtin:
        raise ApiError(
            ErrorCode.PROTECTED, f"The built-in {described.name} network cannot be deleted."
        )
    if described.compose_managed:
        raise ApiError(
            ErrorCode.PROTECTED,
            "This network belongs to a compose project and cannot be deleted.",
        )
    return network


def _remove_network_sync(network) -> None:
    for container in network.attrs.get("Containers", {}).values():
        try:
            network.disconnect(container["Name"])
        except APIError:
            pass
    network.remove()


async def remove_network(network_id: str) -> None:
    network = require_mutable_network(network_id)
    try:
        await _in_thread(_remove_network_sync, network)
    except DockerException as exc:
        raise wrap_docker_error(exc, "delete the network") from exc


def _connect_sync(network, container, aliases: list[str] | None) -> None:
    kwargs = {}
    if aliases:
        kwargs["aliases"] = aliases
    try:
        network.connect(container, **kwargs)
    except APIError as exc:
        message = str(exc).lower()
        # Re-applying saved attachments after a redeploy is expected to hit
        # containers that are already attached.
        if "already" in message and "connect" in message:
            return
        raise


async def connect_container(
    network_id: str, container_id: str, aliases: list[str] | None = None
) -> None:
    network = resolve_network(network_id)
    container = resolve_container(container_id)
    try:
        await _in_thread(_connect_sync, network, container, aliases)
    except DockerException as exc:
        raise wrap_docker_error(exc, "connect the container") from exc


async def disconnect_container(network_id: str, container_id: str) -> None:
    network = resolve_network(network_id)
    container = resolve_container(container_id)
    try:
        await _in_thread(lambda: network.disconnect(container))
    except DockerException as exc:
        raise wrap_docker_error(exc, "disconnect the container") from exc


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #
async def stream_logs(
    container_id: str,
    *,
    tail: int | str = 200,
    since: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield log lines with their stream tagged, then follow live output.

    The SDK's ``follow`` stream merges stdout and stderr together, which loses
    the distinction the UI needs, so two followers are started with timestamps
    on and their lines pushed into one queue, each tagged at the source.

    A container started with a TTY reports everything as stdout; there is no
    separate stderr stream to read in that case.

    Yields a final ``{"type": "end"}`` once the container stops.
    """
    container = resolve_container(container_id)
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

    def make_follower(stream: str) -> None:
        def _pump() -> None:
            try:
                for raw in container.logs(
                    stdout=stream == "stdout",
                    stderr=stream == "stderr",
                    timestamps=True,
                    tail=tail,
                    since=since or None,
                    follow=True,
                ):
                    ts, _, msg = raw.rstrip("\n").partition(" ")
                    when = _parse_time(ts) or datetime.now(timezone.utc)
                    queue.put_nowait(
                        {
                            "type": "log",
                            "time": when.isoformat(),
                            "stream": stream,
                            "msg": msg,
                        }
                    )
            except (APIError, DockerException):
                pass
            finally:
                queue.put_nowait({"type": "eof", "stream": stream})

        asyncio.get_running_loop().run_in_executor(None, _pump)

    make_follower("stdout")
    make_follower("stderr")

    open_streams = 2
    while open_streams > 0:
        event = await queue.get()
        if event.get("type") == "eof":
            open_streams -= 1
            continue
        yield event

    yield {"type": "end"}


def _logs_sync(container_id: str, tail: int | str, since: str | None) -> str:
    container = resolve_container(container_id)
    out = container.logs(stdout=True, stderr=True, timestamps=False, tail=tail, since=since or None)
    if isinstance(out, bytes):
        return out.decode(errors="replace")
    return out


async def download_logs(
    container_id: str, *, tail: int | str = "all", since: str | None = None
) -> str:
    return await _in_thread(_logs_sync, container_id, tail, since)