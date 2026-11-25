/* oxlint-disable next/no-html-link-for-pages, react/todo, react-doctor/no-array-index-as-key -- Immutable ordered evidence may contain duplicates. ASGI owns navigation and styles; async forms release busy state in finally. */
"use client";

import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

import { EvidencePage, Select } from "./common";
import { strings, withParam } from "./model";

type Turn = [string, string];

interface Data {
  project: Project;
  run: { id: string; sha: string; folder: string };
  q: string;
  file: string;
  files: Record<string, string>;
  preview: string | null;
  sections: [string, string][] | null;
  steps: object[] | null;
  sources: string[];
  source: string;
  harbor: boolean;
  jobs: string[];
  job: string;
  comparison: string | null;
  conversation: Turn[];
  can_ask: boolean;
}

const Feedback = ({ data: d }: { data: Data }) => {
  const [turns, setTurns] = useState(d.conversation);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const question = new FormData(form).get("question");
    setBusy(true);
    setProblem("");

    try {
      const result = await api<{ conversation: Turn[] }>(
        `/projects/${d.project.id}/results/${d.run.id}/feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
        }
      );

      setTurns(result.conversation);
      form.reset();
    } catch (error) {
      setProblem(messageOf(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h2>Run feedback</h2>
      <section aria-label="Conversation" aria-live="polite">
        {turns.map(([q, a], i) => (
          <article key={i}>
            <p>
              <strong>You:</strong> {q}
            </p>
            <p>
              <strong>Assistant:</strong> {a}
            </p>
          </article>
        ))}
      </section>
      {d.can_ask ? (
        <form
          onSubmit={(e) => {
            void submit(e);
          }}
        >
          <p>
            Send this question, conversation and compact run evidence to your
            project’s chat provider.
          </p>
          <label>
            Question
            <textarea name="question" maxLength={4000} required />
          </label>
          <button type="submit" disabled={busy}>
            Ask about this run
          </button>
        </form>
      ) : (
        <p>No canonical agent evidence for feedback.</p>
      )}
      {problem && <p role="alert">{problem}</p>}
    </>
  );
};

// oxlint-disable-next-line sonarjs/function-name -- React component.
const JobFields = ({ data: d }: { data: Data }) =>
  d.harbor ? (
    <>
      <input type="hidden" name="harbor" value="true" />
      <input type="hidden" name="job" value={d.job} />
    </>
  ) : null;

const Inventory = ({ data: d }: { data: Data }) => (
  <>
    {d.harbor && (
      <form>
        <input type="hidden" name="harbor" value="true" />
        <Select
          name="job"
          label="Harbor job"
          value={d.job}
          options={[
            { value: "", label: "All retained jobs" },
            ...strings(d.jobs),
          ]}
        />
        <button type="submit">Open job</button>
      </form>
    )}
    <form>
      <JobFields data={d} />
      <label>
        File filter
        <input name="q" defaultValue={d.q} />
      </label>
      <button type="submit">Filter files</button>
    </form>
    <ul>
      {Object.entries(d.files).map(([id, label]) => (
        <li key={id}>
          <a href={withParam("file", id)}>{label}</a>
        </li>
      ))}
    </ul>
    {!Object.keys(d.files).length && <p>No matching retained files.</p>}
    {d.steps && (
      <>
        <form>
          <input type="hidden" name="file" value={d.file} />
          <JobFields data={d} />
          <input type="hidden" name="q" value={d.q} />
          <Select
            name="source"
            label="Step source"
            value={d.source}
            options={[
              { value: "", label: "All sources" },
              ...strings(d.sources),
            ]}
          />
          <button type="submit">Show steps</button>
        </form>
        <ol aria-label="Trajectory steps">
          {d.steps.map((s, i) => (
            <li key={i}>
              <pre>{JSON.stringify(s, null, 2)}</pre>
            </li>
          ))}
        </ol>
      </>
    )}
    {d.sections && (
      <section aria-label="Artifact preview">
        <h2>Report sections</h2>
        {d.sections.map(([title, body], i) => (
          <details key={i}>
            <summary>{title}</summary>
            <pre>{body}</pre>
          </details>
        ))}
      </section>
    )}
    {d.preview !== null && (
      <details open>
        <summary>Redacted artifact text</summary>
        <a href={withParam("download", "true")}>Download redacted text</a>
        <section aria-label="Artifact preview">
          <pre>{d.preview}</pre>
        </section>
      </details>
    )}
  </>
);

const Screen = ({ data: d }: { data: Data }) => (
  <>
    <h1>Review run</h1>
    <p>
      {d.run.folder} · {d.run.sha} ·{" "}
      <a href={`/projects/${d.project.id}/runs/${d.run.id}`}>
        Run details and exports
      </a>
    </p>
    <h2>Reports and Harbor artifacts</h2>
    <p>
      <a href="?report=true">View report</a> ·{" "}
      <a href="?agents=true">Compare agents</a> ·{" "}
      <a href="?latest=true">Latest per agent</a> ·{" "}
      <a href="?harbor=true">Browse Harbor jobs</a> ·{" "}
      <a href={`/projects/${d.project.id}/results?run=${d.run.id}`}>
        Filter measurements
      </a>
    </p>
    {d.comparison !== null && (
      <section aria-label="Agent score comparison">
        <pre>{d.comparison}</pre>
      </section>
    )}
    <Inventory data={d} />
    <Feedback data={d} />
  </>
);

/** @returns The evidence document at its canonical author URL. */
export default function Review() {
  return <EvidencePage screen={Screen} />;
}
