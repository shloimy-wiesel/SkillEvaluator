"use client";

import { useState } from "react";

import { useResource } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

import { Qualification } from "./qualification";
import { Starter } from "./starter";

interface AssetView {
  project: Project;
  files: string[];
}

/** @returns The authoring workspace at the project's current revision. */
export const Assets = ({
  projectId,
  pushedRevision,
}: {
  projectId: string;
  pushedRevision: string | null;
}) => {
  const [showReceipt, setShowReceipt] = useState(true);

  const { data, error } = useResource<AssetView>(
    `/projects/${projectId}/assets`
  );

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <output>Loading assets…</output>;
  }

  const { project, files } = data;

  return (
    <>
      <nav aria-label="Breadcrumb">
        <a href={`/projects/${projectId}`}>{project.name}</a> / Evaluation
        assets
      </nav>
      <h1>Evaluation assets</h1>
      <p>
        {project.folder} · {project.branch} @{" "}
        <code>{project.revision.slice(0, 12)}</code>
      </p>
      {showReceipt && pushedRevision === project.revision && (
        <output>Pushed {project.revision}</output>
      )}
      <div
        onSubmitCapture={() => {
          setShowReceipt(false);
        }}
      >
        <Starter project={project} kind="grader" />
        <Starter project={project} kind="harbor" />
      </div>
      <Qualification project={project} files={files} />
    </>
  );
};
