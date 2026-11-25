"use client";

import {
  Choice,
  Flag,
  Input,
  QueueForm,
  useRoute,
} from "@/components/expert/controls";
import { useResource } from "@/lib/studio-api";

interface ExperimentView {
  revision: string;
  folder: string;
}

const Revision = ({ sha }: { sha: string }) => (
  <Input name="sha" label="Commit SHA" initial={sha} required />
);

const Experiments = ({ path }: { path: string }) => {
  const { data, error } = useResource<ExperimentView>(path);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <output>Opening experiments…</output>;
  }

  const { folder, revision } = data;

  return (
    <>
      <a href={path.split("/experiments")[0]}>Project overview</a>
      <h1>Experiments</h1>
      <p>
        Choose files and folders from the selected project commit. Results are
        saved in run history.
      </p>
      <section>
        <h2>External observations</h2>
        <p>
          Import precomputed metrics without executing tests or verifying the
          producer’s claims.
        </p>
        <QueueForm path={`${path}/metrics`} label="Import observations">
          <Revision sha={revision} />
          <Input name="source" label="Observations JSON" required />
        </QueueForm>
      </section>
      <section>
        <h2>Catalog neighbors</h2>
        <p>
          Select a frozen manifest using the project embedding provider and a
          description catalog.
        </p>
        <QueueForm path={`${path}/decoys`} label="Select decoys">
          <Revision sha={revision} />
          <Input name="catalog" label="Catalog JSON" required />
          <Input name="catalog_root" label="Catalog root" required />
          <Input name="count" label="Decoy count" min={1} max={1000} />
          <label>
            Exclude paths (one per line)
            <textarea name="exclude" />
          </label>
          <Input name="model" label="Embedding model override" />
        </QueueForm>
      </section>
      <section>
        <h2>Multi-skill interaction</h2>
        <p>
          Run the baseline, each skill alone, and all skills together on one
          reviewed suite. Requires a saved chat provider and Harbor; each
          configuration can incur charges.
        </p>
        <QueueForm path={`${path}/interaction`} label="Run interaction">
          <Revision sha={revision} />
          <label>
            Selected skill folders (one per line)
            <textarea name="skills" defaultValue={folder} required />
          </label>
          <Input
            name="eval_source"
            label="Fixed evaluation source"
            initial={folder}
            required
          />
          <Choice
            name="metric"
            label="Outcome metric"
            placeholder=""
            values={["goal_accuracy", "accuracy", "overall"]}
          />
          <Flag
            name="sandbox_grader_consent"
            label="Allow the repository grader in the sandbox"
          />
          <Choice
            name="env_mode"
            label="Environment"
            placeholder=""
            values={["docker", "kata"]}
          />
          <Choice
            name="kata_runtime"
            label="Kata runtime (Kata only)"
            values={["kata", "kata-qemu", "kata-clh"]}
          />
          <label>
            Kata DNS servers (Kata only, one IP address per line)
            <textarea name="kata_dns" />
          </label>
          <Flag
            name="harbor_keep_jobs"
            label="Keep Harbor jobs in the private run directory"
          />
          <fieldset>
            <legend>Agents (none selected uses the engine default)</legend>
            {["codex", "opencode", "claude-code"].map((agent) => (
              <Flag key={agent} name="agents" label={agent} value={agent} />
            ))}
          </fieldset>
          <Input name="model" label="Agent model override" />
          <Input min={1} name="n_attempts" label="Attempts per case" />
          <Input min={1} name="n_concurrent" label="Concurrent trials" />
        </QueueForm>
      </section>
    </>
  );
};

/** @returns The pinned experiments workspace at the canonical project route. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export default function Page() {
  const route = useRoute();

  return route ? (
    <Experiments path={route.split("?")[0] ?? route} />
  ) : (
    <output>Opening experiments…</output>
  );
}
