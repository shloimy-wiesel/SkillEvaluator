"use client";

import { Fragment } from "react";

import { CIDocument, useCIAction } from "@/components/ci-document";
import {
  HostOptions,
  ScanOptions,
  RunnerOptions,
  PublicationMode,
} from "@/components/ci-options";
import type { Defaults } from "@/components/ci-options";
import type { Project } from "@/lib/studio-api";

interface Advanced {
  project: Project;
  form: Defaults;
  releases: string[];
  roots: string[];
  notice?: string;
  jobs?: { name: string; status: string; url: string }[];
  pipelines: { id: string; status: string }[];
  selected?: string;
  result?: {
    plan: object;
    files: Record<string, string>;
    manual_merge: string;
  };
  digest?: string;
}

// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
const Jobs = ({ view }: { view: Advanced }) =>
  view.jobs ? (
    <>
      <h2>Jobs for pipeline #{view.selected}</h2>
      {view.jobs.length ? (
        <table aria-label="Pipeline jobs">
          <thead>
            <tr>
              <th>Job</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {view.jobs.map((job) => (
              <tr key={job.url}>
                <td>
                  <a href={job.url}>{job.name}</a>
                </td>
                <td>{job.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>No jobs reported for this pipeline.</p>
      )}
      {view.jobs.length === 100 && <p>Showing the first 100 jobs.</p>}
    </>
  ) : null;

// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
const Reviewed = ({ view, busy }: { view: Advanced; busy: boolean }) => {
  if (!view.result) {
    return null;
  }

  return (
    <>
      <h2>Review {view.form.mode} setup</h2>
      <pre>{JSON.stringify(view.result.plan, null, 2)}</pre>
      {Object.entries(view.result.files).map(([path, text]) => (
        <Fragment key={path}>
          <h3>{path}</h3>
          <section aria-label={path}>
            <pre>{text}</pre>
          </section>
        </Fragment>
      ))}
      <input name="approval" type="hidden" value={view.digest} />
      {view.result.manual_merge && (
        <>
          <p role="alert">
            An existing GitLab pipeline requires a manual merge.
          </p>
          <pre>{view.result.manual_merge}</pre>
        </>
      )}
      {!view.result.manual_merge && view.form.mode !== "preview" && (
        <button type="submit" name="action" value="apply" disabled={busy}>
          Apply reviewed setup
        </button>
      )}
      <button type="submit" name="action" value="receipt" disabled={busy}>
        Download reviewed plan
      </button>
    </>
  );
};

const AdvancedCI = ({ data, path }: { data: Advanced; path: string }) => {
  const { result, problem, busy, onSubmit } = useCIAction<Advanced>(path);
  const view = result ?? data;
  const { project, form } = data;

  return (
    <>
      <a href={`/projects/${project.id}/ci`}>Repository CI</a>
      <h1>Advanced CI setup</h1>
      <p>
        {project.remote} · {project.branch} at {project.revision}
      </p>
      {(view.notice ?? "") !== "" && !problem && (
        <output>
          <pre>{view.notice}</pre>
        </output>
      )}
      {problem && <p role="alert">{problem}</p>}
      <Jobs view={view} />
      <form onSubmit={onSubmit}>
        <input type="hidden" name="branch" value={project.branch} />
        <input type="hidden" name="revision" value={project.revision} />
        <HostOptions form={form} />
        <p>
          Tier 1 alone requires GitHub. Tier 1 blocks; Tiers 2 and 3 are
          advisory and require CI credentials, protected runners and datasets.
        </p>
        {view.pipelines.length > 0 && (
          <label>
            Pipeline for this revision{" "}
            <select
              key={view.selected}
              defaultValue={view.selected}
              name="pipeline_id"
            >
              {view.pipelines.map((p) => (
                <option key={p.id} value={p.id}>
                  #{p.id} · {p.status}
                </option>
              ))}
            </select>
          </label>
        )}
        {view.pipelines.length === 20 && (
          <p>Showing the latest 20 pipelines.</p>
        )}
        <button disabled={busy} type="submit" name="action" value="status">
          Read live status
        </button>
        <p>
          Discovered roots: {data.roots.join(", ")} · Leave blank for CLI
          defaults.
        </p>
        <ScanOptions form={form} releases={data.releases} />
        <p>
          Auto follows the CLI: hosted Pages for Tier 1; retained artifacts and
          feedback for all tiers.
        </p>
        <fieldset>
          <legend>All-tier configuration</legend>
          <RunnerOptions form={form} />
        </fieldset>
        <p>
          Save commits the files only. PR/MR requires a host token with API and
          workflow write access. GitHub Tier 1 PR setup requires admin access
          and may enable Actions, Pages, report history and a deployment
          environment. Private reports require verified private Pages. GitLab
          feedback needs a protected default branch, protected environment and
          scoped SKILLEVALUATOR_GITLAB_TOKEN. Before GitLab 18.4 or when the
          version is unknown, configure SKILLEVALUATOR_GITLAB_READ_TOKEN
          (Reporter/read_api).
        </p>
        <PublicationMode form={form} />
        <button type="submit" name="action" value="review" disabled={busy}>
          Review files
        </button>
        <Reviewed view={view} busy={busy} />
      </form>
    </>
  );
};

/** @returns Advanced CI review, status and publication. */
export default function Page() {
  return <CIDocument screen={AdvancedCI} />;
}
