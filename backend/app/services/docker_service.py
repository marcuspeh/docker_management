"""Docker access through the Python SDK.

The SDK covers containers, logs and networks. Compose build/up/down go through
the CLI instead, because they need streaming progress output.
"""

from __future__ import annotations

from typing import Any

import docker
from docker.errors import DockerException

from ..config import settings

_client: docker.DockerClient | None = None


def get_client() -> docker.DockerClient:
    """Shared SDK client bound to the host daemon via the mounted socket."""
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url=settings.docker_socket)
    return _client


async def ping_docker() -> dict[str, Any]:
    """Report daemon reachability for /api/health."""
    try:
        return await _in_thread(get_client().ping)
    except DockerException:
        return {"reachable": False, "serverVersion": None}


async def _in_thread(fn, *args, **kwargs):
    """Run a blocking SDK call off the event loop."""
    import asyncio
    import functools

    return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))