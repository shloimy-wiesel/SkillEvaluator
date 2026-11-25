# Studio extension contract

From the repository root, install in a Python 3.12+ venv:

```sh
pip install -e . -r studio/requirements.txt
STUDIO_DATA_DIR="$PWD/.studio-data" uvicorn studio.app:create_app --factory
```

`create_app(data_dir=..., routers=())` constructs an independent app. There
is no import-time global connection. Use one process per volume. Tests can
pass extra `APIRouter` instances. For production, import the new router in
`studio/extensions.py` and append it to `ROUTERS`. Register `(link label,
route name)` in `PROJECT_LINKS` for project overview navigation. A named
project entry route must take `project_id`. Prefer a feature-owned prefix
such as `/projects/{project_id}/datasets` and unique route names.

Place the route name in the appropriate ordered task in `studio/navigation.py`
to surface it under Authoring, Evaluation or Results. Unclassified registered
entries remain reachable under Project tools. `base.html` provides a project
breadcrumb when the template context contains `project`.

```python
router = APIRouter(prefix="/projects/{project_id}/datasets")


@router.get("", name="datasets_index")
def index(request: Request, project_id: str):
    project = request.app.state.workspace.get(project_id)
    if project is None:
        raise HTTPException(404, "Unknown project")
    return request.app.state.templates.TemplateResponse(
        request=request, name="datasets/index.html", context={"project": project}
    )
```

Put Jinja files under `studio/templates/<feature>/`; extend `base.html` and
override `title` and `content`. Use labelled forms, POST for mutations and
redirect after a successful save. Do not introduce template-level secrets.

* `request.app.state.workspace` exposes `data_dir`, `db_path`, `projects()`,
  `get(id) -> Project | None`, `checkout(project) -> Path`, and
  `git(project, args, authenticated=False) -> str`. The Git helper takes only
  **server-constructed argv**, scopes authorization to the saved remote and
  raises `WorkspaceError` with a displayable diagnostic. It is not a public
  command runner. Use the canonical `project.remote` for network operations.
* `Project` is an immutable snapshot (`id`, `name`, `remote`, `folder`,
  `branch`, `revision`); the latter two are persisted checkout metadata.
  Projects live at `projects/<opaque id>` inside the volume. Folder paths
  are relative POSIX paths; `.` is valid. Recheck containment, `.git` and
  symlinks on every later read/write and after changing branches. Do not
  assume a repo stayed unchanged since connect.
* A branch/editor slice should serialize mutations per project, validate ref
  names, compare the expected base SHA to local and remote state, use ordinary
  non-force pushes and report stale edits. Update checkout metadata only to
  reflect successful Git operations. A run slice must pin a SHA and isolate
  run workspaces; never run in a mutable author checkout.
* SQLite is `studio.sqlite3`. Own feature tables and additive migrations;
  open short-lived connections per operation and close them. Keep long Git or
  model calls outside write transactions. Keep artifacts under `data_dir`.
  Persist sensitive fields only as encrypted blobs; the workspace's Fernet
  cipher uses the volume's `credential.key`. Do not log secrets or raw Git
  stderr. Do not store host paths or accept executable config through forms.

## Run the browser journey

See [RUNS.md](RUNS.md) for the queue, evaluator adapter, rerun and artifact contracts.

```sh
pip install pytest playwright==1.65.2
playwright install chromium    # or use an installed google-chrome on PATH
python -m pytest -q tests/studio
```

The suite uses a disposable bare Git repository served over authenticated
HTTPS, a test-local CA, real Chromium and successive ASGI servers using the
same volume. It needs a Git executable, but no provider keys or external Git host.
To verify actual container replacement on Linux, build the image from the
quickstart and run `STUDIO_TEST_IMAGE=skillevaluator-studio python -m pytest
-q tests/studio -k reopens`. This creates two successive containers sharing
a temporary named volume and removes them and the volume after the journey.
