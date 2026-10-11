# syntax=docker/dockerfile:1

# The portal API: a pure API service that drives the host's Docker daemon
# through the mounted socket. It also serves the two web app builds if they
# are present, which is what the single-image deployment uses; when nginx
# fronts the apps instead, only /api is reached.

FROM python:3.12-slim

# git and ssh are needed to clone repositories, including private ones.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The compose plugin ships in the docker cli image; the SDK talks to the
# socket directly.
COPY --from=docker:cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/
COPY --from=docker:cli /usr/local/lib/docker/cli-plugins/ /usr/local/lib/docker/cli-plugins/

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    SCM_DIST_DIR=/app/web/scm \
    CONTAINERS_DIST_DIR=/app/web/containers

EXPOSE 8000

# A single worker: deployment job state lives in memory and is not shared
# between processes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]