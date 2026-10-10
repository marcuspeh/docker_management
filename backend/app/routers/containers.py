"""Container listing, lifecycle actions and log streaming."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import Repo
from ..schemas import ContainerOut, StopRequest
from ..services import docker_service

router = APIRouter(tags=["containers"])


def slug_map(session: Session) -> dict[str, str]:
    """Compose project slug -> repo id.

    ``com.docker.compose.project`` is the only link between a stored repo and a
    live container, so listings resolve repoId through it.
    """
    return {repo.slug: repo.id for repo in session.exec(select(Repo)).all()}


@router.get("", response_model=list[ContainerOut])
async def list_containers(
    all: bool = Query(False, description="Include stopped containers."),
    network: str | None = Query(None),
    repoId: str | None = Query(None),
    q: str | None = Query(None, description="Match name, id or image."),
    session: Session = Depends(get_session),
) -> list[ContainerOut]:
    # The portal's own container is always excluded by the service layer.
    return await docker_service.list_containers(
        all_=all,
        network=network,
        repo_id=repoId,
        query=q,
        slug_to_repo=slug_map(session),
    )


@router.post("/{container_id}/stop", response_model=ContainerOut)
async def stop_container(
    container_id: str,
    payload: StopRequest | None = None,
) -> ContainerOut:
    timeout = payload.timeout if payload else 10
    return await docker_service.container_action(container_id, "stop", timeout)


@router.post("/{container_id}/start", response_model=ContainerOut)
async def start_container(container_id: str) -> ContainerOut:
    return await docker_service.container_action(container_id, "start")


@router.post("/{container_id}/restart", response_model=ContainerOut)
async def restart_container(container_id: str) -> ContainerOut:
    return await docker_service.container_action(container_id, "restart")


@router.get("/{container_id}/logs")
async def stream_container_logs(
    container_id: str,
    tail: int | str = Query(200),
    since: str | None = Query(None),
) -> EventSourceResponse:
    async def event_source():
        async for event in docker_service.stream_logs(
            container_id, tail=tail, since=since
        ):
            if event.get("type") == "log":
                yield {
                    "event": "log",
                    "data": json.dumps(
                        {
                            "time": event["time"],
                            "stream": event["stream"],
                            "msg": event["msg"],
                        }
                    ),
                }
            else:
                yield {"event": "end", "data": "{}"}

    return EventSourceResponse(event_source(), ping=15)


@router.get("/{container_id}/logs/download", response_class=PlainTextResponse)
async def download_container_logs(
    container_id: str,
    tail: int | str = Query("all"),
    since: str | None = Query(None),
) -> PlainTextResponse:
    text = await docker_service.download_logs(container_id, tail=tail, since=since)
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{container_id}-logs.txt"'
        },
    )