"use client";

import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

const gates = [
  ["false pass", "max_false_pass_rate"],
  ["false fail", "max_false_fail_rate"],
  ["unjudgeable", "max_unjudgeable_rate"],
] as const;

const whitespace = /\s+/u;

const QualificationFields = ({ files }: { files: string[] }) => (
  <>
    <label htmlFor="suite">Suite</label>
    <select id="suite" name="suite">
      <option value="">Bundled reference suite</option>
      {files.map((file) =>
        file.split("/").at(-1) === "suite.json" ? (
          <option key={file}>{file}</option>
        ) : null
      )}
    </select>
    <label htmlFor="split">Split</label>
    <select id="split" name="split">
      <option>assessment</option>
      <option>tuning</option>
      <option>all</option>
    </select>
    <label>
      Case IDs (one per line; blank selects all) <textarea name="cases" />
    </label>
    <label>
      Qualification policy{" "}
      <select name="policy">
        <option value="">None</option>
        {files.map((file) => (
          <option key={file}>{file}</option>
        ))}
      </select>
    </label>
    <label>
      Repeats{" "}
      <input
        type="number"
        name="repeats"
        min="1"
        max="20"
        defaultValue="3"
        required
      />
    </label>
    <label>
      Concurrency{" "}
      <input
        type="number"
        name="concurrency"
        min="1"
        max="4"
        defaultValue="1"
        required
      />
    </label>
    <label>
      Attempt timeout (seconds){" "}
      <input
        type="number"
        name="timeout"
        min="0.001"
        step="any"
        max="600"
        defaultValue="300"
        required
      />
    </label>
    {gates.map(([label, name]) => (
      <label key={name}>
        Maximum {label} rate{" "}
        <input type="number" min="0" max="1" step="any" name={name} />
      </label>
    ))}
    <label>
      <input type="checkbox" name="sandbox_consent" /> Allow this project suite
      to run in the isolated Docker worker with the saved chat profile (offline
      if none).
    </label>
  </>
);

/** @returns The revision-bound qualification and suite-check actions. */
export const Qualification = ({
  project,
  files,
}: {
  project: Project;
  files: string[];
}) => {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const projectPath = `/projects/${project.id}`;

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();

    const fields = new FormData(
      event.currentTarget,
      event.nativeEvent.submitter
    );

    const rawCases = fields.get("cases");
    const cases = rawCases instanceof File ? "" : (rawCases?.trim() ?? "");

    const body = {
      ...Object.fromEntries(fields),
      cases: cases ? cases.split(whitespace) : [],
      branch: project.branch,
      revision: project.revision,
      sandbox_consent: fields.has("sandbox_consent"),
      ...Object.fromEntries(
        gates.map(([, name]) => [
          name,
          fields.get(name) === "" ? null : fields.get(name),
        ])
      ),
    };

    setBusy(true);
    setProblem("");

    try {
      const { run_id } = await api<{ run_id: string }>(
        `${projectPath}/assets/qualify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );

      window.location.assign(`${projectPath}/runs/${run_id}`);
    } catch (error) {
      setProblem(messageOf(error));
      // oxlint-disable-next-line react-doctor/no-loading-flag-reset-outside-finally -- Success navigates to the queued run.
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>Validate the shipped grader</h2>
      <p>
        Check independently labelled evidence without inference, or qualify the
        shipped verifier against it. To evaluate your skill with an authored
        grader, <a href={`${projectPath}/live`}>open Live Tier 3</a> and allow
        the repository grader in the sandbox.
      </p>
      <form
        aria-label="Grader qualification"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <fieldset disabled={busy}>
          <QualificationFields files={files} />
          <p>
            Bundled qualification uses the installed tier3 extra and the project
            chat provider. It may incur inference charges. Project suite
            qualification requires an enabled sandbox. Results and JSON exports
            are retained in Evaluation runs.
          </p>
          <button type="submit" name="action" value="check">
            Check suite
          </button>{" "}
          <button type="submit" name="action" value="qualify">
            Run qualification
          </button>
        </fieldset>
        {problem && <p role="alert">{problem}</p>}
      </form>
    </section>
  );
};
