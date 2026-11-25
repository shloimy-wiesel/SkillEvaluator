# Results and review

Start from **Compare revisions**, **Skill lift history**, or **Results dashboard** in a project. A terminal live run links to **Review artifacts and feedback**.

- Revision comparison selects a branch or full commit on each side. Source changes are independent of evaluation availability. Select retained runs to compare baseline lift within a revision and with-skill change between revisions; incompatible measurements include reasons.
- History, dashboard, and trajectory filters live in the URL. Filter first, then use the download link to export the same selection. Dashboard imports accept canonical JSON up to 1 MiB; removing an import does not remove a run.
- Review opens files by inventory key. **Download redacted text** saves the displayed artifact preview, including for a retained HTML report. **View report** exposes expandable text sections. When necessary Studio rebuilds the report in temporary storage.
- Questions use the project's chat provider and the selected run's compact evidence. Saved answers remain available after reopening the project.

## HTTP and fixture verification (#31)

The four browser views read `/api/v1` + their canonical project paths. Uploads POST bounded JSON to `/results/uploads`; removal POSTs to `/results/uploads/{source}/remove`; feedback POSTs `{"question":"…"}` to `/results/{run_id}/feedback`, each relative to the versioned project URL. Exports remain attachments at the browser URLs.

Chromium against the original `8305e1b` export connected to a private HTTPS Git fixture and timed out waiting for the comparison JSON response. Two further failing journeys demonstrated the missing redacted artifact attachment and an unescaped, unredacted model string in the native history CSV. The regression tests check actual downloaded bytes and HTTP status, including cross-project and invalid inventory requests.

```sh
(cd studio/frontend && corepack pnpm install --offline --frozen-lockfile && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm build --force)
python -m pytest -q tests/studio/test_review.py tests/studio/test_comparison.py tests/studio/test_comparison_engine.py
```

These tests use a real ASGI server, Chromium, private HTTPS Git, SQLite and native evidence readers. Trial outputs and chat provider responses are fixtures; the Bedrock check exercises the worker up to a substituted SDK transport.

On Python 3.13.11, Chrome 131.0.6778.108, and Node 24.18.0, all 30 tests passed at `14374f9`. After `0c68131` added invalid-revision recovery, all four comparison journeys passed again, including correcting the revision in place. Workspace lint, typecheck, and static export passed.
