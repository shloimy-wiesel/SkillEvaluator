"""CI consumer of the persisted, project-bound GitLab instance transport (#18)."""

import io
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

from rich.console import Console

from skillevaluator import ci_onboarding as ci

from .workspace import WorkspaceError


def configured_instance(ws, p):
    try:
        from .gitlab import instance
    except ModuleNotFoundError as exc:
        if exc.name != "studio.gitlab":
            raise
        return None
    lab = instance(ws, p)
    if lab is not None:
        clone, project = urlsplit(p.remote), urlsplit(lab.web_url)
        if (
            lab.root + "/" + lab.namespace != lab.web_url
            or project.scheme != "https"
            or project.netloc.lower() != clone.netloc.lower()
            or project.path != clone.path.rstrip("/").removesuffix(".git")
            or project.query
            or project.fragment
        ):
            raise WorkspaceError("Configured GitLab instance does not match this project.")
    return lab


def resource(lab, kind, number):
    if type(number) is not int or number < 1:
        raise WorkspaceError("The GitLab API returned an invalid resource identifier.")
    return f"{lab.web_url}/-/{kind}/{number}"


class StatusClient:
    platform = "gitlab"

    def __init__(self, ws, p, lab):
        self.ws, self.p, self.lab = ws, p, lab
        self.origin, self.name = lab.root, lab.namespace

    def info(self):
        info = self.lab.request("GET")
        if not isinstance(info, dict) or info.get("archived") or not isinstance(info.get("default_branch"), str):
            raise WorkspaceError("Cannot inspect the GitLab default branch.")
        self.branch = branch = info["default_branch"]
        self.ws.git(self.p, ["check-ref-format", "refs/heads/" + branch])
        self.ws.git(self.p, ["fetch", "--no-tags", "--", self.p.remote, "refs/heads/" + branch], authenticated=True)
        self.tip = self.ws.git(self.p, ["rev-parse", "FETCH_HEAD"])
        return info

    def file(self, path, ref):
        if ref != self.branch:
            raise WorkspaceError("CI snapshot does not match this branch.")
        entry = self.ws.git(self.p, ["--literal-pathspecs", "ls-tree", self.tip, "--", path])
        if not entry:
            return None
        if not entry.startswith(("100644 blob ", "100755 blob ")):
            raise WorkspaceError("Expected a regular CI configuration file.")
        oid = entry.split("\t", 1)[0].split()[2]
        if int(self.ws.git(self.p, ["cat-file", "-s", oid])) > 128 * 1024:
            raise WorkspaceError("CI configuration exceeds the inspection limit.")
        return self.ws.git(self.p, ["cat-file", "blob", oid], raw=True).decode("utf-8", errors="replace")

    def api(self, method, suffix, *, missing_ok=False):
        path = urlsplit(suffix)
        if not missing_ok or method != "GET" or path.path != "/pipelines":
            raise WorkspaceError("Unsupported pipeline status request.")
        values = self.lab.request("GET", "/pipelines", query=dict(parse_qsl(path.query)))
        if not isinstance(values, list):
            raise WorkspaceError("GitLab did not return a pipeline list.")
        return [
            {"status": item.get("status", "unknown"), "web_url": resource(self.lab, "pipelines", item.get("id"))}
            for item in values[:1]
        ]


def host_operation(ws, p, lab, task, params):
    if task == "status":
        if params["platform"] == "github":
            raise WorkspaceError("GitHub does not match this GitLab project.")
        output = io.StringIO()
        console = Console(file=output, width=2000, force_terminal=False)
        wizard = SimpleNamespace(console=console, print_link=lambda url: console.print(url, markup=False))
        # Project tokens need not have instance-level version access. Retain the
        # engine's explicit unverified-version advisory instead of assuming 18.4+.
        ci.all_tier_helpers.inspect_client(wizard, StatusClient(ws, p, lab), admission={"verified": False})
        return {"status": output.getvalue()}
    if task == "admission":
        info = lab.request("GET")
        if not isinstance(info, dict) or info.get("archived") or info.get("default_branch") != p.branch:
            raise WorkspaceError("Open the current GitLab default branch before creating a merge request.")
        return {}
    if task == "existing_review":
        values = lab.request("GET", "/merge_requests", query={"state": "opened", "source_branch": params["head"]})
        if not isinstance(values, list) or len(values) != 1:
            raise WorkspaceError("Inspect the existing branch on GitLab; no unique open merge request was found.")
        item = values[0]
        if (
            item.get("sha") != params["tip"]
            or item.get("source_branch") != params["head"]
            or item.get("target_branch") != p.branch
            or not item.get("source_project_id")
            or item.get("source_project_id") != item.get("target_project_id")
        ):
            raise WorkspaceError("The merge request differs from the reviewed branch or target.")
    elif task == "review_request":
        item = lab.request(
            "POST",
            "/merge_requests",
            payload={
                "source_branch": params["head"],
                "target_branch": p.branch,
                "title": params["title"],
                "remove_source_branch": True,
            },
        )
    else:
        raise WorkspaceError("Unsupported GitLab host operation.")
    return {"notice": resource(lab, "merge_requests", item.get("iid") if isinstance(item, dict) else None)}
