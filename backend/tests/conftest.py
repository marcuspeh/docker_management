"""Shared fixtures.

Settings and the database engine are module-level singletons, so they are
redirected at import time before anything reads them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Point the app at throwaway locations before app modules are imported.
_TMP = Path(__file__).parent / ".tmp"
_TMP.mkdir(exist_ok=True)

import os  # noqa: E402

os.environ.setdefault("WORKSPACE_DIR", str(_TMP / "repos"))
os.environ.setdefault("DB_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("SCM_DIST_DIR", str(_TMP / "scm"))
os.environ.setdefault("CONTAINERS_DIST_DIR", str(_TMP / "containers"))


@pytest.fixture
def bare_repo(tmp_path: Path) -> Path:
    """A bare repo with one commit and a compose file, plus an extra branch."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"

    run(["git", "init", "--bare", "-b", "main", str(remote)])
    run(["git", "clone", str(remote), str(work)])
    (work / "docker-compose.yml").write_text("services: {}\n")
    run(["git", "-C", str(work), "add", "."])
    run(
        ["git", "-C", str(work), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "first commit"]
    )
    run(["git", "-C", str(work), "push", "origin", "main"])
    run(["git", "-C", str(work), "checkout", "-b", "develop"])
    run(["git", "-C", str(work), "push", "origin", "develop"])
    return remote


@pytest.fixture
def broken_repo(tmp_path: Path) -> Path:
    """A repo whose default branch has no compose file."""
    remote = tmp_path / "broken.git"
    work = tmp_path / "broken-work"
    run(["git", "init", "--bare", "-b", "main", str(remote)])
    run(["git", "clone", str(remote), str(work)])
    (work / "README.md").write_text("no compose here\n")
    run(["git", "-C", str(work), "add", "."])
    run(
        ["git", "-C", str(work), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "no compose"]
    )
    run(["git", "-C", str(work), "push", "origin", "main"])
    return remote


@pytest.fixture
def fake_docker(tmp_path: Path) -> Path:
    """A stub `docker` on PATH that records argv and honours FAKE_BUILD_FAIL."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "docker-calls.log"

    stub = bindir / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'for a in "$@"; do\n'
        '  if [ "$a" = "build" ]; then\n'
        '    echo "GIT_BRANCH=$GIT_BRANCH GIT_COMMIT=$GIT_COMMIT"\n'
        '    if [ -n "$FAKE_BUILD_FAIL" ]; then echo "build error" >&2; exit 1; fi\n'
        "  fi\n"
        "done\n"
        "exit 0\n"
    )
    stub.chmod(0o755)
    return bindir


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient over an isolated database and workspace."""
    from fastapi.testclient import TestClient
    from sqlmodel import SQLModel, create_engine

    from app import config
    from app import db as db_module
    from app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr("app.db.engine", engine)
    # The clone directory is derived from the repo slug, so a shared workspace
    # would let one test's clone satisfy another test's "first deploy".
    monkeypatch.setattr(config.settings, "workspace_dir", tmp_path / "repos")
    SQLModel.metadata.create_all(engine)

    with TestClient(app) as test_client:
        yield test_client


def run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, check=True, capture_output=True, text=True)


def docker_available() -> bool:
    try:
        import docker

        docker.DockerClient().ping()
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(
    not docker_available(), reason="requires a reachable Docker daemon"
)