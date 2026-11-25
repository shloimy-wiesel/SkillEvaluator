"""Bridge the private draft to a bounded, revision-pinned Harbor run."""

from .dataset_drafts import write_json
from .dataset_tools import engine
from .live_job import LIVE, Controls, snapshot
from .native_location import native_directory


def collect(draft, jobs, consent):
    if not consent:
        raise ValueError("Trajectory collection requires explicit paid sandbox consent.")
    controls = Controls(
        arms="skill",
        grading_mode="default",
        env_mode="docker",
        max_cases=1,
        max_agents=1,
        n_attempts=1,
        max_attempts_total=1,
        agent_runtime_preflight=False,
    )
    options = snapshot(draft.ws, draft.project.id, controls)
    run = jobs.enqueue(draft.project, draft.state["revision"], LIVE, options)
    draft.state["collection"] = run
    draft.stage()
    return run


def refine_collected(draft, jobs):
    run = draft.state.get("collection", "")
    row = jobs.get(draft.project.id, run)
    if (
        not row
        or row["sha"] != draft.state["revision"]
        or row["kind"] != LIVE.kind
        or row["status"] not in {"passed", "failed", "neutral"}
    ):
        raise ValueError("A completed sandbox trial for this draft revision is required.")
    root = draft.ws.data_dir / "artifacts" / draft.project.id / run / "tier3"
    native = native_directory(root)
    # The evaluator may consult fallback log files. Never follow a link in trial evidence.
    total = 0
    for trials in native.glob("*/with-skill/trials"):
        if trials.resolve() != trials:
            raise ValueError("Unsupported linked sandbox evidence.")
        for index, path in enumerate(trials.rglob("*")):
            if path.is_symlink() or not (path.is_dir() or (path.is_file() and path.stat().st_nlink == 1)):
                raise ValueError("Unsupported linked sandbox evidence.")
            if path.is_file():
                total += path.stat().st_size
            if index >= 16000 or total > 64 * 1024**2:
                raise ValueError("Trial evidence exceeds the draft refinement limit.")
    doc = engine(draft, "generate", {"grounding": "trace", "no_llm": True, "from_results": str(native)})["dataset"]
    write_json(draft.root / "generated.json", doc)
    draft.stage()
    return {"generated": doc, "notice": f"Generated {len(doc['evals'])} case(s) from the sandbox trial."}
