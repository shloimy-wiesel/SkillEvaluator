"""Run from the repo root on a Linux Docker bridge host. See studio/GITLAB.md."""

import argparse
import ipaddress
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path

CE = "gitlab/gitlab-ce:18.11.3-ce.0"
RUNNER = "gitlab/gitlab-runner:alpine-v18.11.0"
SMOKE = """studio-smoke:
  tags: [studio-smoke]
  rules:
    - exists: [.gitlab-ci.yml]
  script:
    - test "$(id -u)" != 0
    - test ! -S /var/run/docker.sock
    - test -s .gitlab-ci.yml
    - test -s skills/triage/SKILL.md
"""


def docker(*args, stdin=None):
    return subprocess.check_output(["docker", *args], input=stdin, text=True).strip()


def provision(work, ip, ce, runner):
    root = f"https://{ip}/forge"
    ca = work / "forge.crt"
    http = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca))
    )
    for _ in range(150):
        try:
            with http.open(root + "/users/sign_in", timeout=3):
                break
        except OSError:
            time.sleep(4)
    else:
        raise RuntimeError("GitLab did not become ready")
    # No credentials inherited from the host. This brand-new CE has only disposable data.
    mint = """u=User.find_by_username!("root"); puts %w[api write_repository read_api].map{|s|
      u.personal_access_tokens.create!(name:"studio-#{s}",scopes:[s],expires_at:1.day.from_now.to_date).token}.to_json"""
    admin, git, read = json.loads(docker("exec", ce, "gitlab-rails", "runner", mint).splitlines()[-1])

    def post(endpoint, **data):
        req = urllib.request.Request(
            root + "/api/v4/" + endpoint,
            json.dumps(data).encode(),
            {"PRIVATE-TOKEN": admin, "Content-Type": "application/json"},
        )
        with http.open(req, timeout=60) as response:
            return json.load(response)

    group = post("groups", name="engineering", path="engineering")
    sub = post("groups", name="platform", path="platform", parent_id=group["id"])
    project = post(
        "projects",
        name="handbook",
        namespace_id=sub["id"],
        visibility="private",
        initialize_with_readme=True,
        default_branch="main",
        ci_config_path="smoke-ci.yml",
        shared_runners_enabled=False,
    )
    # Some GitLab versions accept ci_config_path only on the update endpoint.
    if project.get("ci_config_path") != "smoke-ci.yml":
        req = urllib.request.Request(
            root + f"/api/v4/projects/{project['id']}",
            b'{"ci_config_path":"smoke-ci.yml"}',
            {"PRIVATE-TOKEN": admin, "Content-Type": "application/json"},
            method="PUT",
        )
        with http.open(req) as response:
            assert json.load(response)["ci_config_path"] == "smoke-ci.yml"
    post(
        f"projects/{project['id']}/repository/commits",
        branch="main",
        commit_message="Seed isolated runner smoke",
        actions=[
            {"action": "create", "file_path": "smoke-ci.yml", "content": SMOKE},
            {"action": "create", "file_path": "skills/triage/SKILL.md", "content": "# Triage\n"},
        ],
    )
    record = post(
        "user/runners",
        runner_type="project_type",
        project_id=project["id"],
        tag_list=["studio-smoke"],
        run_untagged=False,
        locked=True,
        description="studio-smoke",
    )
    docker(
        "exec",
        "-i",
        runner,
        "sh",
        "-ec",
        "read -r CI_SERVER_TOKEN; export CI_SERVER_TOKEN; exec gitlab-runner register --non-interactive "
        '--executor shell --tls-ca-file /etc/gitlab-runner/certs/ca.crt --url "$1"',
        "register",
        root,
        stdin=record["token"] + "\n",
    )
    config = work / "config.json"
    config.write_text(
        json.dumps(
            {
                "remote": project["http_url_to_repo"],
                "root": root,
                "username": "root",
                "git_token": git,
                "api_token": read,
                "ca_pem": ca.read_text(),
                "runner_id": record["id"],
            }
        )
    )
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subnet", required=True, type=ipaddress.IPv4Network, help="unused private IPv4 bridge CIDR")
    subnet = parser.parse_args().subnet
    if not subnet.is_private or subnet.num_addresses < 8:
        parser.error("choose an unused private CIDR with at least eight addresses")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="studio-gl-") as tmp, ExitStack() as cleanup:
        work = Path(tmp)
        net = docker("network", "create", "--internal", "--subnet", str(subnet), work.name)
        cleanup.callback(docker, "network", "rm", net)
        ip = str(subnet[2])
        ca, key = work / "forge.crt", work / "forge.key"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-keyout",
                key,
                "-out",
                ca,
                "-subj",
                "/CN=forge",
                "-addext",
                f"subjectAltName=IP:{ip}",
            ],
            check=True,
        )
        ca.chmod(0o644)  # Public certificate also read by non-root processes in the containers.

        def start(image, *options):
            container = docker("create", "--network", net, *options, image)
            cleanup.callback(docker, "rm", "-vf", container)
            docker("start", container)
            return container

        ce = start(
            CE,
            "--ip",
            ip,
            "--hostname",
            "forge",
            "--shm-size",
            "256m",
            "-v",
            f"{key}:/etc/gitlab/ssl/forge.key:ro",
            "-v",
            f"{ca}:/etc/gitlab/ssl/forge.crt:ro",
            "-e",
            f"GITLAB_OMNIBUS_CONFIG=external_url 'https://{ip}/forge'; letsencrypt['enable']=false; "
            "nginx['ssl_certificate']='/etc/gitlab/ssl/forge.crt'; nginx['ssl_certificate_key']='/etc/gitlab/ssl/forge.key'; "
            "prometheus_monitoring['enable']=false; puma['worker_processes']=2; sidekiq['concurrency']=8",
        )
        runner = start(RUNNER, "--security-opt", "no-new-privileges", "-v", f"{ca}:/etc/gitlab-runner/certs/ca.crt:ro")
        config = provision(work, ip, ce, runner)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"--basetemp={work / 'pytest'}",
                "tests/studio/test_gitlab_instance.py::test_reviewed_setup_runs_keyless_job",
            ],
            env={**os.environ, "STUDIO_GITLAB_RUNNER_CONFIG": str(config), "NO_PROXY": ip + ",localhost,127.0.0.1"},
            check=True,
        )


if __name__ == "__main__":
    main()
