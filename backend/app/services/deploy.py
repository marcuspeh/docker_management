"""The deploy pipeline.

Clone or fetch, check out the requested ref, build, then bring the stack up and
re-apply saved network attachments. The ordering is load-bearing: a failed build
must leave the running containers untouched, so ``up`` is the only step that
mutates them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlmodel import Session, select

from ..db import session_scope
from ..errors import ApiError, ErrorCode
from ..models import Deployment, NetworkAttachment, Repo, utcnow
from . import compose_service, docker_service, git_service, jobs

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RepoSnapshot:
    """The repo fields the pipeline needs, read once at the start."""

    id: str
    url: str
    slug: str
    path: str
    compose_file: str


def snapshot(repo: Repo) -> RepoSnapshot:
    return RepoSnapshot(
        id=repo.id,
        url=repo.url,
        slug=repo.slug,
        path=repo.path,
        compose_file=repo.compose_file,
    )


class StepFailed(Exception):
    """A pipeline step failed; the message goes in the log and the status."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step
        self.message = message


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
async def _git(job: jobs.DeploymentJob, argv: list[str], cwd=None) -> int:
    return await jobs.run_streaming(job, ["git", *argv], cwd=cwd, env=git_service.GIT_ENV)


async def step_source(job: jobs.DeploymentJob, repo: RepoSnapshot) -> None:
    """Clone on the first deploy, otherwise fetch."""
    clone = git_service.clone_dir(repo.slug)

    if not git_service.is_cloned(repo.slug):
        job.log.step("clone", "started")
        clone.parent.mkdir(parents=True, exist_ok=True)
        rc = await _git(job, ["clone", repo.url, str(clone)])
        if rc != 0:
            job.log.step("clone", "failed")
            raise StepFailed("clone", "Could not clone the repository.")
        job.log.step("clone", "succeeded")
        return

    job.log.step("fetch", "started")
    rc = await _git(job, ["fetch", "--prune", "origin"], cwd=clone)
    if rc != 0:
        job.log.step("fetch", "failed")
        raise StepFailed("fetch", "Could not fetch from origin.")
    job.log.step("fetch", "succeeded")


async def step_checkout(
    job: jobs.DeploymentJob, repo: RepoSnapshot, branch: str, commit: str | None
) -> tuple[str, str | None]:
    """Check out the branch or an explicit commit. Returns (sha, subject)."""
    job.log.step("checkout", "started")
    clone = git_service.clone_dir(repo.slug)

    if commit:
        rc = await _git(job, ["checkout", "-f", "--detach", commit], cwd=clone)
        target = commit
    else:
        rc = await _git(job, ["checkout", "-f", "-B", branch, f"origin/{branch}"], cwd=clone)
        target = branch

    if rc != 0:
        job.log.step("checkout", "failed")
        raise StepFailed("checkout", f"Could not check out {target}.")

    # Report a missing compose file here rather than as a confusing compose
    # failure several steps later.
    compose_path = git_service.compose_file_path(
        repo.slug, repo.path, repo.compose_file
    )
    if not compose_path.exists():
        job.log.step("checkout", "failed")
        location = f"{repo.path.rstrip('/')}/{repo.compose_file}"
        raise StepFailed(
            "checkout", f"No compose file at {location} on {target}."
        )

    job.log.step("checkout", "succeeded")
    return (
        await git_service.rev_parse(clone),
        await git_service.commit_subject(clone),
    )


def _git_env(branch: str, commit: str | None) -> dict[str, str]:
    """Expose the deployed ref to the user's compose file."""
    return {"GIT_BRANCH": branch, "GIT_COMMIT": commit or ""}


async def step_build(
    job: jobs.DeploymentJob, repo: RepoSnapshot, branch: str, commit: str | None
) -> None:
    job.log.step("build", "started")
    argv = compose_service.compose_argv(
        repo.slug, repo.path, repo.compose_file, "build", "--progress", "plain"
    )
    rc = await jobs.run_streaming(
        job, argv, env=compose_service.compose_env(_git_env(branch, commit))
    )
    if rc != 0:
        job.log.step("build", "failed")
        raise StepFailed("build", "Build failed. Running containers are unchanged.")
    job.log.step("build", "succeeded")


async def step_up(
    job: jobs.DeploymentJob, repo: RepoSnapshot, branch: str, commit: str | None
) -> None:
    # Cancelling before this point leaves the previous containers running.
    if job.cancelled:
        raise StepFailed("up", "Cancelled before the stack was updated.")

    job.log.step("up", "started")
    argv = compose_service.compose_argv(
        repo.slug, repo.path, repo.compose_file, "up", "-d", "--remove-orphans"
    )
    rc = await jobs.run_streaming(
        job, argv, env=compose_service.compose_env(_git_env(branch, commit))
    )
    if rc != 0:
        job.log.step("up", "failed")
        raise StepFailed("up", "docker compose up failed.")
    job.log.step("up", "succeeded")


async def step_networks(job: jobs.DeploymentJob, repo: RepoSnapshot) -> None:
    """Restore manual network attachments, which compose recreations drop."""
    job.log.step("networks", "started")
    with session_scope() as session:
        await apply_saved_attachments(session, repo, job)
    job.log.step("networks", "succeeded")


async def apply_saved_attachments(
    session: Session, repo: RepoSnapshot | Repo, job: jobs.DeploymentJob | None = None
) -> None:
    """Re-connect deployed services to networks after every up.

    "Already connected" is expected here and ignored.
    """
    repo_id = repo.id
    slug = repo.slug
    attachments = session.exec(
        select(NetworkAttachment).where(NetworkAttachment.repo_id == repo_id)
    ).all()
    if not attachments:
        return

    containers = await docker_service.list_project_containers(slug)
    by_service = {c.service: c for c in containers if c.service}

    for attachment in attachments:
        container = by_service.get(attachment.service)
        if container is None:
            if job:
                job.log.append(
                    f"  skipped {attachment.network}: no container for "
                    f"service {attachment.service}"
                )
            continue
        try:
            await docker_service.connect_container(
                attachment.network, container.full_id, _aliases(attachment)
            )
            if job:
                job.log.append(
                    f"  reattached {attachment.service} to {attachment.network}"
                )
        except ApiError as exc:
            if job:
                job.log.append(
                    f"  could not reattach {attachment.service} to "
                    f"{attachment.network}: {exc.message}"
                )


def _aliases(attachment: NetworkAttachment) -> list[str] | None:
    try:
        parsed = json.loads(attachment.aliases or "[]")
    except json.JSONDecodeError:
        return None
    return parsed or None


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
async def run_pipeline(
    deployment_id: str, repo_id: str, branch: str, commit: str | None
) -> None:
    """Run the pipeline to completion, persisting status as it goes.

    Always settles the deployment, so a stream never hangs waiting for ``done``.
    """
    job = jobs.get_job(deployment_id) or jobs.new_job(deployment_id, repo_id)

    with session_scope() as session:
        deployment = session.get(Deployment, deployment_id)
        repo = session.get(Repo, repo_id)
        if deployment is None or repo is None:
            job.finished.set()
            jobs.release_job(deployment_id)
            return
        deployment.status = "running"
        repo = snapshot(repo)

    commit_sha: str | None = None
    commit_message: str | None = None

    try:
        await step_source(job, repo)
        commit_sha, commit_message = await step_checkout(job, repo, branch, commit)
        await step_build(job, repo, branch, commit)
        await step_up(job, repo, branch, commit)
        await step_networks(job, repo)
        result = ("success", commit_sha, commit_message, None)

    except StepFailed as exc:
        job.log.append(f"! {exc.message}")
        result = (
            "cancelled" if job.cancelled else "failed",
            commit_sha,
            commit_message,
            exc.message,
        )
    except Exception as exc:
        logger.exception("Deployment %s failed unexpectedly", deployment_id)
        job.log.append(f"! {exc}")
        result = ("failed", commit_sha, commit_message, str(exc))

    _settle(deployment_id, job, *result)


def _settle(
    deployment_id: str,
    job: jobs.DeploymentJob,
    status: str,
    commit_sha: str | None,
    commit_message: str | None,
    error: str | None,
) -> None:
    """Publish the terminal event, persist state and the replayable log."""
    job.log.finish(
        {
            "status": status,
            "commitSha": commit_sha,
            "commitMessage": commit_message,
            "error": error,
        }
    )

    with session_scope() as session:
        deployment = session.get(Deployment, deployment_id)
        if deployment is not None:
            deployment.status = status
            deployment.commit_sha = commit_sha
            deployment.commit_message = commit_message
            deployment.error = error
            deployment.log = job.log.snapshot()
            deployment.finished_at = utcnow()

    job.finished.set()
    jobs.release_job(deployment_id)


# --------------------------------------------------------------------------- #
# Stack actions
# --------------------------------------------------------------------------- #
async def stack_action(repo: Repo, action: str) -> list:
    """Run a compose stack action and return the project's containers."""
    if action == "up":
        code, output = await compose_service.up(repo.slug, repo.path, repo.compose_file)
        if code != 0:
            raise ApiError(
                ErrorCode.DOCKER_ERROR,
                "docker compose up failed.",
                {"stderr": output[-4000:]},
            )
        # A plain up can also drop manual attachments, so restore them.
        with session_scope() as session:
            await apply_saved_attachments(session, repo)
    elif action == "stop":
        code, output = await compose_service.stop(
            repo.slug, repo.path, repo.compose_file
        )
    elif action == "restart":
        code, output = await compose_service.restart(
            repo.slug, repo.path, repo.compose_file
        )
    elif action == "down":
        code, output = await compose_service.down(
            repo.slug, repo.path, repo.compose_file
        )
    else:
        raise ApiError(ErrorCode.NOT_FOUND, f"Unknown stack action: {action}")

    if code != 0 and action != "up":
        raise ApiError(
            ErrorCode.DOCKER_ERROR,
            f"docker compose {action} failed.",
            {"stderr": output[-4000:]},
        )

    return await docker_service.list_project_containers(repo.slug)