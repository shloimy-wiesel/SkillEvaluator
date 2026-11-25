"""Revision-bound authoring copies. Only explicitly staged files may be published."""

import json
import re
import shutil
from pathlib import Path, PureWindowsPath
from uuid import uuid4

import yaml

from skillevaluator.tier3.case_ids import validate_case_ids
from skillevaluator.tier3.dataset_utils import DATASET_EXTENSIONS, find_eval_file, parse_dataset_text

from .diff_preview import file_diffs
from .editing import read_file
from .workspace import WorkspaceError

CANONICAL = "evals/evals.json"
NAMED = r"evals/datasets/[A-Za-z0-9_-]+\.(?:json|yaml|yml)"


def dataset_destination(name):
    return bool(re.fullmatch(NAMED, name) or name in {f"evals/evals{ext}" for ext in (".json", ".yaml", ".yml")})


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + uuid4().hex)
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def safe_ref(name):
    if (
        not name
        or PureWindowsPath(name).drive
        or any(c in name for c in "\\:")
        or any(ord(c) < 32 for c in name)
        or any(part.casefold() in ("", ".", "..", ".git") for part in name.split("/"))
    ):
        raise ValueError("Choose a relative path inside the skill.")
    return name


class Draft:
    def __init__(self, ws, project, token):
        if not re.fullmatch("[a-f0-9]{32}", token):
            raise ValueError("Invalid draft.")
        self.root = ws.data_dir / "dataset-drafts" / project.id / token
        self.meta = self.root / "state.json"
        self.ws, self.project, self.token = ws, project, token
        self.state = json.loads(self.meta.read_text())
        self.skill = self.root / "source" / self.state["folder"]

    @classmethod
    def create(cls, ws, project):
        read_file(ws, project, "SKILL.md")  # verify clean checkout and expected branch/SHA
        token = uuid4().hex
        root = ws.data_dir / "dataset-drafts" / project.id / token
        folder = safe_ref(Path(project.folder).name or project.name)
        skill = root / "source" / folder
        prefix = "" if project.folder == "." else project.folder + "/"
        tree = ws.git(
            project, ["--literal-pathspecs", "ls-tree", "-rlz", project.revision, "--", project.folder], raw=True
        )
        try:
            size = 0
            for index, entry in enumerate(tree.split(b"\0")):
                if not entry:
                    continue
                header, path = entry.split(b"\t", 1)
                mode, _, oid, length = header.split()
                if mode not in (b"100644", b"100755"):
                    raise WorkspaceError("Drafts require regular files inside the selected skill.")
                name = safe_ref(path.decode().removeprefix(prefix))
                size += int(length)
                if size > 64 * 1024**2 or index >= 4096:
                    raise WorkspaceError("Skill exceeds the Studio draft limit (64 MiB, 4096 files).")
                target = skill / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(ws.git(project, ["cat-file", "blob", oid.decode()], raw=True))
            active = find_eval_file(skill)
            write_json(
                root / "state.json",
                {
                    "branch": project.branch,
                    "revision": project.revision,
                    "folder": folder,
                    "version": 0,
                    "path": active.relative_to(skill).as_posix() if active else CANONICAL,
                    "staged": [],
                },
            )
            return cls(ws, project, token)
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise

    @property
    def path(self):
        return self.skill / self.state["path"]

    def document(self):
        if self.path.exists():
            return parse_dataset_text(self.path.read_text(encoding="utf-8"), self.path.suffix)
        return {"skill_name": self.state["folder"], "evals": []}

    def choices(self):
        standard = [stem + ext for stem in ("evals/evals", "eval/dataset") for ext in DATASET_EXTENSIONS]
        named = [p.relative_to(self.skill).as_posix() for p in (self.skill / "evals/datasets").glob("*") if p.is_file()]
        return sorted(
            {
                CANONICAL,
                *(s for s in standard if (self.skill / s).is_file()),
                *(s for s in named if re.fullmatch(NAMED, s)),
            }
        )

    def manage(self, form):
        if form["action"] == "switch":
            name = form["dataset"]
            if name not in self.choices():
                raise ValueError("Choose an available dataset.")
            self.state["path"] = name
            self.stage()
        elif form["action"] == "create":
            name = "evals/datasets/" + form["name"] + ".json"
            if not re.fullmatch(NAMED, name) or (self.skill / name).exists():
                raise ValueError("Choose an unused dataset name using letters, numbers, underscores or hyphens.")
            self.state["path"] = name
            self.write(self.document())
        else:
            doc = self.document()
            if not isinstance(doc, dict) or "evals" not in doc or not form["identity"].strip():
                raise ValueError("Enter a skill identity for an object dataset.")
            doc["skill_name"] = form["identity"].strip()
            self.write(doc)

    def stage(self, *names):
        self.state["version"] += 1
        self.state["staged"] = sorted(set(self.state["staged"]).union(names))
        write_json(self.meta, self.state)

    def write(self, document):
        if self.path.suffix in {".yaml", ".yml"}:
            self.path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
        else:
            write_json(self.path, document)
        self.stage(self.state["path"])

    def case(self, form, action):
        doc = self.document()
        if not isinstance(doc, dict) or not isinstance(doc.get("evals"), list) or self.path.suffix == ".jsonl":
            raise ValueError("Migrate this dataset to an object before editing cases.")
        cases = doc["evals"]
        index = int(form.get("index", -1))
        if action != "add" and not 0 <= index < len(cases):
            raise ValueError("Unknown case.")
        if action == "remove":
            cases.pop(index)
        else:
            entry = {} if action == "add" else cases[index]
            if str(entry.get("id")) != form["case_id"] or "id" not in entry:
                entry["id"] = form["case_id"]
            for key in ("prompt", "expected_output"):
                if key not in form and key not in entry:
                    raise ValueError("Enter a prompt and expected output.")
                if key in form:
                    if not form[key].strip():
                        raise ValueError("Enter a prompt and expected output.")
                    entry[key] = form[key].replace("\r\n", "\n")
            if "assertions" in form:
                lines = form["assertions"].replace("\r\n", "\n").split("\n")
                if any(lines) or "assertions" in entry:
                    entry["assertions"] = [s for s in lines if s]
            if form.get("file_mode") == "explicit":
                entry["files"] = [safe_ref(s.strip()) for s in form["files"].splitlines() if s.strip()]
            elif form.get("file_mode") == "inherit":
                entry.pop("files", None)
            if form.get("trigger") in ("yes", "no"):
                entry["should_trigger"] = form["trigger"] == "yes"
            elif form.get("trigger") == "inherit":
                entry.pop("should_trigger", None)
            if action == "add":
                cases.append(entry)
            validate_case_ids(item.get("id") for item in cases)
        self.write(doc)

    def _staged_files(self):
        for name in self.state["staged"]:
            path = self.skill / name
            yield name, path.read_bytes() if path.exists() else None

    def changes(self):
        return dict(self._staged_files())

    def diff(self):
        files = (
            (name, read_file(self.ws, self.project, name) or b"", after or b"", "")
            for name, after in self._staged_files()
        )
        return file_diffs(files) or "No changes."
