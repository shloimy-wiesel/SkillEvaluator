"""Translate a bounded browser upload and human decisions into the engine review contract."""

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from skillevaluator.tier3.trace_import import accept_traces, import_traces, redact

from .dataset_drafts import CANONICAL, safe_ref, write_json


def review_document(draft):
    path = draft.root / "review/candidates.json"
    return json.loads(path.read_text()) if path.exists() else None


def traces(draft, form):
    review = draft.root / "review"
    if form["action"] == "import":
        upload = form.get("export")
        if not getattr(upload, "filename", None):
            raise ValueError("Choose a trace export.")
        raw = upload.file.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise ValueError("Trace exports must be at most 2 MiB.")
        # Raw export is never retained in the review or copied into Git.
        with TemporaryDirectory(dir=draft.root) as tmp:
            export = Path(tmp) / safe_ref(Path(upload.filename).name)
            export.write_bytes(raw)
            dry = "dry_import" in form
            doc = import_traces(draft.skill, export, review, force="force_import" in form, dry_run=dry)
        return {"sample": doc if dry else None, "notice": f"{len(doc['candidates'])} candidate(s) for review."}
    doc = review_document(draft)
    if not doc:
        raise ValueError("Import candidates before accepting them.")
    for candidate in doc["candidates"]:
        cid = candidate["id"]
        review_fields = {
            "decision": form["decision_" + cid],
            "expected_output": form["expected_" + cid],
            "assertions": [s for s in form["assertions_" + cid].splitlines() if s.strip()],
        }
        if redact(review_fields)[0] != review_fields:
            raise ValueError("Remove sensitive data from the review.")
        candidate["review"].update(review_fields)
        for ref in candidate["files"]:
            safe_ref(ref)
    dry = form["action"] == "preview_accept"
    # Invalid or unconsented decisions must not overwrite the resumable review.
    with TemporaryDirectory(dir=draft.root) as tmp:
        proposed = Path(tmp)
        write_json(proposed / "candidates.json", doc)
        for candidate in doc["candidates"]:
            for ref in candidate["files"]:
                target = proposed / ref
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(review / ref, target)
        result = accept_traces(draft.skill, proposed, dry_run=dry, allow_native_harbor="allow_native" in form)
    write_json(review / "candidates.json", doc)
    if result["added"] and not dry:
        draft.state["path"] = CANONICAL
        additions = set(result["added"])
        fixtures = [
            f"evals/{safe_ref(ref)}"
            for case in draft.document()["evals"]
            if case["id"] in additions
            for ref in case["files"]
        ]
        draft.stage(CANONICAL, *fixtures)
    return {
        "notice": f"{'Preview' if dry else 'Staged'}: {len(result['added'])} addition(s), "
        f"{len(result['already present'])} already present, {len(result['skipped'])} skipped.",
        "trace_checks": result["validation"],
        "allow_native": "allow_native" in form,
    }
