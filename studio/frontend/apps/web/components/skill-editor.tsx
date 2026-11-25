/* oxlint-disable shadcn/no-unknown-classes, next/no-html-link-for-pages, react-doctor/nextjs-no-a-element -- Studio stylesheet and ASGI-owned routes. */
"use client";

import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf, useResource } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

interface View {
  project: Project;
  text: string | null;
  heads: Record<string, string>;
  error: string | null;
}

const BaseFields = ({ project }: { project: Project }) => (
  <>
    <input type="hidden" name="branch" value={project.branch} />
    <input type="hidden" name="revision" value={project.revision} />
  </>
);

const BranchForm = ({
  view,
  create,
  path,
  onSubmit,
}: {
  view: View;
  create: boolean;
  path: string;
  onSubmit: (event: SubmitEvent<HTMLFormElement>) => void;
}) => {
  const { project, heads } = view;
  const options = Object.entries(heads);

  return (
    <form action={`/api/v1${path}/branch`} method="post" onSubmit={onSubmit}>
      <BaseFields project={project} />
      <input type="hidden" name="action" value={create ? "create" : "switch"} />
      <label>
        {create ? "Start from branch" : "Open branch"}{" "}
        <select
          required
          name="source"
          defaultValue={`${heads[project.branch]} ${project.branch}`}
        >
          {options.map(([name, sha]) => (
            <option key={name} value={`${sha} ${name}`}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {create && (
        <label>
          New branch name <input required name="new" />
        </label>
      )}
      <button type="submit">
        {create ? "Create branch" : "Switch branch"}
      </button>
    </form>
  );
};

interface Address {
  path: string;
  pushed: string | null;
}

const Editor = ({ path, pushed, initial }: Address & { initial: View }) => {
  const [view, setView] = useState(initial);
  const [problem, setProblem] = useState(initial.error);
  const [diff, setDiff] = useState<string>();
  const [busy, setBusy] = useState(false);
  const { project } = view;

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form, event.nativeEvent.submitter);
    const action = data.get("action");
    const branchAction = action === "create" || action === "switch";
    setBusy(true);
    setProblem(null);

    try {
      const result = await api<{ diff?: string; revision?: string }>(
        `${path}/${branchAction ? "branch" : "changes"}`,
        { method: "POST", body: data }
      );

      if (action === "preview") {
        setDiff(result.diff === "" ? "No changes." : result.diff);
      } else {
        window.location.assign(
          result.revision === undefined
            ? path
            : `${path}?pushed=${encodeURIComponent(result.revision)}`
        );
      }
    } catch (error) {
      const latest = await api<View>(path).catch(() => view);
      setView(latest);
      setProblem(messageOf(error));
    }
  };

  const onSubmit = (event: SubmitEvent<HTMLFormElement>) => {
    void submit(event).finally(() => {
      setBusy(false);
    });
  };

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href="/">Projects</a> /{" "}
        {busy ? (
          project.name
        ) : (
          <a href={`/projects/${project.id}`}>{project.name}</a>
        )}{" "}
        / <span aria-current="page">Edit {project.branch}</span>
      </nav>
      <h1>Edit {project.branch}</h1>
      <p>
        Revision <code>{project.revision}</code>
      </p>
      {problem !== null && (
        <p role="alert">
          {problem} <a href={path}>Reopen editor</a>
        </p>
      )}
      {pushed === project.revision && (
        <output>Pushed revision {project.revision}.</output>
      )}
      <fieldset disabled={busy}>
        {initial.text !== null && (
          <section className="panel">
            <h2>Skill content</h2>
            <form
              action={`/api/v1${path}/changes`}
              method="post"
              onSubmit={onSubmit}
            >
              <BaseFields project={initial.project} />
              <label htmlFor="skill-content">SKILL.md</label>
              <textarea
                id="skill-content"
                name="text"
                rows={18}
                defaultValue={initial.text}
                onChange={() => {
                  setDiff(undefined);
                }}
              />
              <button name="action" value="preview" type="submit">
                Preview changes
              </button>{" "}
              <button name="action" value="save" type="submit">
                Save and push
              </button>
            </form>
            {diff !== undefined && (
              <section aria-label="Change preview">
                <h3>Change preview</h3>
                <pre>{diff}</pre>
              </section>
            )}
          </section>
        )}
        <section className="panel">
          <h2>Branches</h2>
          <BranchForm
            view={view}
            create={false}
            path={path}
            onSubmit={onSubmit}
          />
          <BranchForm view={view} create path={path} onSubmit={onSubmit} />
        </section>
      </fieldset>
    </>
  );
};

/** @returns The branch editor for this project. */
export const SkillEditor = ({ path, pushed }: Address) => {
  const { data, error } = useResource<View>(path);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  return data ? (
    <Editor path={path} pushed={pushed} initial={data} />
  ) : (
    <output>Opening editor…</output>
  );
};
