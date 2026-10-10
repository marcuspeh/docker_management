"""Runtime settings for the portal backend.

Every value has a default that works for local development; the container
deployment overrides the workspace and database locations via the environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Where repository clones live. Mounted at the same path inside and outside
    # the container so relative bind mounts in a user's compose file resolve on
    # the host.
    workspace_dir: Path = Path("/srv/portal/repos")

    db_url: str = "sqlite:////srv/portal/portal.db"

    # Left empty by default: the apps are served from the same origin as the API.
    # Set explicitly (comma separated) only when an app is hosted elsewhere.
    cors_origins: list[str] = []

    # Production builds of the two web apps.
    scm_dist_dir: Path = Path("/app/web/scm")
    containers_dist_dir: Path = Path("/app/web/containers")

    # git ls-remote is given a hard timeout so an unreachable or
    # credential-prompting remote fails fast instead of hanging the request.
    git_timeout_seconds: float = 20.0

    # Upper bound on a single compose build/up invocation.
    compose_timeout_seconds: float = 3600.0

    # Number of log lines kept in memory per running deployment.
    log_buffer_lines: int = 10_000

    # Docker socket used to reach the host daemon.
    docker_socket: str = "unix:///var/run/docker.sock"

    # Label marking the portal's own container so it can be excluded and refused.
    self_label: str = "portal.self"

    @property
    def database_path(self) -> Path | None:
        """Filesystem path for the SQLite database, when the URL is file-based."""
        prefix = "sqlite:///"
        if self.db_url.startswith(prefix):
            raw = self.db_url[len(prefix) :]
            # sqlite:///relative.db and sqlite:////absolute.db both appear here.
            return Path(raw)
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()