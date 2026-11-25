"use client";

import { CIDocument, useCIAction } from "@/components/ci-document";
import type { Project } from "@/lib/studio-api";

interface CI {
  project: Project;
  gitlab: boolean;
  notice?: string;
  compare?: string;
  scan_runs?: string;
  workflow?: string;
  digest?: string;
  demo?: string;
  demo_target?: string;
  demo_branch?: string;
  demo_digest?: string;
}

const RepositoryCI = ({ data, path }: { data: CI; path: string }) => {
  const { result, problem, busy, onSubmit } = useCIAction<CI>(path);
  const { project, gitlab } = data;
  const view = result ?? data;

  const base = (
    <>
      <input type="hidden" name="branch" value={project.branch} />
      <input type="hidden" name="revision" value={project.revision} />
    </>
  );

  return (
    <>
      <a href={`/projects/${project.id}`}>{project.name}</a>
      <h1>Repository CI</h1>
      {(view.notice ?? "") !== "" && !problem && <output>{view.notice}</output>}
      {problem && <p role="alert">{problem}</p>}
      <p>
        <a href={`${path}/advanced`}>Advanced CI setup</a> · All tiers, GitLab,
        hosted reports, live status and setup requests.
      </p>
      {gitlab ? (
        <p>GitLab supports all-tier CI only.</p>
      ) : (
        <>
          <p>
            GitHub Actions · Tier 1 checks only. Changes target {project.branch}{" "}
            at {project.revision}.
          </p>
          <form onSubmit={onSubmit}>
            {base}
            <button disabled={busy} name="action" value="status" type="submit">
              Check status
            </button>
          </form>
          {(view.scan_runs ?? "") !== "" && (
            <a href={view.scan_runs}>Inspect scan runs on Git host</a>
          )}
          <h2>Set up checks</h2>
          <p>
            Scan the connected skill folder: {project.folder}. Publishing may
            start a CI run.
          </p>
          <form onSubmit={onSubmit}>
            {base}
            <label>
              Minimum score{" "}
              <input
                name="score"
                type="number"
                min={0}
                max={100}
                defaultValue={70}
                required
              />
            </label>
            <label>
              Scan scope{" "}
              <select name="scope">
                <option value="auto">Changed skills</option>
                <option value="all">All selected skills</option>
              </select>
            </label>
            <label>
              Release channel{" "}
              <select name="channel">
                <option value="pinned">Bundled pinned release</option>
                <option value="stable">Follow stable</option>
              </select>
            </label>
            <button type="submit" name="action" value="review" disabled={busy}>
              Review setup
            </button>
            {(view.workflow ?? "") !== "" && (
              <>
                <h3>.github/workflows/skill-checks.yml</h3>
                <section aria-label="Generated workflow">
                  <pre>{view.workflow}</pre>
                </section>
                <input type="hidden" name="approval" value={view.digest} />
                <button
                  disabled={busy}
                  type="submit"
                  name="action"
                  value="publish"
                >
                  Publish reviewed workflow
                </button>
              </>
            )}
          </form>
        </>
      )}
      <h2>Try a demo pull request</h2>
      <p>
        After setup on the default branch, review a comment-only skill change.
        Create a review request on a separate branch with the project
        credential.
      </p>
      <form onSubmit={onSubmit}>
        {base}
        <button
          type="submit"
          name="action"
          value="review"
          data-suffix="/demo"
          disabled={busy}
        >
          Review demo
        </button>
        {(view.demo ?? "") !== "" && (
          <>
            <section aria-label="Demo change">
              <pre>{view.demo}</pre>
            </section>
            <p>
              New branch: {view.demo_branch} · File: {view.demo_target}
            </p>
            <input type="hidden" name="approval" value={view.demo_digest} />
            <button
              type="submit"
              disabled={busy}
              name="action"
              value="request"
              data-suffix="/demo"
            >
              Create reviewed PR/MR
            </button>
            {!gitlab && (
              <button
                type="submit"
                disabled={busy}
                name="action"
                value="publish"
                data-suffix="/demo"
              >
                Publish demo branch
              </button>
            )}
          </>
        )}
      </form>
      {(view.compare ?? "") !== "" && (
        <a href={view.compare}>Open pull request for review</a>
      )}
    </>
  );
};

/** @returns Revision-bound repository automation. */
export default function Page() {
  return <CIDocument screen={RepositoryCI} />;
}
