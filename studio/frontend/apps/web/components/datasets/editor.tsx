/* oxlint-disable shadcn/no-unknown-classes -- Studio defines these classes in its same-origin stylesheet. */
"use client";

import { useEffect, useState } from "react";
import type { SubmitEvent } from "react";

import { messageOf } from "@/lib/studio-api";

import { Cases } from "./cases";
import { Action } from "./fields";
import type { DatasetView } from "./model";
import { Traces } from "./traces";
import { Workbench } from "./workbench";

type Reply =
  | DatasetView
  | { location: string }
  | { detail: { message: string } };

const request = async (path: string, options?: RequestInit) => {
  // oxlint-disable-next-line react-doctor/no-fetch-response-used-without-status-check -- 409 and 422 carry a reviewable draft, 404 a structured diagnostic.
  const response = await fetch(`/api/v1${path}`, {
    cache: "no-store",
    ...options,
  });

  if (!response.ok && ![404, 409, 422].includes(response.status)) {
    throw new Error(`Dataset request failed (${response.status}).`);
  }

  // SAFETY: The project-scoped dataset endpoint returns its view on success and on recoverable conflicts.
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion, anti-slop/require-safety-comment-for-type-assertion -- HTTP response boundary.
  return (await response.json()) as Reply;
};

const Publish = ({ view }: { view: DatasetView }) => (
  <section className="panel">
    <h2>Review &amp; publish</h2>
    <p>Only Commit and push changes the project branch.</p>
    <form>
      <Action value="preview">Preview changes</Action>
      {Boolean(view.draft?.staged.length) && (
        <Action value="commit">Commit and push</Action>
      )}
    </form>
    {view.diff !== undefined && (
      <section aria-label="Change preview">
        <pre>{view.diff}</pre>
      </section>
    )}
    <details>
      <summary>Delete dataset</summary>
      <form>
        <Action value="delete">Stage dataset deletion</Action>
      </form>
    </details>
    <details>
      <summary>Discard working copy</summary>
      <form>
        <Action value="discard">Discard private draft</Action>
      </form>
    </details>
  </section>
);

/** @returns A revision-bound authoring session, including recoverable conflict views. */
export const DatasetEditor = ({ path }: { path: string }) => {
  const [view, setView] = useState<DatasetView>();
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [retry, setRetry] = useState<FormData>();

  const [pending, setPending] = useState<{
    path: string;
    fields: FormData;
    reviewing: boolean;
  }>();

  // oxlint-disable-next-line react-doctor/no-fetch-in-effect, react-doctor/no-set-state-after-await-in-effect -- Static export; abort and gate writes on cleanup.
  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      try {
        const result = await request(path, { signal: controller.signal });

        if (!controller.signal.aborted) {
          if ("project" in result) {
            setView(result);
          } else if ("detail" in result) {
            setProblem(result.detail.message);
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setProblem(messageOf(error));
        }
      }
    };

    void load();

    return () => {
      controller.abort();
    };
  }, [path]);

  const submit = async (event: SubmitEvent<HTMLFieldSetElement>) => {
    event.preventDefault();

    if (busy || pending?.reviewing === true || !view) {
      return;
    }

    const body = new FormData(event.target, event.nativeEvent.submitter);

    if (view.draft) {
      body.set("draft", view.draft.token);
      body.set("version", String(view.draft.version));
    } else {
      body.set("branch", view.project.branch);
      body.set("revision", view.project.revision);
    }

    setBusy(true);
    setProblem("");

    try {
      const result = await request(path, { method: "POST", body });

      if ("location" in result) {
        window.location.assign(result.location);

        return;
      }

      if ("project" in result) {
        setView(result);
        const action = body.get("action");

        if (result.detail?.code === "conflict" && view.draft && result.draft) {
          body.delete("draft");
          setPending({ path: view.draft.path, fields: body, reviewing: true });
        }

        setRetry(
          result.detail?.code === "invalid_dataset" &&
            (action === "add" || action === "update")
            ? body
            : undefined
        );
        setEpoch((value) => value + 1);
      } else {
        setProblem(result.detail.message);
      }
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  if (!view) {
    return problem ? (
      <p role="alert">{problem}</p>
    ) : (
      <output>Opening datasets…</output>
    );
  }

  return (
    <>
      <nav aria-label="Breadcrumb">
        <a href={`/projects/${view.project.id}`}>{view.project.name}</a> /
        Datasets
      </nav>
      <p className="eyebrow">
        Evaluation design / {view.draft?.branch ?? view.project.branch}
      </p>
      <h1>Datasets</h1>
      <p className="lede">Design the cases that put your skill to the test.</p>
      {(problem || view.detail) && (
        <p role="alert">{problem || view.detail?.message}</p>
      )}
      {!busy && view.pushed === true && (
        <output>Pushed dataset changes to {view.project.branch}.</output>
      )}
      {busy && <output>Applying dataset action…</output>}
      {pending && (
        <section aria-label="Pending submission" className="panel">
          <h2>Pending submission</h2>
          <p>Current draft version: {view.draft?.version}</p>
          <p>
            Your submission for {pending.path} was not applied. Compare these
            values with the current draft below, then enter the changes you want
            to keep.
          </p>
          <dl>
            {[...pending.fields.entries()].map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>
                  <pre>{value instanceof File ? value.name : value}</pre>
                </dd>
              </div>
            ))}
          </dl>
          {pending.reviewing ? (
            <button
              type="button"
              onClick={() => {
                setPending({ ...pending, reviewing: false });
              }}
            >
              Reconcile with current draft
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                setPending(undefined);
              }}
            >
              Dismiss pending submission
            </button>
          )}
        </section>
      )}
      <fieldset
        key={epoch}
        className="datasets"
        disabled={busy || pending?.reviewing}
        inert={busy}
        aria-label="Dataset authoring"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        {view.draft ? (
          <>
            <Cases view={view} retry={retry} />
            {!busy && view.notice !== undefined && (
              <output>{view.notice}</output>
            )}
            <Workbench view={view} />
            <Traces view={view} />
            <Publish view={view} />
          </>
        ) : (
          <section className="panel">
            <h2>Author a dataset</h2>
            <p>
              Open a private working copy of this revision. Preview changes
              before publishing.
            </p>
            <form>
              <Action value="open">Open draft</Action>
            </form>
          </section>
        )}
      </fieldset>
    </>
  );
};
