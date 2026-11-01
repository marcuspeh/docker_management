# syntax=docker/dockerfile:1

# The portal API: a pure API service that drives the host's Docker daemon
# through the mounted socket. The web apps are served by nginx in
# ../frontend, so only /api is reached here.

FROM python:3.12-slim

# git and ssh are needed to clone repositories, including private ones.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The Docker CLI and its plugins ship in the docker cli image. The CLI is
# what runs `docker compose`; the SDK talks to the socket directly.
# The cli-plugins directory is the one the CLI searches by default.
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    DEPLOYMENT_DIST_DIR=/app/web/deployment \
    CONTAINERS_DIST_DIR=/app/web/containers

EXPOSE 8000

# A single worker: deployment job state lives in memory and is not shared
# between processes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]