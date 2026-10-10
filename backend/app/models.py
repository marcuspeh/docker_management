"""SQLModel tables.

Containers and networks are deliberately *not* stored: they are read live from
the Docker daemon. Containers deployed by the portal are linked back to a repo
through compose labels (``com.docker.compose.project`` -> repo slug and
``com.docker.compose.service`` -> service name).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


#: Statuses meaning "a runner owns this deployment". Anything still in one of
#: these at startup was orphaned by a restart.
RUNNING_STATUSES = ("queued", "running")

#: Statuses meaning the deployment has reached a final state.
FINISHED_STATUSES = ("success", "failed", "cancelled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Repo(SQLModel, table=True):
    __tablename__ = "repo"

    id: str = Field(primary_key=True)
    name: str
    # Unique, also used as the compose project name.
    slug: str = Field(index=True, unique=True)
    url: str
    # Path to the directory holding the compose file, relative to the repo root.
    # "/" means the root.
    path: str = "/"
    compose_file: str = "docker-compose.yml"
    default_branch: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Deployment(SQLModel, table=True):
    __tablename__ = "deployment"

    id: str = Field(primary_key=True)
    repo_id: str = Field(foreign_key="repo.id", index=True)
    branch: str
    requested_commit: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None
    status: str = "queued"
    step: str | None = None
    error: str | None = None
    # Log lines with their sequence numbers, stored as JSON once the deploy ends.
    log: str = Field(default="[]", sa_column=Column(Text, nullable=False, default="[]"))
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class NetworkAttachment(SQLModel, table=True):
    """A container-to-network link restored after every deploy of a repo."""

    __tablename__ = "networkattachment"

    id: str = Field(primary_key=True)
    repo_id: str = Field(foreign_key="repo.id", index=True)
    service: str
    network: str
    aliases: str = Field(default="[]", sa_column=Column(Text, nullable=False, default="[]"))