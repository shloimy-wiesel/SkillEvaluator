/* oxlint-disable shadcn/no-unknown-classes -- Studio classes come from the shared same-origin stylesheet. */
"use client";

import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf, useResource } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

const Library = () => {
  const { data, error } = useResource<Project[]>("/projects");

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <output>Loading projects…</output>;
  }

  return (
    <>
      <h2>
        Connected projects <small>{data.length}</small>
      </h2>
      {data.length ? (
        data.map((p) => (
          <article className="library-entry" key={p.id}>
            <a className="project" href={`/projects/${p.id}`}>
              {p.name}
            </a>
            <dl className="library-meta">
              <div>
                <dt>Skill folder</dt>
                <dd>
                  <code>{p.folder}</code>
                </dd>
              </div>
              <div>
                <dt>Branch</dt>
                <dd>
                  <code>{p.branch}</code>
                </dd>
              </div>
            </dl>
          </article>
        ))
      ) : (
        <div className="empty">
          <b>No projects yet</b>
          <p>
            Connect a repository using its HTTPS clone URL to add your first
            skill here.
          </p>
        </div>
      )}
    </>
  );
};

const Connection = () => {
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (busy) {
      return;
    }

    const body = JSON.stringify(
      Object.fromEntries(new FormData(event.currentTarget))
    );

    setBusy(true);
    setProblem("");

    try {
      const project = await api<Project>("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });

      window.location.assign(`/projects/${project.id}`);
    } catch (error) {
      setProblem(messageOf(error));
      // oxlint-disable-next-line react-doctor/no-loading-flag-reset-outside-finally -- Success navigates to a new document.
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(event) => {
        void submit(event);
      }}
      method="post"
    >
      <label htmlFor="remote">Repository URL</label>
      <input
        name="remote"
        id="remote"
        type="url"
        placeholder="https://git.example.com/team/skills.git"
        aria-describedby="remote-hint"
        required
      />
      <p id="remote-hint">
        Use the HTTPS clone URL from the repository’s Code menu.
      </p>
      <label htmlFor="folder">Skill folder</label>
      <input
        name="folder"
        id="folder"
        defaultValue="."
        aria-describedby="folder-hint"
        required
      />
      <p id="folder-hint">
        Choose one folder that directly contains SKILL.md, such as
        skills/engineering/code-review. Use a dot for the root.
      </p>
      <details>
        <summary>Private repository credentials</summary>
        <label htmlFor="username">Git username</label>
        <input name="username" id="username" autoComplete="off" />
        <label htmlFor="token">Access token</label>
        <input
          name="token"
          id="token"
          type="password"
          autoComplete="new-password"
        />
      </details>
      <details>
        <summary>Self-managed GitLab</summary>
        <label htmlFor="gitlab">GitLab installation URL</label>
        <input
          type="url"
          id="gitlab"
          name="gitlab_root"
          placeholder="https://git.example.net:8443/forge"
        />
        <label htmlFor="ca">Private CA certificate (optional PEM bundle)</label>
        <textarea id="ca" name="ca_pem" />
      </details>
      {problem && <p role="alert">{problem}</p>}
      <button type="submit" disabled={busy}>
        {busy ? "Connecting…" : "Connect project"}
      </button>
    </form>
  );
};

/** @returns The project library and repository connection form. */
export default function Page() {
  return (
    <>
      <div className="page-intro">
        <p className="eyebrow">Studio / Workspace</p>
        <h1>Your projects</h1>
        <p className="lede">
          Connect a repository, choose a skill, and pick up where you left off.
        </p>
      </div>
      <div className="grid">
        <section className="panel">
          <p className="eyebrow">Project library</p>
          <Library />
        </section>
        <section className="panel">
          <p className="eyebrow">New connection</p>
          <h2>Connect a repository</h2>
          <Connection />
        </section>
      </div>
    </>
  );
}
