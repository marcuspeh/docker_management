"""Deployment endpoints: repositories, branches, deployments and stack actions."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select

from ..db import get_session
from ..errors import ApiError, ErrorCode
from ..models import Deployment, Repo
from ..schemas import (
    BranchesResponse,
    BranchOut,
    CommitOut,
    ContainerOut,
    DeployRequest,
    DeploymentDetail,
    DeploymentOut,
    RepoCreate,
    RepoOut,
    RepoPatch,
    StackActionResponse,
)
from ..services import git_service as git_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deployment"])


def get_repo_or_404(repo_id: str, session: Session) -> Repo:
    repo = session.get(Repo, repo_id)
    if repo is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Repository not found.")
    return repo


def last_deployment(session: Session, repo_id: str) -> Deployment | None:
    return session.exec(
        select(Deployment)
        .where(Deployment.repo_id == repo_id)
        .order_by(Deployment.started_at.desc())
        .limit(1)
    ).first()


def to_repo_out(repo: Repo, session: Session) -> RepoOut:
    return RepoOut(
        id=repo.id,
        name=repo.name,
        url=repo.url,
        path=repo.path,
        compose_file=repo.compose_file,
        default_branch=repo.default_branch,
        cloned=git_svc.is_cloned(repo.slug),
        last_deployment=last_deployment(session, repo.id),
        created_at=repo.created_at,
    )


def unique_slug(session: Session, base: str) -> str:
    """Append a counter when the desired slug is already taken."""
    slug = base
    suffix = 2
    while session.exec(select(Repo).where(Repo.slug == slug)).first() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@router.get("/repos", response_model=list[RepoOut])
def list_repos(session: Session = Depends(get_session)) -> list[RepoOut]:
    repos = session.exec(select(Repo).order_by(Repo.name)).all()
    return [to_repo_out(repo, session) for repo in repos]


@router.post("/repos", response_model=RepoOut, status_code=201)
async def create_repo(
    payload: RepoCreate, session: Session = Depends(get_session)
) -> RepoOut:
    name = payload.name.strip()
    if not name:
        raise ApiError(
            ErrorCode.INVALID_NAME, "Name is required.", {"field": "name"}
        )
    url = payload.url.strip()
    if not url:
        raise ApiError(ErrorCode.INVALID_NAME, "URL is required.", {"field": "url"})

    path = git_svc.normalize_path(payload.path)
    compose_file = git_svc.validate_compose_file(payload.compose_file)

    # Reach the remote now so an unreachable repo is rejected up front; nothing
    # is cloned until the first deploy.
    default_branch, _branches = await git_svc.ls_remote(url)

    repo = Repo(
        id=str(uuid.uuid4()),
        name=name,
        slug=unique_slug(session, git_svc.slugify(name)),
        url=url,
        path=path,
        compose_file=compose_file,
        default_branch=default_branch,
    )
    session.add(repo)
    session.commit()
    session.refresh(repo)
    return to_repo_out(repo, session)


@router.get("/repos/{repo_id}", response_model=RepoOut)
def get_repo(repo_id: str, session: Session = Depends(get_session)) -> RepoOut:
    return to_repo_out(get_repo_or_404(repo_id, session), session)


@router.patch("/repos/{repo_id}", response_model=RepoOut)
def patch_repo(
    repo_id: str, payload: RepoPatch, session: Session = Depends(get_session)
) -> RepoOut:
    repo = get_repo_or_404(repo_id, session)

    # The URL is intentionally immutable: changing it would orphan the clone.
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise ApiError(
                ErrorCode.INVALID_NAME, "Name is required.", {"field": "name"}
            )
        repo.name = name
    if payload.path is not None:
        repo.path = git_svc.normalize_path(payload.path)
    if payload.compose_file is not None:
        repo.compose_file = git_svc.validate_compose_file(payload.compose_file)

    session.add(repo)
    session.commit()
    session.refresh(repo)
    return to_repo_out(repo, session)


@router.delete("/repos/{repo_id}", status_code=204)
async def delete_repo(
    repo_id: str,
    teardown: bool = Query(False),
    session: Session = Depends(get_session),
) -> None:
    repo = get_repo_or_404(repo_id, session)

    if teardown:
        from ..services import compose_service

        # Bring the stack down before the clone disappears; ignore failures so
        # the records are still cleaned up.
        try:
            await compose_service.down(repo.slug, repo.path, repo.compose_file)
        except ApiError:
            pass

    import shutil

    clone = git_svc.clone_dir(repo.slug)
    if clone.exists():
        shutil.rmtree(clone, ignore_errors=True)

    for deployment in session.exec(
        select(Deployment).where(Deployment.repo_id == repo_id)
    ).all():
        session.delete(deployment)

    from ..models import NetworkAttachment

    for attachment in session.exec(
        select(NetworkAttachment).where(NetworkAttachment.repo_id == repo_id)
    ).all():
        session.delete(attachment)

    session.delete(repo)
    session.commit()


@router.get("/repos/{repo_id}/branches", response_model=BranchesResponse)
async def get_branches(
    repo_id: str, session: Session = Depends(get_session)
) -> BranchesResponse:
    repo = get_repo_or_404(repo_id, session)
    # Read from the remote so this works before the first clone.
    branches = await git_svc.list_branches(repo.url)
    return BranchesResponse(
        default_branch=repo.default_branch,
        branches=[BranchOut(**branch) for branch in branches],
    )


@router.get("/repos/{repo_id}/commits", response_model=list[CommitOut])
async def get_commits(
    repo_id: str,
    branch: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[CommitOut]:
    repo = get_repo_or_404(repo_id, session)
    if not git_svc.is_cloned(repo.slug):
        raise ApiError(
            ErrorCode.NOT_CLONED,
            "Repository has not been cloned yet. Deploy it first.",
        )
    commits = await git_svc.log_commits(git_svc.clone_dir(repo.slug), branch, limit)
    return [CommitOut(**commit) for commit in commits]


# --------------------------------------------------------------------------- #
# Deployments
# --------------------------------------------------------------------------- #
def get_deployment_or_404(deployment_id: str, session: Session) -> Deployment:
    deployment = session.get(Deployment, deployment_id)
    if deployment is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Deployment not found.")
    return deployment


@router.post(
    "/repos/{repo_id}/deployments", response_model=DeploymentOut, status_code=202
)
async def create_deployment(
    repo_id: str, payload: DeployRequest, session: Session = Depends(get_session)
) -> DeploymentOut:
    from ..services import deploy as deploy_svc
    from ..services import jobs

    repo = get_repo_or_404(repo_id, session)

    # One deploy per repo at a time; different repos still run in parallel.
    running = jobs.active_job_for_repo(repo_id)
    if running is not None:
        raise ApiError(
            ErrorCode.DEPLOY_IN_PROGRESS,
            "A deployment is already running for this repository.",
            {"deploymentId": running.id},
        )

    branch = payload.branch.strip()
    if not branch:
        raise ApiError(
            ErrorCode.INVALID_NAME, "Branch is required.", {"field": "branch"}
        )

    lock = jobs.repo_lock(repo_id)
    if lock.locked():
        raise ApiError(
            ErrorCode.DEPLOY_IN_PROGRESS,
            "Another operation is already running for this repository.",
        )

    deployment = Deployment(
        id=jobs.new_deployment_id(),
        repo_id=repo_id,
        branch=branch,
        requested_commit=payload.commit,
        status="queued",
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)

    # Register the job before yielding so an immediate second request sees the
    # repo as busy instead of racing the background task.
    jobs.new_job(deployment.id, repo_id)

    async def run_locked() -> None:
        # The lock is held for the whole pipeline, not just task creation, so
        # stack actions and further deploys queue behind it.
        async with lock:
            try:
                await deploy_svc.run_pipeline(
                    deployment.id, repo_id, branch, payload.commit
                )
            except Exception:
                logger.exception("Deployment %s crashed", deployment.id)

    asyncio.create_task(run_locked())

    return deployment


@router.get("/repos/{repo_id}/deployments", response_model=list[DeploymentOut])
def list_deployments(
    repo_id: str,
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[DeploymentOut]:
    get_repo_or_404(repo_id, session)
    return session.exec(
        select(Deployment)
        .where(Deployment.repo_id == repo_id)
        .order_by(Deployment.started_at.desc())
        .limit(limit)
    ).all()


@router.get("/deployments/{deployment_id}", response_model=DeploymentDetail)
async def get_deployment(
    deployment_id: str, session: Session = Depends(get_session)
) -> DeploymentDetail:
    from ..services import docker_service

    deployment = get_deployment_or_404(deployment_id, session)
    repo = get_repo_or_404(deployment.repo_id, session)

    try:
        containers: list[ContainerOut] = await docker_service.list_project_containers(
            repo.slug
        )
    except Exception:
        # Docker being unreachable must not hide the deployment record.
        containers = []

    return DeploymentDetail(**DeploymentOut.model_validate(deployment).model_dump(),
                            containers=containers)


@router.get("/deployments/{deployment_id}/logs")
async def stream_deployment_logs(
    deployment_id: str,
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> EventSourceResponse:
    from ..services import jobs

    deployment = get_deployment_or_404(deployment_id, session)

    live = jobs.get_job(deployment_id)
    if live is not None:
        log = live.log
    else:
        # A finished (or restarted) deployment replays from its stored log.
        log = jobs.load_saved_log(deployment.log)

    async def event_source():
        async for event in jobs.replay_and_follow(log, offset):
            if event.get("type") == "line":
                yield {
                    "event": "line",
                    "data": _json(event["line"]),
                }
            elif event.get("type") == "step":
                yield {
                    "event": "step",
                    "data": _json(event["step"]),
                }
            else:
                yield {"event": "done", "data": _json(event)}

    return EventSourceResponse(event_source(), ping=15)


@router.post("/deployments/{deployment_id}/cancel", response_model=DeploymentOut)
def cancel_deployment(
    deployment_id: str, session: Session = Depends(get_session)
) -> DeploymentOut:
    from ..services import jobs

    deployment = get_deployment_or_404(deployment_id, session)
    job = jobs.get_job(deployment_id)
    if job is None or job.finished.is_set():
        raise ApiError(
            ErrorCode.INVALID_STATE, "This deployment is no longer running."
        )

    job.cancel()
    return deployment


def _json(data: dict) -> str:
    import json

    return json.dumps(data, default=str)


# --------------------------------------------------------------------------- #
# Stack actions
# --------------------------------------------------------------------------- #
@router.post("/repos/{repo_id}/stack/{action}", response_model=StackActionResponse)
async def stack_action(
    repo_id: str, action: str, session: Session = Depends(get_session)
) -> StackActionResponse:
    from ..services import deploy as deploy_svc
    from ..services import jobs

    if action not in ("up", "stop", "restart", "down"):
        raise ApiError(ErrorCode.NOT_FOUND, f"Unknown stack action: {action}.")

    repo = get_repo_or_404(repo_id, session)

    lock = jobs.repo_lock(repo_id)
    if lock.locked():
        raise ApiError(
            ErrorCode.DEPLOY_IN_PROGRESS,
            "Another operation is already running for this repository.",
        )

    async with lock:
        containers = await deploy_svc.stack_action(repo, action)

    return StackActionResponse(containers=containers)