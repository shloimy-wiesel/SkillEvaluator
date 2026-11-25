import sqlite3
import subprocess
from contextlib import closing

from test_editing import publish_from_seed
from test_workspace import connect, playwright, running

pytest_plugins = ("test_workspace", "test_version_comparison")


def test_compare_branch_to_commit_without_switching(page, tmp_path, private_remote):
    publish_from_seed(tmp_path, "candidate", "# Candidate\n")
    remote = tmp_path / "server/handbook.git"
    main = subprocess.check_output(["git", "rev-parse", "main"], cwd=remote, text=True).strip()
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Compare revisions").click(timeout=1500)
        page.get_by_label("Prior revision").fill(main)
        page.get_by_label("Current revision").fill("candidate")
        page.get_by_role("button", name="Compare revisions").click()
        playwright.expect(page.get_by_label("Prior source")).to_have_text("# Triage\n")
        playwright.expect(page.get_by_label("Current source")).to_have_text("# Candidate\n")
        playwright.expect(page.get_by_label("Current source").locator("ins")).to_have_text("# Candidate\n")
        playwright.expect(page.get_by_text("No retained run for this revision.")).to_have_count(2)
        checkout = next((tmp_path / "volume/projects").iterdir())
        assert subprocess.check_output(["git", "branch", "--show-current"], cwd=checkout).strip() == b"main"
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout).decode().strip() == main


def test_author_compares_paired_evidence_then_inspects_policy_mismatch(
    page, tmp_path, private_remote, evaluation, monkeypatch
):
    publish_from_seed(tmp_path, "candidate", "# Candidate\n")
    volume = tmp_path / "volume"
    remote = tmp_path / "server/handbook.git"
    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(volume / "tier3-output.key"))
    with running(volume) as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Compare revisions").click()
        project = page.url.split("/")[-2]
        for branch, char, score, threshold in (
            ("main", "a", 0.8, 0.6),
            ("candidate", "b", 0.2, 0.6),
            ("candidate", "c", 0.5, 0.9),
        ):
            sha = subprocess.check_output(["git", "rev-parse", branch], cwd=remote, text=True).strip()
            run = char * 32
            result = evaluation(
                char,
                score,
                pass_threshold=threshold,
                evaluated_source={"commit": sha},
                output_dir=volume / "artifacts" / project / run / "tier3",
            )
            assert "error" not in result
            with closing(sqlite3.connect(volume / "studio.sqlite3")) as db, db:
                db.execute(
                    "INSERT INTO runs(id,project_id,sha,folder,kind,options,status,report) VALUES(?,?,?,?,?,?,?,?)",
                    (run, project, sha, "skills/triage", "tier3-live-v1", "{}", "neutral", '{"results":[]}'),
                )
        page.get_by_label("Current revision").fill("candidate")
        page.get_by_role("button", name="Compare revisions").click()
        playwright.expect(page.get_by_label("Version comparison")).to_contain_text(
            "attempt policy changed", timeout=3000
        )
        page.get_by_label("Current run", exact=True).select_option("b" * 32)
        page.get_by_role("button", name="Compare selected runs").click()
        playwright.expect(page.get_by_label("Version comparison")).to_contain_text("\N{MINUS SIGN}0.60")
        playwright.expect(page.get_by_label("Current arm scores")).to_contain_text("\N{MINUS SIGN}0.30")
        forged = page.request.get(page.url.replace("current_run=" + "b" * 32, "current_run=" + "a" * 32))
        assert forged.status == 422 and "Choose a run retained for the selected revision" in forged.text()


def test_download_scoped_native_trends_and_version_report(page, tmp_path, private_remote, evaluation, monkeypatch):
    import csv
    import json

    volume = tmp_path / "volume"
    monkeypatch.setenv("SKILLEVALUATOR_OUTPUT_PROVENANCE_KEY_FILE", str(volume / "tier3-output.key"))
    with running(volume) as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Skill lift history").click(timeout=2000)
        project = page.url.split("/")[-3]
        for char, score, folder in [("a", 0.8, "triage"), ("b", 0.2, ""), ("c", 0.7, "elsewhere")]:
            run = char * 32
            assert "error" not in evaluation(
                char, score, output_dir=volume / "artifacts" / project / run / "tier3" / folder
            )
            with closing(sqlite3.connect(volume / "studio.sqlite3")) as db, db:
                db.execute(
                    "INSERT INTO runs(id,project_id,sha,folder,kind,options,status,report) VALUES(?,?,?,?,?,?,?,?)",
                    (run, project, char * 40, "skills/triage", "tier3-live-v1", "{}", "neutral", "{}"),
                )
        page.reload()

        def download(label):
            with page.expect_download() as waiting:
                page.get_by_role("link", name=label, exact=True).click()
            return waiting.value.path().read_text()

        assert [r["lift_change"] for r in json.loads(download("History JSON"))["rows"]] == [None, -0.6]
        assert len(list(csv.DictReader(download("History CSV").splitlines()))) == 2
        assert "Skill Lift history" in download("History Markdown")
        page.get_by_label("Results scope").select_option(["a" * 32])
        page.get_by_role("button", name="Inspect results").click()
        assert len(json.loads(download("History JSON"))["rows"]) == 1
        assert json.loads(download("Comparison JSON"))["status"] == "unavailable"
        page.get_by_label("Results scope").select_option([])
        page.get_by_label("Agent filter").fill("missing")
        page.get_by_label("Current evaluation").select_option("b" * 32)
        page.get_by_label("Prior evaluation").select_option("a" * 32)
        page.get_by_role("button", name="Inspect results").click()
        assert json.loads(download("History JSON"))["rows"] == []
        assert json.loads(download("Comparison JSON"))["agents"]["opencode"]["delta"] == -0.6
        assert page.request.get(page.url + "&scope=" + "f" * 32).status == 422
