/* oxlint-disable shadcn/no-unknown-classes -- The Studio stylesheet owns the shared panel class. */
"use client";

import { QueueForm, RunDocument } from "@/components/run-workspace/document";
import type { Project } from "@/lib/studio-api";

interface History {
  project: Project;
  actions: Record<string, string>;
  runs: {
    id: string;
    sha: string;
    kind: string;
    status: string;
    created: string;
  }[];
}

const history = ({ project, runs, actions }: History) => {
  const base = `/projects/${project.id}`;

  return (
    <>
      <h1>Evaluation runs</h1>
      <section className="panel">
        <h2>Keyless Tier 1</h2>
        <p>
          Check schema and Unicode in the selected skill. No model, external
          scanner or repository script runs.
        </p>
        <QueueForm path={`${base}/runs`} button="Queue static checks">
          <label>
            Commit SHA
            <input name="sha" defaultValue={project.revision} required />
          </label>
          <label>
            Static checks
            <select name="checks">
              <option value="both">Schema and Unicode</option>
              <option value="schema">Schema only</option>
              <option value="unicode">Unicode only</option>
            </select>
          </label>
        </QueueForm>
      </section>
      <details>
        <summary>Expert checks and validation</summary>
        <ul>
          {Object.entries(actions).map(([key, label]) => (
            <li key={key}>
              <a href={`${base}/expert/${key}`}>{label}</a>
            </li>
          ))}
        </ul>
      </details>
      <section id="history">
        <h2>Run history</h2>
        {runs.length === 0 && (
          <p>
            <b>No runs yet.</b> Queue a check to see its results here.
          </p>
        )}
        {runs.map((run) => (
          <article key={run.id}>
            <a href={`${base}/runs/${run.id}`}>{run.sha}</a>
            <p>
              {run.kind} · {run.status} · {run.created} UTC
            </p>
          </article>
        ))}
      </section>
    </>
  );
};

/** @returns The author-facing history document. */
export default function Page() {
  return <RunDocument render={history} />;
}
