"use client";

import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

interface StarterProps {
  project: Project;
  kind: "grader" | "harbor";
}

/** @returns The starter controls and the exact revision-bound preview being reviewed. */
export const Starter = ({ project, kind }: StarterProps) => {
  const harbor = kind === "harbor";
  const title = harbor ? "Native Harbor task" : "Custom grader";
  const [preview, setPreview] = useState<{ diff: string; body: string }>();
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/projects/${project.id}/assets`;
  const endpoint = `${path}/scaffold`;

  const showPreview = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);

    const starter = {
      ...Object.fromEntries(fields),
      branch: project.branch,
      revision: project.revision,
      kind,
      config: fields.has("config"),
      force: fields.has("force"),
    };

    setProblem("");
    setPreview(undefined);
    setBusy(true);

    try {
      const { diff } = await api<{ diff: string }>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...starter, action: "preview" }),
      });

      setPreview({
        diff,
        body: JSON.stringify({ ...starter, action: "save" }),
      });
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  const push = async () => {
    if (!preview) {
      return;
    }

    setBusy(true);
    setProblem("");

    try {
      const { revision } = await api<{ revision: string }>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: preview.body,
      });

      window.location.assign(`${path}?pushed=${revision}`);
    } catch (error) {
      setProblem(messageOf(error));
      // oxlint-disable-next-line react-doctor/no-loading-flag-reset-outside-finally -- Success navigates to the new revision.
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>{title}</h2>
      <form
        aria-label={title}
        onChange={() => {
          setPreview(undefined);
        }}
        onSubmit={(event) => {
          void showPreview(event);
        }}
      >
        <fieldset disabled={busy}>
          {harbor && (
            <label>
              Case ID <input name="case_id" defaultValue="case-001" required />
            </label>
          )}
          <label>
            Language{" "}
            <select name="language">
              <option>python</option>
              <option>shell</option>
            </select>
          </label>
          <label>
            Grading mode{" "}
            <select
              name="mode"
              defaultValue={harbor ? "custom_only" : "default_plus_custom"}
            >
              <option>default_plus_custom</option>
              <option>custom_only</option>
              {harbor && <option>default</option>}
            </select>
          </label>
          <label>
            <input type="checkbox" name="config" defaultChecked={!harbor} />{" "}
            Update evaluation configuration
          </label>
          <label>
            <input type="checkbox" name="force" /> Overwrite existing starter
          </label>
          <button type="submit">Preview</button>
        </fieldset>
      </form>
      {problem && <p role="alert">{problem}</p>}
      {preview && (
        <>
          <h3>Review branch changes</h3>
          <section aria-label="Change preview">
            <pre>{preview.diff}</pre>
          </section>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              void push();
            }}
          >
            Commit and push
          </button>
        </>
      )}
    </section>
  );
};
