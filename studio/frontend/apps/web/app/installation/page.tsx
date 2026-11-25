"use client";

import { QueueForm, RunDocument } from "@/components/run-workspace/document";
import { Numeric, Select, Toggle } from "@/components/run-workspace/fields";
import type { Project } from "@/lib/studio-api";

interface Installation {
  project: Project;
  version: string;
  python: string;
  topic: string;
  topics: string[];
  help: string;
  changed: string[];
  configs: string[];
  diagnostics: { section: string; message: string }[];
}

const settings = (
  {
    project,
    version,
    python,
    topic,
    topics,
    help,
    changed,
    configs,
    diagnostics,
  }: Installation,
  path: string
) => (
  <>
    <h1>Installation and changed files</h1>
    {diagnostics.map(({ section, message }) => (
      <p role="alert" key={section}>
        {section}: {message} Reload to retry.
      </p>
    ))}
    <p>
      Installed evaluator: <strong>{version}</strong>
    </p>
    <form method="get">
      <Select name="topic" label="Help topic" options={topics} value={topic} />
      <button type="submit">Show help</button>
    </form>
    <section aria-label="Installed command help">
      <pre>{help}</pre>
    </section>
    <details>
      <summary>Diagnostic detail</summary>
      <dl>
        <dt>Python runtime</dt>
        <dd>{python}</dd>
        <dt>Project revision</dt>
        <dd>{project.revision}</dd>
        <dt>Connected folder</dt>
        <dd>{project.folder}</dd>
      </dl>
    </details>
    <h2>Check changed files</h2>
    <p>
      Changes at {project.revision} against its first parent (all files for an
      initial commit). Only affected skills are checked.
    </p>
    <QueueForm path={path} button="Check selected paths" lists={["paths"]}>
      <input type="hidden" name="sha" value={project.revision} />
      <Select
        name="paths"
        label="Changed paths"
        multiple
        required
        options={changed}
      />
      <Select
        name="check"
        label="Offline check"
        options={["schema", "quality", "lint-scripts"]}
      />
      <Numeric
        name="min_score"
        label="Minimum score (quality)"
        max={100}
        value={70}
      />
      <Select
        name="quality_config"
        label="Quality configuration"
        options={configs}
      >
        <option value="">Evaluator default</option>
      </Select>
      <Toggle name="verbose" label="Include redacted evaluator detail" />
    </QueueForm>
  </>
);

/** @returns The installed runtime and changed-file workspace. */
export default function Page() {
  return <RunDocument render={settings} />;
}
