"""Git access and workspace path helpers.

Every command is passed as an argument list and never through a shell, and the
environment disables interactive prompts so a missing credential fails
immediately instead of hanging the request.
"""

from __future__ import annotations

import asyncio
import functools
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from ..errors import ApiError, ErrorCode

#: Refuse to let git block on credentials or a host key prompt.
GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
}

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
MAX_SLUG_LENGTH = 60


# --------------------------------------------------------------------------- #
# Naming and path safety
# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    """Derive a compose-safe slug from a display name.

    The slug doubles as the compose project name, so it is restricted to
    ``[a-z0-9-]``.
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:MAX_SLUG_LENGTH].strip("-")
    if not slug:
        raise ApiError(
            ErrorCode.INVALID_NAME,
            "Name must contain at least one letter or digit.",
            {"field": "name"},
        )
    return slug


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ApiError(
            ErrorCode.INVALID_NAME,
            "Name may only contain lowercase letters, digits and hyphens.",
            {"field": "name"},
        )
    return slug


def normalize_path(path: str | None) -> str:
    """Normalize a repo-relative directory, where ``/`` means the repo root."""
    if path is None or not path.strip() or path.strip() == "/":
        return "/"

    cleaned = path.strip().strip("/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ApiError(
            ErrorCode.INVALID_PATH,
            "Path must stay inside the repository.",
            {"field": "path"},
        )
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def validate_compose_file(compose_file: str | None) -> str:
    name = (compose_file or "docker-compose.yml").strip()
    if not name or "/" in name or name in (".", ".."):
        raise ApiError(
            ErrorCode.INVALID_PATH,
            "Compose file must be a file name inside the repo path.",
            {"field": "composeFile"},
        )
    return name


def clone_dir(slug: str) -> Path:
    return settings.workspace_dir / validate_slug(slug)


def compose_dir(slug: str, path: str) -> Path:
    """Absolute directory holding the compose file.

    Guards against a normalized path escaping the clone.
    """
    base = clone_dir(slug)
    target = (base / normalize_path(path).lstrip("/")).resolve()
    root = base.resolve()
    if root != target and root not in target.parents:
        raise ApiError(
            ErrorCode.INVALID_PATH,
            "Path must stay inside the repository.",
            {"field": "path"},
        )
    return target


def compose_file_path(slug: str, path: str, compose_file: str) -> Path:
    return compose_dir(slug, path) / validate_compose_file(compose_file)


def is_cloned(slug: str) -> bool:
    return (clone_dir(slug) / ".git").exists()


def is_usable_clone(slug: str) -> bool:
    """True when the clone is complete enough to fetch into.

    ``is_cloned`` only sees a ``.git`` directory, which a clone interrupted by a
    cancel or a restart can leave behind half-written. ``rev-parse`` succeeding
    means git itself considers the repository usable.
    """
    clone = clone_dir(slug)
    if not (clone / ".git").exists():
        return False
    result = run_git(["rev-parse", "--git-dir"], cwd=clone, timeout=10)
    return result.ok


# --------------------------------------------------------------------------- #
# Command execution
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    remote: bool = True,
) -> GitResult:
    """Run git synchronously. Callers wrap this in ``asyncio.to_thread``.

    ``remote`` says whether the command contacts the remote. A timeout on a
    local-only command (rev-parse, log, checkout) is not an unreachable repo,
    so it gets GIT_ERROR rather than REPO_UNREACHABLE.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            env=GIT_ENV,
            capture_output=True,
            text=True,
            timeout=timeout or settings.git_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        code = ErrorCode.REPO_UNREACHABLE if remote else ErrorCode.GIT_ERROR
        message = (
            "Git timed out while contacting the remote."
            if remote
            else "Git timed out on a local command."
        )
        raise ApiError(code, message, {"stderr": str(exc)}) from exc
    except FileNotFoundError as exc:  # pragma: no cover - git always present in image
        raise ApiError(
            ErrorCode.GIT_ERROR, "git executable not found on the server."
        ) from exc
    return GitResult(proc.returncode, proc.stdout, proc.stderr)


async def git(
    *args: str, cwd: Path | None = None, timeout: float | None = None, remote: bool = True
) -> GitResult:
    return await asyncio.to_thread(
        functools.partial(run_git, list(args), cwd=cwd, timeout=timeout, remote=remote)
    )


def _raise_git_error(result: GitResult, action: str, url: str | None = None) -> None:
    detail: dict[str, str] = {"stderr": result.stderr.strip()[-4000:]}
    if url:
        detail["url"] = url
    raise ApiError(
        ErrorCode.GIT_ERROR, f"Git failed to {action}.", detail
    )


# --------------------------------------------------------------------------- #
# Remote inspection
# --------------------------------------------------------------------------- #
def parse_ls_remote(output: str) -> tuple[str | None, dict[str, str]]:
    """Parse ``git ls-remote --symref`` into (default branch, {branch: sha})."""
    default_branch: str | None = None
    branches: dict[str, str] = {}

    for line in output.splitlines():
        if line.startswith("ref:"):
            # "ref: refs/heads/main\tHEAD"
            ref, _, target = line.partition("\t")
            if target.strip() == "HEAD":
                ref = ref.removeprefix("ref:").strip()
                default_branch = ref.removeprefix("refs/heads/")
            continue
        sha, _, ref = line.partition("\t")
        ref = ref.strip()
        if ref.startswith("refs/heads/"):
            branches[ref.removeprefix("refs/heads/")] = sha.strip()

    return default_branch, branches


async def ls_remote(url: str) -> tuple[str | None, dict[str, str]]:
    """Check access and discover the default branch without cloning."""
    result = await git("ls-remote", "--symref", url)
    if not result.ok:
        raise ApiError(
            ErrorCode.REPO_UNREACHABLE,
            "Could not reach the repository. Check the URL and your Git credentials.",
            {"stderr": result.stderr.strip()[-4000:]},
        )
    return parse_ls_remote(result.stdout)


async def list_branches(url: str) -> list[dict[str, str]]:
    """Branches and their head sha, readable before the first clone."""
    _, branches = await ls_remote(url)
    return [
        {"name": name, "commit": sha}
        for name, sha in sorted(branches.items())
    ]


# --------------------------------------------------------------------------- #
# Local clone operations
# --------------------------------------------------------------------------- #
async def clone(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = await git("clone", url, str(dest))
    if not result.ok:
        _raise_git_error(result, "clone the repository", url)


async def fetch(dest: Path) -> None:
    result = await git("fetch", "--prune", "origin", cwd=dest)
    if not result.ok:
        _raise_git_error(result, "fetch from origin")


async def checkout_branch(dest: Path, branch: str) -> None:
    result = await git("checkout", "-f", "-B", branch, f"origin/{branch}", cwd=dest)
    if not result.ok:
        _raise_git_error(result, f"check out branch {branch}")


async def checkout_commit(dest: Path, sha: str) -> None:
    result = await git("checkout", "-f", "--detach", sha, cwd=dest)
    if not result.ok:
        _raise_git_error(result, f"check out commit {sha}")


async def rev_parse(dest: Path, ref: str = "HEAD") -> str:
    result = await git("rev-parse", ref, cwd=dest, remote=False)
    if not result.ok:
        _raise_git_error(result, f"resolve {ref}")
    return result.stdout.strip()


async def commit_subject(dest: Path, ref: str = "HEAD") -> str | None:
    result = await git("log", "-1", "--format=%s", ref, cwd=dest, remote=False)
    return result.stdout.strip() if result.ok else None


async def log_commits(dest: Path, branch: str, limit: int = 20) -> list[dict]:
    """Recent commits on a branch, newest first."""
    result = await git(
        "log",
        f"-{limit}",
        "--format=%H%x1f%s%x1f%an%x1f%cI",
        "origin/" + branch,
        cwd=dest,
        remote=False,
    )
    if not result.ok:
        raise ApiError(
            ErrorCode.GIT_ERROR,
            f"Could not read commit history for {branch}.",
            {"stderr": result.stderr.strip()[-4000:]},
        )

    commits: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, subject, author, committed_at = parts
        try:
            when = datetime.fromisoformat(committed_at).astimezone(timezone.utc)
        except ValueError:
            when = datetime.now(timezone.utc)
        commits.append(
            {"sha": sha, "subject": subject, "author": author, "committed_at": when}
        )
    return commits