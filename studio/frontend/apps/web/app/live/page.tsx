"use client";

import { Fragment, useState } from "react";

import { QueueForm, RunDocument } from "@/components/run-workspace/document";
import { Numeric, Select, Toggle } from "@/components/run-workspace/fields";
import type { Project } from "@/lib/studio-api";
import { useResource } from "@/lib/studio-api";

interface Settings {
  project: Project;
  judge: string | null;
  profiles: { key: string; label: string; reason: string | null }[];
  prior: { id: string; sha: string; created: string }[];
}

const budgets = [
  ["n_attempts", "Attempts per case", 1, 1],
  ["max_attempts_total", "Maximum total attempts", 0, 1],
  ["n_concurrent", "Concurrent cases per agent", 1, 1],
  ["max_agents", "Concurrent agents", 1, 1],
  ["max_cases", "Maximum cases", 1, 1],
  ["pass_threshold", "Pass threshold", 0, "any"],
  ["timeout_multiplier", "Timeout multiplier", 0, "any"],
  ["max_agent_tokens", "Maximum measured agent tokens", 0, 1],
  ["max_judge_calls", "Maximum judge calls", 0, 1],
  ["max_cost_usd", "Maximum agent cost (USD)", 0, "any"],
  ["override_cpus", "CPUs per trial", 1, 1],
  ["override_memory_mb", "Memory per trial (MiB)", 1, 1],
  ["override_storage_mb", "Storage per trial (MiB)", 1, 1],
] as const;

const Trials = ({ judge }: { judge: string | null }) => (
  <details>
    <summary>Trial settings and budgets</summary>
    <p>
      Blank limits use the pinned policy and engine defaults. Paid workload
      scales with cases × agents × attempts × arms.
    </p>
    <p>Saved chat / standard judge: {judge ?? "not configured"}</p>
    <p>
      Per-agent settings override the shared agent model. For an
      OpenAI-compatible OpenCode agent, enter openai/MODEL.
    </p>
    <label>
      Agent model override
      <input name="model" />
    </label>
    <Toggle
      name="harbor_keep_jobs"
      label="Retain Harbor jobs for trajectory review"
    />
    {Object.entries({
      codex_model: "Codex",
      opencode_model: "OpenCode",
      claude_code_model: "Claude Code",
    }).map(([name, label]) => (
      <label key={name}>
        {label} model override
        <input name={name} />
      </label>
    ))}
    {budgets.map(([name, label, min, step]) => (
      <Numeric key={name} name={name} label={label} min={min} step={step} />
    ))}
    <label>
      Model price file (repository-relative; required for USD budget)
      <input name="price_file" />
    </label>
    {Object.entries({
      stop_on_pass: "Stop remaining attempts after a pass",
      agent_runtime_preflight: "Run a paid agent preflight",
      tolerate_baseline_timeouts: "Tolerate baseline timeouts",
    }).map(([name, label]) => (
      <Select key={name} name={name} label={label}>
        <option value="">Use run policy</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </Select>
    ))}
    <Toggle
      name="autopilot"
      label="Prepare missing dataset even with Evaluate"
    />
  </details>
);

const ProfileChoices = ({ profiles }: Pick<Settings, "profiles">) => (
  <Select name="sandbox_profile" label="Sandbox profile">
    <option value="generated">Generated Harbor tasks</option>
    {profiles.map(({ key, label, reason }) => (
      <option key={key} value={key} disabled={Boolean(reason)}>
        {label}
        {Boolean(reason) && ` — ${reason}`}
      </option>
    ))}
  </Select>
);

const RevisionProfiles = ({ path }: { path: string }) => {
  const { data, error } = useResource<Settings["profiles"]>(path);

  return (
    <>
      <ProfileChoices profiles={data ?? []} />
      {error !== undefined && <p role="alert">{error}</p>}
    </>
  );
};

const fullSha = /^[0-9a-f]{40}(?:[0-9a-f]{24})?$/u;

const RevisionInputs = ({
  project,
  profiles,
}: Pick<Settings, "project" | "profiles">) => {
  const [draft, setDraft] = useState<string>();
  const sha = draft ?? project.revision;
  let choices = <ProfileChoices profiles={[]} />;

  if (sha === project.revision) {
    choices = <ProfileChoices profiles={profiles} />;
  } else if (fullSha.test(sha)) {
    choices = (
      <RevisionProfiles
        path={`/projects/${project.id}/live/profiles?sha=${sha}`}
      />
    );
  }

  return (
    <>
      <label>
        Commit SHA
        <input
          name="sha"
          value={sha}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          required
        />
      </label>
      <Fragment key={sha}>
        {choices}
        <Toggle
          name="reviewed_inputs"
          label="I reviewed the pinned task inputs and consent to running them in the selected paid sandbox"
        />
      </Fragment>
    </>
  );
};

const settings = (
  { project, judge, profiles, prior }: Settings,
  path: string
) => (
  <>
    <h1>Live Tier 3</h1>
    <p>
      Configure{" "}
      <a href={`/projects/${project.id}/providers`}>the chat provider</a> and an
      operator-managed Docker sandbox before starting paid trials.
    </p>
    <QueueForm path={path} button="Queue live evaluation" lists={["agents"]}>
      <RevisionInputs project={project} profiles={profiles} />
      <p>
        Native Harbor requires the stock single-step task scaffold. Gym requires
        the pinned Gym worker, Docker and a Codex Responses-compatible provider.
      </p>
      <Select name="workflow" label="Workflow">
        <option value="evaluate">Evaluate existing cases</option>
        <option value="alias">
          Evaluate existing cases (legacy evaluate alias)
        </option>
        <option value="direct">Direct Tier 3: prepare a missing dataset</option>
      </Select>
      <label>
        Dataset path (repository-relative; blank discovers the pinned skill
        dataset)
        <input name="dataset" />
      </label>
      <Select
        name="env_mode"
        label="Environment"
        options={["docker", "kata"]}
      />
      <Select name="grading_mode" label="Grading mode">
        <option value="">Use run policy (otherwise standard)</option>
        <option value="default">Standard</option>
        <option value="default_plus_custom">
          Standard and sandboxed custom grader
        </option>
        <option value="custom_only">Sandboxed custom grader only</option>
      </Select>
      <Toggle
        name="sandbox_grader_consent"
        label="Allow the repository grader in the sandbox"
      />
      <fieldset>
        <legend>Agents · leave unchecked for the provider default</legend>
        {["codex", "opencode", "claude-code"].map((agent) => (
          <Toggle key={agent} name="agents" value={agent} label={agent} />
        ))}
      </fieldset>
      <Select name="arms" label="Comparison arms">
        <option value="paired">With and without skill</option>
        <option value="skill">With skill only</option>
        <option value="baseline">Baseline only</option>
      </Select>
      {Object.entries({
        reuse_baseline: "Reuse baseline from",
        compare_to: "Compare skill to",
      }).map(([name, label]) => (
        <Select key={name} name={name} label={label}>
          <option value="">None</option>
          {prior.map((run) => (
            <option key={run.id} value={run.id}>
              {run.sha.slice(0, 12)} · {run.created} · {run.id}
            </option>
          ))}
        </Select>
      ))}
      <Trials judge={judge} />
    </QueueForm>
  </>
);

/** @returns The live evaluation launcher. */
export default function Page() {
  return <RunDocument render={settings} />;
}
