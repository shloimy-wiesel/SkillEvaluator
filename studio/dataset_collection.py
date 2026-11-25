"""Bridge the private draft to a bounded, revision-pinned Harbor run."""

from .dataset_drafts import write_json
from .dataset_tools import engine
from .live_job import LIVE, Controls, snapshot


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
    runs = [p.parent for p in root.glob("*/result.json") if p.is_file() and p == p.resolve()]
    if len(runs) != 1:
        raise ValueError("A single completed Harbor result is required.")
    # The evaluator may consult fallback log files. Never follow a link in trial evidence.
    for trials in runs[0].glob("*/with-skill/trials"):
        if trials.resolve() != trials or any(
            p.is_symlink() or not (p.is_dir() or (p.is_file() and p.stat().st_nlink == 1)) for p in trials.rglob("*")
        ):
            raise ValueError("Unsupported linked sandbox evidence.")
    doc = engine(draft, "generate", {"grounding": "trace", "no_llm": True, "from_results": str(runs[0])})["dataset"]
    write_json(draft.root / "generated.json", doc)
    draft.stage()
    return {"generated": doc, "notice": f"Generated {len(doc['evals'])} case(s) from the sandbox trial."}
