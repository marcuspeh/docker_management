"""Application factory.

The backend is a pure API service that also serves the two production web app
builds. All routes live on one ``/api`` router so authentication can be added
later in a single place.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .db import init_db, session_scope
from .errors import ErrorCode, register_error_handlers
from .routers import containers, health, networks, scm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    await recover_interrupted_deployments()
    logger.info("Portal backend ready")
    yield


async def recover_interrupted_deployments() -> None:
    """Fail deployments left marked running by a previous process.

    Job state lives in memory and the service runs a single worker, so anything
    still 'running' at startup lost its runner with the old process.
    """
    from sqlmodel import select

    from . import models

    with session_scope() as session:
        stale = session.exec(
            select(models.Deployment).where(
                models.Deployment.status.in_(models.RUNNING_STATUSES)
            )
        ).all()
        for deployment in stale:
            deployment.status = "failed"
            deployment.error = "Interrupted by a backend restart."
        if stale:
            logger.info("Marked %d interrupted deployment(s) as failed", len(stale))


class SPAStaticFiles(StaticFiles):
    """Static files with a per-app SPA fallback and correct cache headers.

    Plain StaticFiles answers 404 for a client-side route such as ``/scm/123``,
    which would break deep links and refreshes. Anything that does not match a
    file falls back to this app's own index.html instead, so each app resolves
    its own routes rather than leaking into the other one.
    """

    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            response = None

        if response is None or response.status_code == 404:
            index = Path(self.directory) / "index.html"
            if not index.is_file():
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": {
                            "code": ErrorCode.NOT_FOUND,
                            "message": "index.html is missing from this build.",
                            "detail": {},
                        }
                    },
                )
            response = FileResponse(index)

        # Hashed asset filenames are immutable; the entry document is not.
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="Docker Management Portal", version="0.1.0", lifespan=lifespan)

    if settings.cors_origins:
        # Off by default: both apps are served from this same origin.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_error_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(scm.router, prefix="/api/scm")
    app.include_router(containers.router, prefix="/api/containers")
    app.include_router(networks.router, prefix="/api/networks")

    _mount_static_apps(app)
    return app


def _mount_static_apps(app: FastAPI) -> None:
    """Serve each web app's dist under its own base path.

    A request that matches no file falls back to that app's index.html so deep
    links work. An app whose directory is absent returns 404 and the rest of the
    service keeps working, so either app can be hosted elsewhere.
    """
    from fastapi.responses import RedirectResponse

    apps = (
        ("/scm", settings.scm_dist_dir),
        ("/containers", settings.containers_dist_dir),
    )

    @app.get("/", include_in_schema=False)
    async def _root() -> RedirectResponse:
        return RedirectResponse(url="/scm/")

    for base_path, dist_dir in apps:
        if dist_dir.is_dir():
            app.mount(
                base_path,
                SPAStaticFiles(directory=dist_dir, html=True),
                name=f"static{base_path.replace('/', '_')}",
            )
        else:
            logger.warning(
                "Web app directory %s is missing; %s will not be served",
                dist_dir,
                base_path,
            )

            # No mount for this app, so answer its paths directly. A path
            # parameter does not match an empty segment, so the bare base path
            # needs its own route.
            async def _missing_app(_full_path: str = ""):
                return JSONResponse(
                    status_code=404,
                    content={
                        "error": {
                            "code": ErrorCode.NOT_FOUND,
                            "message": "Web app is not deployed on this server.",
                            "detail": {},
                        }
                    },
                )

            app.get(base_path, include_in_schema=False)(_missing_app)
            app.get(
                f"{base_path}/{{full_path:path}}", include_in_schema=False
            )(_missing_app)


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # A single worker: deploy job state is held in memory.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)