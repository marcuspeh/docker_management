# Docker Management Portal

A self-hosted portal for a remote server, made of one backend and two separate
web apps:

- **SCM app** (`/scm/`) — register Git repositories and deploy a chosen branch.
  A deploy fetches, checks out, runs `docker compose build` then
  `docker compose up -d`, streaming live output and recording the commit hash.
- **Containers app** (`/containers/`) — manage containers and Docker networks,
  and view live logs.
- **Backend** — a FastAPI service that runs as a container and drives the host's
  Docker daemon through the mounted socket.

Each web app is built, run and deployed on its own and works as a page by itself.

## Security warning

**Mounting the Docker socket gives this container root-equivalent access to the
host.** Anyone who can reach the portal can start a container that mounts the
host filesystem. There is no authentication in v1, so the portal is published
only on `127.0.0.1`. Put it behind your own authenticating proxy before exposing
it anywhere else.

## How it fits together

```
nginx  ->  /scm/        SCM app
          /containers/  Containers app
          /api/*        FastAPI backend
                          |
                          +--> host Docker daemon (mounted socket)
                          +--> git remotes (SSH or HTTPS)
```

Compose reaches the daemon in two ways, on purpose:

- **Docker CLI via subprocess** for `build`, `up`, `down`, `stop` and `restart`,
  because those need streaming progress output.
- **Docker SDK (`docker` 7.x)** for containers, logs and networks, because those
  want structured objects.

Containers deployed by the portal are matched back to their repository through
compose labels: `com.docker.compose.project` is the repository slug and
`com.docker.compose.service` is the service name. Nothing about containers or
networks is stored in the database.

## Deploying

```bash
mkdir -p /srv/portal
docker compose up -d --build
```

Then open <http://127.0.0.1:8000/scm/>.

The workspace must be mounted at the **same path inside and outside** the
container (`/srv/portal:/srv/portal`). Compose files in your repositories often
use relative bind mounts, and those resolve against the project directory on the
host, so a different internal path would silently mount the wrong thing.

### Git credentials

Private repositories are cloned as the `root` user inside the container, which
reads `/root/.ssh`. `~/.ssh` is mounted read-only for that reason.

- **SSH:** add the host key to `~/.ssh/known_hosts` on the server, otherwise the
  clone fails on an unknown host. Git runs with `BatchMode=yes` and
  `GIT_TERMINAL_PROMPT=0`, so a missing or rejected key fails immediately instead
  of hanging the deploy.
- **HTTPS:** no credential helper is configured. Use a token in the remote URL
  or a credential helper baked into the image.

## Configuration

All settings are environment variables read by `backend/app/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `WORKSPACE_DIR` | `/srv/portal/repos` | Where repository clones live |
| `DB_URL` | `sqlite:////srv/portal/portal.db` | SQLite location |
| `CORS_ORIGINS` | empty | Only needed if an app is hosted on another origin |
| `SCM_DIST_DIR` | `/app/web/scm` | SCM app build output |
| `CONTAINERS_DIST_DIR` | `/app/web/containers` | Containers app build output |
| `GIT_TIMEOUT_SECONDS` | `20` | Timeout for `git ls-remote` |
| `COMPOSE_TIMEOUT_SECONDS` | `3600` | Timeout for one compose command |
| `LOG_BUFFER_LINES` | `10000` | In-memory log lines kept per running deploy |

Both apps are served from the same origin as the API, so `CORS_ORIGINS` stays
off. To host an app elsewhere, build it with `VITE_API_BASE_URL` pointing at the
portal and set `CORS_ORIGINS` to that app's origin.

Either app can also be left out of the backend image entirely. Its path then
returns a `404` error envelope and the rest of the service keeps working.

## A note on the deploy pipeline

`build` is the last step that can fail without consequence. A failed build
leaves the running containers exactly as they were — only `up` mutates the
stack. Cancelling a deploy before `up` has the same effect.

Each log line is numbered, so reconnecting to a deploy's log stream with
`?offset=<last seen>` resumes where it left off. Completed deploys keep their
output and can still be replayed.

## Development

Backend:

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
```

The unit suite runs without Docker. Integration tests are marked and skip
automatically when no daemon is reachable:

```bash
.venv/bin/python -m pytest -m docker
```

Run the API directly with `WORKSPACE_DIR` and `DB_URL` pointed somewhere
temporary:

```bash
WORKSPACE_DIR=/tmp/portal/repos DB_URL=sqlite:////tmp/portal.db \
  .venv/bin/uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Both dev servers proxy `/api`, so no CORS configuration is needed locally.

## Layout

```
backend/
  app/
    main.py              app factory, routers, static hosting, startup recovery
    config.py            environment settings
    db.py  models.py     engine and tables
    schemas.py           request and response models (camelCase on the wire)
    errors.py            ApiError and the single error envelope
    services/
      git_service.py     ls-remote, clone, fetch, checkout, rev-parse
      compose_service.py compose argv and invocation
      docker_service.py  containers, logs, networks
      deploy.py          the deploy pipeline and stack actions
      jobs.py            log buffering, SSE fan-out, cancellation
    routers/
      health.py  scm.py  containers.py  networks.py
  tests/
frontend/                the two Vite apps and their shared package
docs/                    backend and frontend tech design
```

The API contract, data model and deploy pipeline are specified in
[docs/tech-design-backend.md](docs/tech-design-backend.md); the frontend is in
[docs/tech-design-frontend.md](docs/tech-design-frontend.md).