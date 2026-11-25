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
serve it behind an authenticated TLS proxy for a trusted operator. The
standard CLI and its original Dockerfile remain independently usable.

For local startup, extension points, and browser tests see [DEVELOPMENT.md](DEVELOPMENT.md).
