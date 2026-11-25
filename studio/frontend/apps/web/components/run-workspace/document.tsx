"use client";

import { useState } from "react";
import type { SubmitEvent, ReactNode } from "react";

import { api, messageOf, useResource } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";
import { useRoute } from "@/lib/use-route";

/** @returns The hydrated feature at its canonical FastAPI URL. */
// oxlint-disable-next-line sonarjs/function-name, typescript/no-unnecessary-type-parameters -- Generic React component tying the endpoint type to its renderer.
export const RunDocument = <T extends { project: Project }>({
  render,
}: {
  render: (data: T, path: string) => ReactNode;
}) => {
  const path = useRoute();

  return path ? (
    <Loaded path={path} render={render} />
  ) : (
    <p>Opening workspace…</p>
  );
};

// oxlint-disable-next-line typescript/no-unnecessary-type-parameters -- T also binds the resource read to the renderer.
const Loaded = <T extends { project: Project }>({
  path,
  render,
}: {
  path: string;
  render: (data: T, path: string) => ReactNode;
}) => {
  const { data, error } = useResource<T>(path);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <p>Opening workspace…</p>;
  }

  return (
    <>
      <nav aria-label="Breadcrumb">
        <a href={`/projects/${data.project.id}`}>{data.project.name}</a> /
        Evaluation
      </nav>
      {render(data, path)}
    </>
  );
};

const noLists: string[] = [];

/** @returns A queue form preserving drafts on error and omitting blank policy overrides. */
export const QueueForm = ({
  children,
  path,
  button,
  lists = noLists,
}: {
  children?: ReactNode;
  path: string;
  button: string;
  lists?: string[];
}) => {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();

    const fields = new FormData(event.currentTarget);
    const repeated = new Set(lists);

    const entries = new Map<
      string,
      FormDataEntryValue | FormDataEntryValue[]
    >();

    for (const [key, value] of fields) {
      if (value !== "") {
        entries.set(key, repeated.has(key) ? fields.getAll(key) : value);
      }
    }

    setBusy(true);
    setProblem("");

    try {
      const result = await api<{ href: string }>(path.split("?")[0] ?? path, {
        body: JSON.stringify(Object.fromEntries(entries)),
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });

      window.location.assign(result.href);
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return (
    <form
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      {children}
      {problem && <p role="alert">{problem}</p>}
      <button type="submit" disabled={busy}>
        {button}
      </button>
    </form>
  );
};
