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
    evidence = retained_evidence(volume, project, runs, "demo")
    assert evidence["comparison"]["agents"]["opencode"]["delta"] == pytest.approx(-0.6)
    assert evidence["history"][1][0]["lift_delta"] == pytest.approx(-0.3)


@pytest.mark.parametrize(
    "damage", ["missing", "linked", "oversized", "wrong-revision", "wrong-skill", "unsigned-directory"]
)
def test_missing_or_untrusted_evidence_never_produces_a_delta(tmp_path, monkeypatch, evaluation, damage):
    from studio.comparison_evidence import retained_evidence

    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(tmp_path / "tier3-output.key"))
    project, run = "1" * 32, "a" * 32
    root = tmp_path / "artifacts" / project / run / "tier3"
    directory = Path(evaluation(output_dir=root / "foreign" if damage == "wrong-skill" else root)["run_dir"])
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
    elif damage == "unsigned-directory":
        from skillevaluator.tier3.output_provenance import GENERATED_OUTPUT_MARKER

        (directory / GENERATED_OUTPUT_MARKER).unlink()
    elif damage == "wrong-revision":
        selection = (run, "b" * 40)
    comparison = retained_evidence(tmp_path, project, [selection, selection], "demo")["comparison"]
    assert comparison["status"] == "unavailable"
    assert comparison["reasons"] and not comparison.get("agents")


def test_scoped_native_history_orders_and_segments_flat_and_nested(tmp_path, monkeypatch, evaluation):
    from studio.comparison_evidence import retained_catalog

    project = "1" * 32
    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(tmp_path / "tier3-output.key"))
    runs = []
    for char, folder, score, threshold in [
        ("a", "", 0.8, 0.6),
        ("b", "demo", 0.2, 0.6),
        ("c", "other", 0.7, 0.6),
        ("d", "demo", 0.5, 0.9),
    ]:
        run = char * 32
        root = tmp_path / "artifacts" / project / run / "tier3" / folder
        assert "error" not in evaluation(char, score, output_dir=root, pass_threshold=threshold)
        runs.insert(0, (run, char * 40))

    def history(agent):
        return retained_catalog(tmp_path, project, runs, "demo", action="history", agent=agent)["rows"]

    rows = history("opencode")
    assert [row["with_skill_score"] for row in rows] == [0.8, 0.2, 0.5]
    assert [row["lift_change"] for row in rows] == [None, -0.6, None]
    assert [row["segment"] for row in rows] == [1, 1, 2]
    assert history("not-recorded") == []


def test_latest_completed_selects_earlier_eligible_different_revision(tmp_path, evaluation, monkeypatch):
    from studio.comparison_evidence import retained_catalog

    from skillevaluator.tier3.output_provenance import GENERATED_OUTPUT_MARKER

    project = "1" * 32
    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(tmp_path / "tier3-output.key"))
    runs = []
    for char, revision, score, threshold in [
        ("a", "a", 0.8, 0.6),
        ("b", "b", 0.5, 0.9),
        ("c", "c", 0.7, 0.6),
        ("d", "c", 0.2, 0.6),
        ("e", "e", 0.9, 0.6),
    ]:
        root = tmp_path / "artifacts" / project / (char * 32) / "tier3"
        result = evaluation(revision, score, output_dir=root, pass_threshold=threshold)
        runs.append((char * 32, revision * 40))
    (Path(result["run_dir"]) / GENERATED_OUTPUT_MARKER).unlink()

    def compare(current, prior):
        return retained_catalog(tmp_path, project, runs, "demo", action="compare", current=current, prior=prior)

    report = compare("latest", "latest")
    assert report["source_studio_run"] == "a" * 32
    assert report["agents"]["opencode"]["metrics"]["accuracy"]["delta"] == -0.6
    assert compare("a" * 32, "latest")["status"] == "unavailable"
    assert compare("d" * 32, "b" * 32)["status"] == "unavailable"
    assert compare("d" * 32, "c" * 32)["identical_skill"]


@pytest.mark.parametrize(
    ("nested", "damage", "status"), [(False, "missing", "incomplete"), (True, "malformed", "corrupt")]
)
def test_history_explains_unfinished_native_results_without_a_change(
    tmp_path, evaluation, monkeypatch, *, nested, damage, status
):
    from studio.comparison_evidence import retained_catalog

    project, run = "1" * 32, "a" * 32
    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(tmp_path / "tier3-output.key"))
    root = tmp_path / "artifacts" / project / run / "tier3"
    path = Path(evaluation(output_dir=root / "demo" if nested else root)["run_dir"]) / "result.json"
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("{")
    args = tmp_path, project, [(run, "a" * 40)], "demo"
    (row,) = retained_catalog(*args, action="history")["rows"]
    assert row["status"] == status and row["lift_delta"] is None and row["lift_reasons"]
    assert retained_catalog(*args, action="compare", current="latest", prior="latest")["status"] == "unavailable"
