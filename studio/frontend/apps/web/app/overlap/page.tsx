"use client";

import { QueueForm, RunDocument } from "@/components/run-workspace/document";
import { Numeric, Select, Toggle } from "@/components/run-workspace/fields";
import type { Project } from "@/lib/studio-api";

interface Settings {
  project: Project;
  sha: string;
  dirs: string[];
  catalogs: string[];
  entries: number;
  scalars: number;
}

const settings = (
  { project, sha, dirs, catalogs, entries, scalars }: Settings,
  path: string
) => (
  <>
    <h1>Evaluate overlap</h1>
    <p>
      Use the saved{" "}
      <a href={`/projects/${project.id}/providers`}>provider settings</a>.
      Similarity needs embeddings only; intra-skill review also needs chat.
    </p>
    <form method="get">
      <label>
        Commit SHA
        <input name="sha" defaultValue={sha} required />
      </label>
      <button type="submit">Load commit inputs</button>
    </form>
    <QueueForm path={path} button="Queue overlap checks" lists={["formats"]}>
      <input type="hidden" name="sha" value={sha} />
      <Select name="action" label="Overlap checks">
        <option value="direct">
          Tier 2: intra-skill and optional catalog comparison
        </option>
        <option value="context">Context optimization check</option>
        <option value="dedup">Dedup scan</option>
        <option value="similarity">Similarity check</option>
      </Select>
      <Numeric
        name="threshold"
        label="Intra-skill threshold"
        max={1}
        step="any"
        value={0.8}
      />
      <Numeric
        name="similarity_threshold"
        label="Similarity threshold"
        max={1}
        step="any"
        value={0.75}
      />
      <Select name="catalog" label="Comparison catalog" options={catalogs}>
        <option value="">No catalog</option>
      </Select>
      <Toggle name="full_body" label="Compare full bodies" />
      <fieldset>
        <legend>Focused checks</legend>
        <label>
          Embedding model override
          <input name="model" placeholder="Saved model" />
        </label>
        <label>
          Chat model override (context or dedup)
          <input name="llm_model" placeholder="Saved model" />
        </label>
      </fieldset>
      <fieldset>
        <legend>Similarity check only</legend>
        <Select name="collection" label="Collection directory" options={dirs}>
          <option value="">Selected skill: {project.folder}</option>
        </Select>
        <Select
          name="content_type"
          label="Content type"
          options={["auto", "skill", "rules", "workflows"]}
        />
        <Numeric
          name="max_entries"
          label="Maximum entries"
          min={1}
          max={5000}
          value={entries}
        />
        <Numeric
          name="max_scalar_comparisons"
          label="Maximum scalar comparisons"
          min={1}
          value={scalars}
        />
        <Toggle name="save_catalog" label="Save catalog for download" />
      </fieldset>
      <Select
        name="formats"
        label="Report formats"
        multiple
        options={[
          "cli",
          "html",
          "json",
          "markdown",
          "sarif",
          "junit",
          "github",
        ]}
      />
      <p>
        Direct Tier 2 defaults to the summary with HTML and JSON files. Focused
        checks default to the summary. Select cli alone for the summary without
        additional files.
      </p>
    </QueueForm>
  </>
);

/** @returns The revision-pinned overlap launcher. */
export default function Page() {
  return <RunDocument render={settings} />;
}
