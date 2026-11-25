# SkillEvaluator Studio

Studio is a single-operator browser workspace for a Git-backed skill. Run these
commands from the repository root:

```sh
docker build -f studio/Dockerfile -t skillevaluator-studio .
docker volume create skill-workspace
docker run -d --name skill-studio -p 127.0.0.1:8000:8000 \
  -v skill-workspace:/data skillevaluator-studio
```

Open <http://127.0.0.1:8000>. Enter the HTTPS clone URL from GitHub, GitLab,
or your self-hosted instance. Use the final URL (no redirects). Enter `.`
for a root skill or a path such as `skills/triage`; that directory must
contain a regular `SKILL.md` on the remote's default branch. Private projects
also need a username and access token: for GitHub use your account and a token
with repository contents read access; for GitLab use your username and a
token with `read_repository`. Enter credentials in the separate fields.
For a private GitLab installation, expand **Self-managed GitLab** and enter
the installation URL (including any port and prefix), not the group URL.
See [GitLab access and TLS](GITLAB.md) for private CA and API settings.

Open a project to see its folder, checked-out branch, and full revision.
**Check remote access** verifies the saved credentials without updating the checkout.

To replace the container, `docker rm -f skill-studio`, rebuild if desired,
and repeat the `docker run` command with the **same volume**. No reconnect
is needed. Back up the entire volume with Studio stopped. It holds checkouts,
SQLite and the encryption key: losing the key loses credential access, and
anyone with the full backup can decrypt the secrets. A bind mount instead
of a named volume must be writable by UID 10001. For an internal Git CA,
mount its PEM trust bundle read-only and set `GIT_SSL_CAINFO` to its container path.

The app has no built-in user authentication. Keep the loopback binding or
serve it behind an authenticated TLS proxy for a trusted operator. By default
Studio accepts the HTTP `Host` names `127.0.0.1`, `localhost`, and `[::1]`.
For a proxy, set `STUDIO_TRUSTED_HOSTS=studio.example.org` on Studio (multiple
exact names are comma-separated, without schemes, ports, or wildcards). Have
the proxy preserve the public `Host` including its port and forward the HTTPS
scheme; configure Uvicorn to trust proxy headers only from that proxy. Form
submissions still require same-origin access. The standard CLI and its original
Dockerfile remain independently usable.

For local startup, extension points, and browser tests see [DEVELOPMENT.md](DEVELOPMENT.md).

## Live Tier 3 image

Build the optional live target; it installs the engine's `tier3` extra
(including Harbor 0.25), Docker CLI, Buildx and Compose. Use a **dedicated
sandbox Docker daemon** on a worker VM. Access to its socket grants control
of that daemon. Only Studio receives the socket, never the evaluated skill.
The default Studio image needs no daemon and no privileged container.

On the dedicated worker, use the same absolute data path on both sides of the
bind mount: Harbor's sibling trial containers need to resolve worker paths.
For an existing Studio, stop it first and use its *whole* persistent volume
contents (including `credential.key`) as the data directory.

```sh
docker build --target live -f studio/Dockerfile -t skillevaluator-studio:live .
DATA=/srv/skill-studio
SOCKET=/var/run/docker.sock  # dedicated worker daemon
sudo install -d -m 0700 -o 10001 -g 10001 "$DATA"
docker run -d --name skill-studio-live -p 127.0.0.1:8000:8000 \
  --group-add "$(stat -c %g "$SOCKET")" \
  -v "$SOCKET:/var/run/docker.sock" -v "$DATA:$DATA" \
  -e STUDIO_DATA_DIR="$DATA" -e STUDIO_LIVE_ENABLED=1 \
  skillevaluator-studio:live
docker exec skill-studio-live docker info
docker exec skill-studio-live docker compose version
```

To enable [project-suite grader qualification](ASSETS.md#qualify-against-a-project-suite),
also pass `-e STUDIO_GRADER_IMAGE="$(docker image inspect --format '{{.Id}}' skillevaluator-studio:live)"`
to the Studio container. That trusted image must already exist on the sandbox daemon.

Allow the worker to build/pull Harbor task images and install agent runtimes;
allow trial containers to reach your HTTPS model endpoint. A loopback provider
URL on the Studio container is not reachable as loopback in a sibling trial.
Configure **Provider settings → Chat**, then use [the live run form](RUNS.md#live-tier-3).
There is no requirement for `docker run --privileged`. Kata additionally needs
a working Kata runtime on the daemon. After an abrupt worker kill, inspect
and clean up any leftover Harbor trial containers and networks on that daemon.
