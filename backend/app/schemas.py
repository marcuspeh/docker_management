"""Request and response models.

The API speaks camelCase on the wire; Python attributes stay snake_case. Every
model sets ``populate_by_name`` so responses serialise by alias while tests and
internal code can construct them with field names.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #
DeployStep = Literal["clone", "fetch", "checkout", "build", "up", "networks"]
DeployStatus = Literal["queued", "running", "success", "failed", "cancelled"]


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    docker: dict[str, Any]
    git: dict[str, Any]


# --------------------------------------------------------------------------- #
# Deployment
# --------------------------------------------------------------------------- #
class DeploymentOut(ApiModel):
    id: str
    repo_id: str
    branch: str
    commit_sha: str | None = None
    commit_message: str | None = None
    status: DeployStatus
    step: DeployStep | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class DeploymentDetail(DeploymentOut):
    containers: list["ContainerOut"] = []


class RepoOut(ApiModel):
    id: str
    name: str
    url: str
    path: str
    compose_file: str
    default_branch: str | None = None
    cloned: bool
    last_deployment: DeploymentOut | None = None
    created_at: datetime


class BranchOut(ApiModel):
    name: str
    commit: str


class BranchesResponse(ApiModel):
    default_branch: str | None = None
    branches: list[BranchOut]


class CommitOut(ApiModel):
    sha: str
    subject: str
    author: str
    committed_at: datetime


class RepoCreate(ApiModel):
    name: str
    url: str
    path: str = "/"
    compose_file: str = "docker-compose.yml"


class RepoPatch(ApiModel):
    name: str | None = None
    path: str | None = None
    compose_file: str | None = None


class DeployRequest(ApiModel):
    branch: str
    commit: str | None = None


class StackActionResponse(ApiModel):
    containers: list["ContainerOut"] = []


# --------------------------------------------------------------------------- #
# Containers
# --------------------------------------------------------------------------- #
ContainerState = Literal[
    "running", "exited", "paused", "restarting", "created", "dead"
]


class PortOut(ApiModel):
    container_port: int
    host_port: int | None = None
    host_ip: str | None = None
    protocol: Literal["tcp", "udp"]


class ContainerOut(ApiModel):
    id: str
    full_id: str
    name: str
    image: str
    state: ContainerState
    status: str
    exit_code: int | None = None
    ports: list[PortOut] = []
    networks: list[str] = []
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    repo_id: str | None = None
    service: str | None = None


class StopRequest(ApiModel):
    timeout: int = 10


class LogLineOut(ApiModel):
    time: datetime
    stream: Literal["stdout", "stderr"]
    msg: str


# --------------------------------------------------------------------------- #
# Networks
# --------------------------------------------------------------------------- #
class NetworkOut(ApiModel):
    id: str
    name: str
    driver: str
    scope: Literal["local", "swarm", "global"]
    subnet: str | None = None
    internal: bool
    builtin: bool
    compose_managed: bool
    container_count: int


class NetworkCreate(ApiModel):
    name: str
    driver: str = "bridge"
    internal: bool = False


class ConnectRequest(ApiModel):
    container_ids: list[str]
    aliases: list[str] | None = None


class DisconnectRequest(ApiModel):
    container_ids: list[str]


class ConnectFailure(ApiModel):
    container_id: str
    error: str


class ConnectResponse(ApiModel):
    connected: list[str] = []
    failed: list[ConnectFailure] = []


# Resolve the forward reference used by DeploymentDetail.
DeploymentDetail.model_rebuild()
RepoOut.model_rebuild()
StackActionResponse.model_rebuild()