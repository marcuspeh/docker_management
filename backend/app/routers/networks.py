"""Network listing, creation, deletion and container attachments."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..errors import ApiError, ErrorCode
from ..models import NetworkAttachment, Repo
from ..schemas import (
    ConnectFailure,
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    NetworkCreate,
    NetworkOut,
)
from ..services import docker_service

router = APIRouter(tags=["networks"])


def _identify(container) -> tuple[str | None, str | None]:
    """(repo_id, service) for a container deployed by the portal, else (None, None)."""
    labels = (container.attrs.get("Config") or {}).get("Labels") or {}
    project = labels.get(docker_service.COMPOSE_PROJECT_LABEL)
    service = labels.get(docker_service.COMPOSE_SERVICE_LABEL)
    return (project, service) if project and service else (None, None)


def _slug_map(session: Session) -> dict[str, str]:
    return {repo.slug: repo.id for repo in session.exec(select(Repo)).all()}


def _save_attachment(
    session: Session,
    slug_to_repo: dict[str, str],
    network_name: str,
    container,
    aliases: list[str] | None,
) -> None:
    """Remember a link so it can be restored after a redeploy recreates it.

    Only meaningful for containers the portal deployed; anything else is left
    alone.
    """
    project, service = _identify(container)
    if not project or not service:
        return
    repo_id = slug_to_repo.get(project)
    if not repo_id:
        return

    existing = session.exec(
        select(NetworkAttachment).where(
            NetworkAttachment.repo_id == repo_id,
            NetworkAttachment.service == service,
            NetworkAttachment.network == network_name,
        )
    ).first()
    if existing is not None:
        return

    session.add(
        NetworkAttachment(
            id=str(uuid.uuid4()),
            repo_id=repo_id,
            service=service,
            network=network_name,
            aliases=json.dumps(aliases or []),
        )
    )


def _delete_attachments(session: Session, network_refs: set[str]) -> None:
    """Drop saved attachments for a network, referenced by name or id."""
    for attachment in session.exec(select(NetworkAttachment)).all():
        if attachment.network in network_refs:
            session.delete(attachment)


@router.get("", response_model=list[NetworkOut])
async def list_networks() -> list[NetworkOut]:
    return await docker_service.list_networks()


@router.post("", response_model=NetworkOut, status_code=201)
async def create_network(payload: NetworkCreate) -> NetworkOut:
    name = payload.name.strip()
    if not name:
        raise ApiError(
            ErrorCode.INVALID_NAME, "Network name is required.", {"field": "name"}
        )
    return await docker_service.create_network(
        name, driver=payload.driver, internal=payload.internal
    )


@router.delete("/{network_id}", status_code=204)
async def delete_network(
    network_id: str, session: Session = Depends(get_session)
) -> None:
    network = docker_service.require_mutable_network(network_id)

    # Refuses built-in and compose-owned networks, disconnects what is
    # attached, then removes the network.
    await docker_service.remove_network(network.attrs.get("Id") or network_id)

    # Attachments are stored by name, so match both spellings.
    _delete_attachments(session, {network.attrs.get("Name") or "", network_id})
    session.commit()


@router.post("/{network_id}/connect", response_model=ConnectResponse)
async def connect(
    network_id: str,
    payload: ConnectRequest,
    session: Session = Depends(get_session),
) -> ConnectResponse:
    network = docker_service.resolve_network(network_id)
    real_id = network.attrs.get("Id") or network_id
    network_name = network.attrs.get("Name") or network_id
    slug_to_repo = _slug_map(session)

    connected: list[str] = []
    failed: list[ConnectFailure] = []

    for container_id in payload.container_ids:
        try:
            await docker_service.connect_container(
                real_id, container_id, payload.aliases
            )
            connected.append(container_id)

            try:
                container = docker_service.resolve_container(container_id)
            except ApiError:
                container = None
            if container is not None:
                _save_attachment(
                    session, slug_to_repo, network_name, container, payload.aliases
                )
        except ApiError as exc:
            failed.append(ConnectFailure(container_id=container_id, error=exc.message))

    session.commit()
    return ConnectResponse(connected=connected, failed=failed)


@router.post("/{network_id}/disconnect", response_model=ConnectResponse)
async def disconnect(
    network_id: str,
    payload: DisconnectRequest,
    session: Session = Depends(get_session),
) -> ConnectResponse:
    network = docker_service.resolve_network(network_id)
    real_id = network.attrs.get("Id") or network_id
    network_name = network.attrs.get("Name") or network_id

    disconnected: list[str] = []
    failed: list[ConnectFailure] = []

    for container_id in payload.container_ids:
        try:
            await docker_service.disconnect_container(real_id, container_id)
            disconnected.append(container_id)
        except ApiError as exc:
            failed.append(ConnectFailure(container_id=container_id, error=exc.message))

    # A manual disconnect must not be undone by the next deploy.
    for attachment in session.exec(
        select(NetworkAttachment).where(
            NetworkAttachment.network.in_([network_name, network_id])
        )
    ).all():
        session.delete(attachment)

    session.commit()
    return ConnectResponse(connected=disconnected, failed=failed)