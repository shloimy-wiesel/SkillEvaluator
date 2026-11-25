FROM docker:28.5-cli AS docker-tools
FROM python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS studio-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STUDIO_DATA_DIR=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git gh ca-certificates util-linux && rm -rf /var/lib/apt/lists/*
COPY studio/requirements.txt /tmp/studio-requirements.txt
RUN pip install --no-cache-dir -r /tmp/studio-requirements.txt
COPY . .
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

FROM studio-base AS standard
