import subprocess

# ruff: noqa: F811 -- pytest discovers these shared fixtures by name
from test_workspace import before_push, connect, page, playwright, private_remote, running  # noqa: F401


def publish_from_seed(tmp_path, branch, content):
    seed = tmp_path / "seed"
    (seed / "skills/triage/SKILL.md").write_text(content)
    subprocess.run(
        ["git", "-c", "user.name=peer", "-c", "user.email=p@example.org", "commit", "-am", "Peer edit"],
        cwd=seed,
        check=True,
    )
    subprocess.run(
        ["git", "push", str(tmp_path / "server/handbook.git"), "HEAD:refs/heads/" + branch], cwd=seed, check=True
    )


def test_create_from_chosen_branch_then_switch(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    publish_from_seed(tmp_path, "candidate", "# Candidate\n")
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        assert not page.get_by_role("alert").count(), page.locator("body").inner_text()
        page.get_by_role("link", name="Edit skill").click(timeout=2000)
        page.get_by_label("Start from branch").select_option(label="candidate")
        page.get_by_label("New branch name").fill("review/v2")
        page.get_by_role("button", name="Create branch").click()
        playwright.expect(page.get_by_role("heading", name="Edit review/v2")).to_be_visible()
        assert subprocess.check_output(["git", "rev-parse", "review/v2"], cwd=remote) == subprocess.check_output(
            ["git", "rev-parse", "candidate"], cwd=remote
        )
        page.get_by_label("Open branch").select_option(label="main")
        page.get_by_role("button", name="Switch branch").click()
        playwright.expect(page.get_by_role("heading", name="Edit main")).to_be_visible()


def test_preview_and_publish_skill(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Edit skill").click()
        skill = page.get_by_label("SKILL.md")
        playwright.expect(skill).to_have_value("# Triage\n", timeout=1500)
        skill.fill("# Triage")
        page.get_by_role("button", name="Preview changes").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("No newline", timeout=1500)
        skill.fill("# Review\n\nAssess the evidence.\n")
        page.get_by_role("button", name="Preview changes").click()
        playwright.expect(page.get_by_label("Change preview")).to_contain_text("-# Triage")
        assert subprocess.check_output(["git", "show", "main:skills/triage/SKILL.md"], cwd=remote) == b"# Triage\n"
        page.get_by_role("button", name="Save and push").click()
        playwright.expect(page.get_by_role("status")).to_contain_text("Pushed")
        assert subprocess.check_output(["git", "show", "main:skills/triage/SKILL.md"], cwd=remote) == (
            b"# Review\n\nAssess the evidence.\n"
        )


def test_stale_remote_preserves_draft_and_branch_point(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Edit skill").click()
        stale = page.context.browser.new_page()
        stale.goto(page.url)
        publish_from_seed(tmp_path, "main", "# Collaborator\n")
        page.get_by_label("SKILL.md").fill("My draft")
        page.get_by_role("button", name="Save and push").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("remote branch changed")
        playwright.expect(page.get_by_label("SKILL.md")).to_have_value("My draft")
        assert (
            subprocess.check_output(["git", "show", "main:skills/triage/SKILL.md"], cwd=remote) == b"# Collaborator\n"
        )
        stale.get_by_label("New branch name").fill("wrong-base")
        stale.get_by_role("button", name="Create branch").click()
        playwright.expect(stale.get_by_role("alert")).to_contain_text("source branch changed", timeout=1500)
        assert subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/wrong-base"], cwd=remote
        ).returncode
        page.get_by_role("button", name="Switch branch").click()
        playwright.expect(page.get_by_label("SKILL.md")).to_have_value("# Collaborator\n")


def test_branch_deleted_during_push_is_not_recreated(page, tmp_path, private_remote, before_push):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Edit skill").click()
        before_push.append(
            lambda: subprocess.run(["git", "update-ref", "-d", "refs/heads/main"], cwd=remote, check=True)
        )
        page.get_by_label("SKILL.md").fill("Retain my draft")
        page.get_by_role("button", name="Save and push").click()
        playwright.expect(page.get_by_role("alert")).to_contain_text("Push was not confirmed", timeout=1500)
        playwright.expect(page.get_by_label("SKILL.md")).to_have_value("Retain my draft")
        assert subprocess.run(["git", "show-ref", "--quiet", "--verify", "refs/heads/main"], cwd=remote).returncode


def test_simultaneous_editor_saves_publish_only_one_revision(page, tmp_path, private_remote):
    remote = tmp_path / "server/handbook.git"
    with running(tmp_path / "volume") as base:
        page.goto(base)
        connect(page, *private_remote, skill="skills/triage")
        page.get_by_role("link", name="Edit skill").click()
        responses = page.get_by_label("SKILL.md").evaluate("""async field => {
          const form = field.form;
          return Promise.all(['First draft', 'Second draft'].map(async draft => {
            const data = new FormData(form);
            data.set('text', draft);
            data.set('action', 'save');
            const response = await fetch(form.getAttribute('action'), {method: 'POST', body: data});
            return response.status;
          }));
        }""")
        assert sorted(responses) == [200, 409]
        winner = ["First draft", "Second draft"][responses.index(200)]
        assert subprocess.check_output(["git", "show", "main:skills/triage/SKILL.md"], cwd=remote).decode() == winner
        assert subprocess.check_output(["git", "rev-list", "--count", "main"], cwd=remote).strip() == b"2"


def test_restart_completes_published_save_without_overwriting_dirty_work(tmp_path, private_remote):
    import os
    import sys

    from studio.workspace import Workspace

    data = tmp_path / "volume"
    ws = Workspace(data)
    url, token = private_remote
    p = ws.get(ws.connect(url, "skills/triage", "author", token))
    # Terminate the real writer after its authenticated push, before checkout.
    worker = """
import os, sys
from studio.workspace import Workspace
from studio.editing import commit_changes
ws = Workspace(sys.argv[1]); p = ws.projects()[0]; git = ws.git
def interrupted(p, args, **kwargs):
    if args[0] == 'checkout': os._exit(72)
    return git(p, args, **kwargs)
ws.git = interrupted
commit_changes(ws, p, {'SKILL.md': b'published'}, 'publish')
"""
    assert subprocess.run([sys.executable, "-c", worker, str(data)], env=os.environ.copy()).returncode == 72
    skill = ws.checkout(p) / p.folder / "SKILL.md"
    skill.write_text("unrelated local work")
    assert Workspace(data).get(p.id) == p
    assert skill.read_text() == "unrelated local work"
    skill.write_text("# Triage\n")
    reopened = Workspace(data).get(p.id)
    tip = subprocess.check_output(["git", "rev-parse", "main"], cwd=tmp_path / "server/handbook.git", text=True).strip()
    assert reopened.revision == tip != p.revision
    assert skill.read_text() == "published"


def test_restart_records_created_branch_only_when_remote_still_matches(tmp_path, private_remote):
    import sys

    from studio.workspace import Workspace

    data = tmp_path / "volume"
    ws = Workspace(data)
    url, token = private_remote
    p = ws.get(ws.connect(url, "skills/triage", "author", token))
    worker = """
import os, sys
from studio.workspace import Workspace
from studio.editing import open_branch
ws = Workspace(sys.argv[1]); p = ws.projects()[0]; git = ws.git
def interrupted(p, args, **kwargs):
    result = git(p, args, **kwargs)
    if args[0] == 'checkout': os._exit(73)
    return result
ws.git = interrupted
open_branch(ws, p, p.branch, p.revision, 'review/topic')
"""
    assert subprocess.run([sys.executable, "-c", worker, str(data)]).returncode == 73
    remote = tmp_path / "server/handbook.git"
    publish_from_seed(tmp_path, "review/topic", "peer edit")
    assert Workspace(data).get(p.id) == p
    assert subprocess.check_output(["git", "show", "review/topic:skills/triage/SKILL.md"], cwd=remote) == b"peer edit"
    subprocess.run(["git", "update-ref", "refs/heads/review/topic", p.revision], cwd=remote, check=True)
    assert Workspace(data).get(p.id).branch == "review/topic"
