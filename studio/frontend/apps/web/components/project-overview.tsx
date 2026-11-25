/* oxlint-disable shadcn/no-unknown-classes, next/no-html-link-for-pages, react-doctor/nextjs-no-a-element -- Studio classes come from the shared same-origin stylesheet. Browser routes are owned by ASGI. */
"use client";

import { useState } from "react";

import { api, messageOf, useResource } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

interface Overview {
  project: Project;
  groups: {
    title: string;
    hint: string;
    actions: { href: string; label: string }[];
  }[];
  gitlab: boolean;
}

const CheckRemote = ({ id }: { id: string }) => {
  const [message, setMessage] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const check = async () => {
    setBusy(true);
    setMessage("");
    setProblem("");

    try {
      const result = await api<{ message: string }>(`/projects/${id}/check`, {
        method: "POST",
      });

      setMessage(result.message);
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          void check();
        }}
        disabled={busy}
      >
        {busy ? "Checking…" : "Check remote access"}
      </button>
      {message && <output>{message}</output>}
      {problem && <p role="alert">{problem}</p>}
    </>
  );
};

/** @returns The project overview independently of its document route. */
export const ProjectOverview = ({ projectId }: { projectId: string }) => {
  const { data, error } = useResource<Overview>(`/projects/${projectId}`);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <output>Opening project…</output>;
  }

  const { project, groups, gitlab } = data;

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href="/">Projects</a> /{" "}
        <span aria-current="page">{project.name}</span>
      </nav>
      <div className="page-intro">
        <p className="eyebrow">Project overview</p>
        <h1>{project.name}</h1>
        <p className="lede">
          Edit your skill, check its behavior, or revisit a previous run.
        </p>
      </div>
      <div className="tasks">
        {groups.map(({ title, hint, actions }, index) => (
          <section className="task" aria-label={title} key={title}>
            <span className="marker" aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <h2>{title}</h2>
            <p>{hint}</p>
            <ul>
              {actions.map(({ href, label }) => (
                <li key={label}>
                  <a href={href}>
                    {label}
                    <span aria-hidden="true">→</span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <section className="panel connection">
        <p className="eyebrow">Project details</p>
        <h2>Connected skill</h2>
        <dl>
          {[
            ["Repository", project.remote],
            ["Skill folder", project.folder],
            ["Branch", project.branch],
            ["Checkout revision", project.revision],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                <code>{value}</code>
              </dd>
            </div>
          ))}
        </dl>
        <CheckRemote id={projectId} />
        {gitlab && (
          <p>
            <a href={`/projects/${projectId}/gitlab`}>GitLab access</a>
          </p>
        )}
      </section>
    </>
  );
};
