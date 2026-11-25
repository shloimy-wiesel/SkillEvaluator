"""CI consumer of the persisted, project-bound GitLab instance transport (#18)."""

import io
from types import SimpleNamespace
from urllib.parse import urlsplit

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
    if type(number) is not int or not 0 < number < 2**63:
        raise WorkspaceError("The GitLab API returned an invalid resource identifier.")
    return f"{lab.web_url}/-/{kind}/{number}"


class StatusClient:
    platform = "gitlab"

    def __init__(self, ws, p, lab):
        self.ws, self.p, self.lab = ws, p, lab
        self.origin, self.name = lab.root, lab.namespace
        self.pipelines = []

    def info(self):
        info = self.lab.request("GET")
        if not isinstance(info, dict) or info.get("archived") or not isinstance(info.get("default_branch"), str):
            raise WorkspaceError("Cannot inspect the GitLab default branch.")
        self.branch = branch = info["default_branch"]
        self.project_id = info.get("id")
        self.ws.git(self.p, ["check-ref-format", "refs/heads/" + branch])
        self.ws.git(
            self.p, ["fetch", "--depth=2", "--no-tags", "--", self.p.remote, "refs/heads/" + branch], authenticated=True
        )
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
        if self.p.branch != self.branch or self.p.revision != self.tip:
            raise WorkspaceError("Open the current default branch revision to inspect its pipeline.")
        values = self.lab.request("GET", "/pipelines", query={"ref": self.branch, "sha": self.tip, "per_page": 20})
        if not isinstance(values, list) or len(values) > 20:
            raise WorkspaceError("GitLab did not return a pipeline list.")
        if not values:
            return []
        for item in values:
            if not self.matches_revision(item):
                raise WorkspaceError("GitLab returned a pipeline outside the selected project or revision.")
            link = resource(self.lab, "pipelines", item.get("id"))
            self.pipelines.append({"id": item["id"], "status": ci_status(item), "web_url": link})
        return self.pipelines[:1]

    def matches_revision(self, pipeline):
        return (
            isinstance(pipeline, dict)
            and type(self.project_id) is int
            and type(pipeline.get("project_id")) is int
            and pipeline["project_id"] == self.project_id
            and pipeline.get("ref") == self.branch
            and pipeline.get("sha") == self.tip
        )

    def job_view(self, selected):
        if not self.pipelines and selected is None:
            return {}
        selected = self.pipelines[0]["id"] if selected is None else selected
        if not any(p["id"] == selected for p in self.pipelines):
            raise WorkspaceError("Pipeline is not available for this project and revision.")
        rows = []
        for page in (1, 2):
            batch = self.lab.request("GET", f"/pipelines/{selected}/jobs", query={"per_page": 50, "page": page})
            if not isinstance(batch, list) or len(batch) > 50:
                raise WorkspaceError("GitLab returned an invalid jobs page.")
            for job in batch:
                pipeline = job.get("pipeline") if isinstance(job, dict) else None
                if (
                    not self.matches_revision(pipeline)
                    or type(pipeline.get("id")) is not int
                    or pipeline["id"] != selected
                ):
                    raise WorkspaceError("GitLab returned a job outside the selected pipeline.")
                name = job.get("name")
                if not isinstance(name, str) or not name or len(name) > 255 or not name.isprintable():
                    raise WorkspaceError("GitLab returned an invalid job name.")
                rows.append({"name": name, "status": ci_status(job), "url": resource(self.lab, "jobs", job.get("id"))})
            if len(batch) < 50:
                break
        return {"pipelines": self.pipelines, "selected": selected, "jobs": rows}


def ci_status(record):
    status = record.get("status")
    return (
        status
        if status
        in (
            "created",
            "waiting_for_resource",
            "preparing",
            "pending",
            "running",
            "success",
            "failed",
            "canceling",
            "canceled",
            "skipped",
            "manual",
            "scheduled",
            "waiting_for_callback",
        )
        else "unknown"
    )


def host_operation(ws, p, lab, task, params):
    if task == "status":
        if params["platform"] == "github":
            raise WorkspaceError("GitHub does not match this GitLab project.")
        output = io.StringIO()
        console = Console(file=output, width=2000, force_terminal=False)
        wizard = SimpleNamespace(console=console, print_link=lambda url: console.print(url, markup=False))
        # Project tokens need not have instance-level version access. Retain the
        # engine's explicit unverified-version advisory instead of assuming 18.4+.
        client = StatusClient(ws, p, lab)
        ci.all_tier_helpers.inspect_client(wizard, client, admission={"verified": False})
        return {"status": output.getvalue(), **client.job_view(params.get("pipeline_id"))}
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
