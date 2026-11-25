FROM docker:28.5-cli AS docker-tools
FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS frontend
ENV NEXT_TELEMETRY_DISABLED=1 CI=true LEFTHOOK=0
WORKDIR /web
RUN npm install --global pnpm@11.25.0
COPY studio/frontend/pnpm-lock.yaml studio/frontend/pnpm-workspace.yaml ./
RUN pnpm fetch --frozen-lockfile
COPY studio/frontend/ ./
RUN pnpm install --offline --frozen-lockfile && pnpm --filter web build

FROM python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS studio-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STUDIO_DATA_DIR=/data STUDIO_FRONTEND_DIR=/app/studio-web
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git gh ca-certificates util-linux && rm -rf /var/lib/apt/lists/*
COPY studio/requirements.txt /tmp/studio-requirements.txt
RUN pip install --no-cache-dir -r /tmp/studio-requirements.txt
COPY . .
COPY --from=frontend /web/apps/web/out /app/studio-web
ARG STUDIO_TIER3=false
RUN if [ "$STUDIO_TIER3" = true ]; then pip install --no-cache-dir '.[tier2,tier3]'; else pip install --no-cache-dir '.[tier2]'; fi && useradd --create-home --uid 10001 studio && install -d -o studio -g studio -m 0700 /data
USER studio
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn","studio.app:create_app","--factory","--host","0.0.0.0","--port","8000"]

FROM studio-base AS live
USER root
COPY --from=docker-tools /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-tools /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/
RUN pip install --no-cache-dir '.[tier3]' -r studio/requirements.txt && docker compose version && harbor --version
USER studio

# Optional Gym CLI stays in its own Python environment; never install at job time.
FROM live AS live-gym
USER root
ENV UV_PYTHON_INSTALL_DIR=/opt/studio-python
RUN pip install --no-cache-dir uv==0.13.4 && \
    uv venv --python 3.13.14 /opt/studio-gym && \
    uv pip install --python /opt/studio-gym/bin/python \
      'nemo-gym @ git+https://github.com/NVIDIA-NeMo/Gym@792fa142f58277aecff05d402061d647e9a92acf' && \
    /opt/studio-gym/bin/gym eval run --help >/dev/null
USER studio

FROM studio-base AS standard
