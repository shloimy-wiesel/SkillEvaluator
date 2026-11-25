import json
import os
import subprocess
import sys
from pathlib import Path

from .dataset_drafts import CANONICAL, dataset_destination, safe_ref, write_json
from .providers import worker_environment


def engine(draft, action, options, env=None):
    allowed = ("PATH", "SSL_CERT_FILE", "LANG")
    if env and env.get("SKILL_EVAL_LLM_PROVIDER") == "bedrock":
        allowed += (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "AWS_ROLE_ARN",
            "AWS_WEB_IDENTITY_TOKEN_FILE",
            "AWS_PROFILE",
            "AWS_SHARED_CREDENTIALS_FILE",
            "AWS_CONFIG_FILE",
        )
    runtime = {key: os.environ[key] for key in allowed if key in os.environ}
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("dataset_worker.py")), str(draft.skill), action],
            cwd=draft.root,
            env={**runtime, **(env or {}), "HOME": str(draft.root)},
            text=True,
            input=json.dumps(options),
            capture_output=True,
            timeout=180,
            check=True,
        )
    except subprocess.SubprocessError as exc:
        raise ValueError("Engine worker unavailable or timed out. Check the evaluator installation.") from exc
    response = json.loads(result.stdout)
    if "error" in response:
        raise ValueError(response["error"])
    return response


def tools_action(draft, form):
    action = form["action"]
    preview = draft.root / "generated.json"
    if action == "validate":
        options = {k: k in form for k in ("strict", "harbor_contract")}
        options["selected"] = draft.state["path"]
        return {"validation": engine(draft, action, options)}
    if action == "generate":
        options = {k: k in form for k in ("no_llm", "full", "force", "refine")}
        options["grounding"] = form["grounding"]
        if options["grounding"] not in {"skill", "intent", "trace", "auto"}:
            raise ValueError("Unknown grounding mode.")
        for key in ("prompt", "results_dir", "from_results"):
            if form.get(key):
                path = draft.skill / safe_ref(form[key])
                if not (path.is_file() if key == "prompt" else path.is_dir()):
                    raise ValueError("Selected input does not exist in this revision.")
                options[key] = str(path)
        env = {} if options["no_llm"] else worker_environment(draft.ws, draft.project.id, "chat")
        doc = engine(draft, action, options, env)["dataset"]
        write_json(preview, doc)
        return {
            "generated": doc,
            "notice": f"Generated {len(doc['evals'])} case(s) for review. Mode: {doc['generation']['mode']}.",
        }
    if action == "use_generation":
        draft.state["path"] = CANONICAL
        draft.write(json.loads(preview.read_text()))
        preview.unlink()
        return {"notice": "Generated cases added to draft."}
    if action == "migrate":
        from skillevaluator.tier3.dataset_migration import migrate_dataset

        # Apply the engine's bounded parser before its duplicate-key-preserving migration reader.
        draft.document()
        name = form.get("destination", "").strip()
        dest = None
        if name:
            if not dataset_destination(name):
                raise ValueError("Choose evals/evals.json (or YAML), or a new file under evals/datasets/.")
            dest = draft.skill / name
            dest.parent.mkdir(exist_ok=True, parents=True)
        result = migrate_dataset(draft.path, skill_name=form.get("skill_name") or None, destination=dest)
        if dest:
            draft.state["path"] = name
            draft.stage(name)
        return {
            "migration": result.dataset,
            "notice": "Migration staged; source preserved." if dest else "Migration preview.",
        }
    raise ValueError("Unknown dataset action.")
