from __future__ import annotations

import asyncio
import subprocess

from fastapi import APIRouter

from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


def _git_version() -> dict[str, str | None]:
    try:
        out = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return {"version": out.stdout.strip() or None}
    except Exception:
        return {"version": None}


async def _docker_version() -> dict[str, object]:
    from ..services.docker_service import ping_docker

    return await ping_docker()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # Docker is required for the portal to function; Git without a version is
    # only a partial problem. Either failing degrades the status.
    docker, git = await asyncio.gather(_docker_version(), asyncio.to_thread(_git_version))

    healthy = bool(docker.get("reachable")) and bool(git.get("version"))
    return HealthResponse(
        status="ok" if healthy else "degraded",
        docker=docker,
        git=git,
    )