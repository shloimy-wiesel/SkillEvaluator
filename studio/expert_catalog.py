"""Pinned input projection and per-member starter replay for root validation."""

import hashlib
import json
import shutil
from dataclasses import replace

from skillevaluator.cli_core import detect_content_type
from skillevaluator.constants import CONTENT_TYPE_SKILL, CONTENT_TYPE_UNKNOWN
from skillevaluator.utils.helpers import find_skills_in_directory

from . import live_job
from .expert_options import FILES
from .workspace import WorkspaceError


def prepare(ctx, work, options):
    source = ctx.root / options.target if options.target else ctx.skill
    root = work / "inputs" / ctx.root.name
    selected = root / source.relative_to(ctx.root)
    if source.resolve() != source or any(p.is_symlink() for p in source.rglob("*")):
        raise WorkspaceError("Choose an unlinked live input.")
    if options.content_type != "skill" and detect_content_type(source) not in (
        CONTENT_TYPE_SKILL,
        CONTENT_TYPE_UNKNOWN,
    ):
        raise WorkspaceError("Choose a skill or a directory containing skills.")
    members = []
    for original in find_skills_in_directory(source):
        member = selected / original.relative_to(source)
        live_job.copy_skill(original, member, set())
        members.append(member)
    if not members:
        raise WorkspaceError("Choose a skill or a directory containing skills.")
    live_job.init_projection(root if root != selected else root.parent, work)
    for key in FILES:
        if relative := getattr(options, key):
            dest = root / relative
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ctx.input_file(relative), dest)
    errors, starters = {}, []
    for member in members:
        try:
            live_job.check_stage_policy(member, options)
            if (member / "evals/results").exists():
                raise WorkspaceError("Remove archived evals/results from the skill before live validation.")
            errors[str(member)] = None
        except WorkspaceError as exc:
            errors[str(member)] = str(exc)
        except ValueError:
            errors[str(member)] = "Invalid pinned Harbor run policy."
        if options.snapshot_id and live_job.find_eval_file(member) is None:
            private = ctx.workspace.data_dir / "root-datasets" / ctx.project_id
            private.mkdir(parents=True, mode=0o700, exist_ok=True)
            relative = member.relative_to(selected).as_posix()
            key = options.snapshot_id
            if relative != ".":
                key += "-" + hashlib.sha256(relative.encode()).hexdigest()
            saved = private / key
            reused = saved.is_file()
            if reused:
                dataset = member / "evals/evals.json"
                dataset.parent.mkdir(exist_ok=True)
                dataset.write_bytes(ctx.workspace.cipher.decrypt(saved.read_bytes()))
            starters.append((relative, member, saved, reused))
    return replace(ctx, root=root, skill=selected), errors, starters


def retain(workspace, starters, outcome):
    notes = {}
    for relative, member, saved, reused in starters:
        if dataset := live_job.find_eval_file(member):
            if not reused:
                temporary = saved.with_suffix(".part")
                temporary.write_bytes(workspace.cipher.encrypt(dataset.read_bytes()))
                temporary.replace(saved)
            notes[relative] = "Reused saved starter" if reused else "Generated and saved starter"
    report = json.loads(outcome.report)
    if "." in notes:
        report["studio_dataset"] = notes.pop(".")
    report["studio_member_datasets"] = notes
    return replace(outcome, report=json.dumps(report))
