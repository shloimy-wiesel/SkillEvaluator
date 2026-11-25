# Revision-bound editing

Use `studio.editing` for authoring features. A `Project` from `Workspace.get`
is the expected snapshot, including **both branch and commit**. Two branches can
point to the same SHA. Put both values in the form when displaying the draft.

```python
from studio.editing import commit_changes, read_file, require_base

# GET: keep this exact project's branch/revision alongside the displayed bytes.
p = ws.get(project_id)  # return HTTP 404 if missing
saved = read_file(ws, p, "evals/dataset.json")

# POST: reject stale forms instead of substituting the newest checkout.
p = require_base(ws.get(project_id), submitted_branch, submitted_revision)
sha = commit_changes(ws, p, {
    "evals/dataset.json": validated_json_bytes,
    "evals/old-dataset.json": None,
}, "Update evaluation dataset")
```

- `read_file(ws, p, name, *, repo_root=False) -> bytes | None` reads exact
  committed bytes, returning `None` if absent. This is an **active editor**
  contract: the saved snapshot and clean checkout must still match `p`.
  It does not contact the remote or serve historical run artifacts.
- `commit_changes(ws, p, changes, message, *, repo_root=False) -> str`
  adds/replaces paths containing `bytes` and deletes paths mapped to `None`
  in one commit. It preserves existing executable modes; new files are
  regular non-executable files. Unchanged batches report a `WorkspaceError`.
  The result is the pushed commit SHA; fetch a fresh `Project` after success.
- Paths are relative POSIX file names under the selected skill directory.
  Scaffolding adapters can pass `repo_root=True` for **server-selected**
  repository paths. Feature code owns content validation, allowed paths, and
  which templates may write configuration. Never accept host paths, commands,
  arbitrary workflow contents, or the root-scope switch from an HTTP form.
  Git internals, traversal, symlinks and submodule paths are rejected.
- `branches(ws, p)` returns `{remote_branch: sha}`. `open_branch(ws, p,
  source, expected_source, new=None)` checks the displayed source SHA before
  switching; a supplied `new` creates and publishes a branch from that SHA.
  Switching to the current branch refreshes it after a collaborator's push.
- Catch `Conflict` (a `WorkspaceError`) first: respond with 409 and preserve
  the draft **and original base**. Present other `WorkspaceError` messages as
  author-facing validation or access errors. If push confirmation is lost,
  inspect the remote before retrying.

Reads, switches, and commits share a per-project lock (one Studio process per
volume). Saves build Git objects with a private temporary index, leaving the
checkout unchanged on remote rejection. Pushes are ordinary non-force pushes:
the application-owned `studio/git-hooks/pre-push` checks the advertised old
OID, including zero for creation, and the receive server verifies it again
when updating the ref. Ship the hook executable. Studio updates checkout
metadata after the local checkout succeeds.

Trusted generators may pass `executable={path: bool}` to `commit_changes` for
files whose generated mode is part of the template contract. Omitted paths
retain the usual mode behavior. Never source this mapping from form fields.

`commit_changes(..., new_branch=server_selected_name)` publishes the new
commit directly to a previously absent branch with the same push guard,
leaving the selected branch and workspace metadata unchanged. Repository CI
uses this for the reviewed demo change.

**Compare revisions** is read-only: it resolves branch names already in the
project clone or a full local commit SHA, then compares Git objects under the
selected skill folder. It does not refresh the remote, switch branches, stage
files, or change the current draft. The preview shows up to 20 changed files,
32 KiB of text per side, and highlights changed lines in smaller files.
Binary, linked, deleted and empty files have explicit preview states.
