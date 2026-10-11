"""Docker Compose command construction and execution.

Compose runs through the CLI rather than the SDK because builds and ups need
streaming progress output. Commands are always argument lists.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..config import settings
from ..errors import ApiError, ErrorCode
from . import git_service as git_svc


def compose_argv(
    slug: str, path: str, compose_file: str, *args: str
) -> list[str]:
    """Build a compose argv.

    The project directory is the directory holding the compose file, which is
    what makes relative bind mounts inside the file resolve correctly.
    """
    directory = git_svc.compose_dir(slug, path)
    file_path = directory / git_svc.validate_compose_file(compose_file)
    return [
        "docker",
        "compose",
        "-p",
        slug,
        "-f",
        str(file_path),
        "--project-directory",
        str(directory),
        *args,
    ]


def compose_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env


async def stream_command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[int, str]:
    """Run a compose command, discarding output.

    Streaming variants live in jobs.py; this is for fire-and-check calls like
    up/stop/restart where output is not shown.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        env=env or compose_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout or settings.compose_timeout_seconds
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise ApiError(
            ErrorCode.DOCKER_ERROR, "Compose command timed out."
        ) from None
    return proc.returncode or 0, (stdout or b"").decode(errors="replace") + (
        stderr or b""
    ).decode(errors="replace")


async def run_simple(
    slug: str, path: str, compose_file: str, *args: str, env_extra: dict[str, str] | None = None
) -> tuple[int, str]:
    argv = compose_argv(slug, path, compose_file, *args)
    return await stream_command(argv, env=compose_env(env_extra))


async def up(slug: str, path: str, compose_file: str, *, extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    return await run_simple(
        slug, path, compose_file, "up", "-d", "--remove-orphans", env_extra=extra_env
    )


async def stop(slug: str, path: str, compose_file: str) -> tuple[int, str]:
    return await run_simple(slug, path, compose_file, "stop")


async def restart(slug: str, path: str, compose_file: str) -> tuple[int, str]:
    return await run_simple(slug, path, compose_file, "restart")


async def down(slug: str, path: str, compose_file: str) -> tuple[int, str]:
    return await run_simple(slug, path, compose_file, "down", "--remove-orphans")