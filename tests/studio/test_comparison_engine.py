from pathlib import Path

import pytest

pytest_plugins = ("test_version_comparison",)


def test_retained_version_change_is_not_baseline_lift(tmp_path, monkeypatch, evaluation):
    from studio.comparison_evidence import retained_evidence

    volume = tmp_path.resolve()
    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(volume / "tier3-output.key"))
    project = "1" * 32
    runs = []
    for revision, score in (("a", 0.8), ("b", 0.2)):
        run_id = revision * 32
        root = volume / "artifacts" / project / run_id / "tier3" / "demo"
        result = evaluation(revision, score, output_dir=root)
        assert Path(result["run_dir"]).parent == root
        runs.append((run_id, revision * 40))
    evidence = retained_evidence(volume, project, runs)
    assert evidence["comparison"]["agents"]["opencode"]["delta"] == pytest.approx(-0.6)
    assert evidence["history"][1][0]["lift_delta"] == pytest.approx(-0.3)


@pytest.mark.parametrize("damage", ["missing", "linked", "oversized", "wrong-revision"])
def test_missing_or_untrusted_evidence_never_produces_a_delta(tmp_path, monkeypatch, evaluation, damage):
    from studio.comparison_evidence import retained_evidence

    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(tmp_path / "tier3-output.key"))
    project, run = "1" * 32, "a" * 32
    root = tmp_path / "artifacts" / project / run / "tier3"
    directory = Path(evaluation(output_dir=root)["run_dir"])
    selection = (run, "a" * 40)
    if damage == "missing":
        next(directory.glob("*/with-skill/trials/*/reward.json")).unlink()
    elif damage == "linked":
        outside = tmp_path / "foreign-project"
        directory.rename(outside)
        directory.symlink_to(outside)
    elif damage == "oversized":
        with (directory / "run_config.json").open("ab") as file:
            file.truncate(9 * 1024**2)
    else:
        selection = (run, "b" * 40)
    comparison = retained_evidence(tmp_path, project, [selection, selection])["comparison"]
    assert comparison["status"] == "unavailable"
    assert comparison["reasons"] and not comparison.get("agents")
