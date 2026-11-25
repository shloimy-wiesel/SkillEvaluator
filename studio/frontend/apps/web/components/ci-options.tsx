/** Default options for the revision under review. */
export interface Defaults {
  platform: string;
  tiers: string;
  default_branch: string;
  score: number;
  scope: string;
  channel: string;
  release: string;
  full: string;
  report_url: string;
  env_mode: string;
  provider: string;
  embedding_provider: string;
  tier1_llm: boolean;
  tier1_provider: string;
  tier3_provider: string;
  n_attempts: number;
  n_concurrent: number;
  timeout_minutes: number;
  benchmark_pr: boolean;
  mode: string;
  model: string;
  embedding_model: string;
  base_url: string;
  embedding_base_url: string;
  tier1_model: string;
  tier3_model: string;
  tier3_base_url: string;
  agents: string;
  runner: string;
  environment: string;
  gateway_secret: string;
  paths: string;
  agent_model: string;
}

interface Props {
  form: Defaults;
}

const Choice = ({
  name,
  label,
  choices,
  value,
}: {
  name: keyof Defaults;
  label: string;
  choices: string[];
  value: string;
}) => (
  <label>
    {label}{" "}
    <select aria-label={label} name={name} defaultValue={value}>
      {choices.map((choice) => (
        <option key={choice} value={choice}>
          {choice || "Automatic"}
        </option>
      ))}
    </select>
  </label>
);

const compatible = "openai-compatible";

/** @returns The HostOptions controls. */
export const HostOptions = ({ form }: Props) => (
  <>
    <Choice
      name="platform"
      label="Host platform"
      choices={["auto", "github", "gitlab"]}
      value={form.platform}
    />
    <Choice
      name="tiers"
      label="Evaluation tiers"
      choices={["one", "all"]}
      value={form.tiers}
    />
  </>
);

/** @returns The ScanOptions controls. */
export const ScanOptions = ({
  form,
  releases,
}: Props & { releases: string[] }) => (
  <>
    <label>
      Scan roots (one per line){" "}
      <textarea name="paths" defaultValue={form.paths} />
    </label>
    <label>
      Default branch override{" "}
      <input
        type="text"
        name="default_branch"
        defaultValue={form.default_branch}
      />
    </label>
    <label>
      Minimum score{" "}
      <input type="number" name="score" defaultValue={form.score} />
    </label>
    <Choice
      name="scope"
      label="Scan scope"
      choices={["auto", "all"]}
      value={form.scope}
    />
    <Choice
      name="channel"
      label="Release channel"
      choices={["pinned", "stable"]}
      value={form.channel}
    />
    <Choice
      name="release"
      label="Pinned release descriptor"
      choices={releases}
      value={form.release}
    />
    <Choice
      name="full"
      label="Hosted reports (GitHub Tier 1)"
      choices={["auto", "hosted", "checks"]}
      value={form.full}
    />
    <label>
      GitHub Pages report URL{" "}
      <input type="text" name="report_url" defaultValue={form.report_url} />
    </label>
  </>
);

/** @returns The RunnerOptions controls. */
export const RunnerOptions = ({ form }: Props) => (
  <>
    <Choice
      name="env_mode"
      label="Execution environment"
      choices={["docker", "local"]}
      value={form.env_mode}
    />
    <Choice
      name="provider"
      label="Chat provider"
      choices={["openai", "anthropic", "nv_build", compatible]}
      value={form.provider}
    />
    <Choice
      name="embedding_provider"
      label="Embedding provider"
      choices={["", "openai", "nv_build", compatible]}
      value={form.embedding_provider}
    />
    <label>
      Protected Tier 1 LLM checks{" "}
      <input
        type="checkbox"
        name="tier1_llm"
        value="true"
        defaultChecked={form.tier1_llm}
      />
    </label>
    <Choice
      name="tier1_provider"
      label="Tier 1 provider"
      choices={["", "openai", "anthropic", "nv_build"]}
      value={form.tier1_provider}
    />
    <Choice
      name="tier3_provider"
      label="Tier 3 provider"
      choices={["", "openai", "anthropic", "nv_build", compatible]}
      value={form.tier3_provider}
    />
    <label>
      Chat model <input type="text" name="model" defaultValue={form.model} />
    </label>
    <label>
      Embedding model{" "}
      <input
        type="text"
        name="embedding_model"
        defaultValue={form.embedding_model}
      />
    </label>
    <label>
      Chat base URL{" "}
      <input type="text" name="base_url" defaultValue={form.base_url} />
    </label>
    <label>
      Embedding base URL{" "}
      <input
        type="text"
        name="embedding_base_url"
        defaultValue={form.embedding_base_url}
      />
    </label>
    <label>
      Tier 1 model{" "}
      <input type="text" name="tier1_model" defaultValue={form.tier1_model} />
    </label>
    <label>
      Tier 3 model{" "}
      <input type="text" name="tier3_model" defaultValue={form.tier3_model} />
    </label>
    <label>
      Tier 3 base URL{" "}
      <input
        type="text"
        name="tier3_base_url"
        defaultValue={form.tier3_base_url}
      />
    </label>
    <label>
      Native agents (comma separated){" "}
      <input type="text" name="agents" defaultValue={form.agents} />
    </label>
    <label>
      Runner label{" "}
      <input type="text" name="runner" defaultValue={form.runner} />
    </label>
    <label>
      Protected environment name{" "}
      <input type="text" name="environment" defaultValue={form.environment} />
    </label>
    <label>
      Gateway secret name (not its value){" "}
      <input
        type="text"
        name="gateway_secret"
        defaultValue={form.gateway_secret}
      />
    </label>
    <label>
      Agent model overrides (one AGENT=MODEL per line){" "}
      <textarea name="agent_model" defaultValue={form.agent_model} />
    </label>
    <label>
      Attempts{" "}
      <input type="number" name="n_attempts" defaultValue={form.n_attempts} />
    </label>
    <label>
      Concurrency{" "}
      <input
        type="number"
        name="n_concurrent"
        defaultValue={form.n_concurrent}
      />
    </label>
    <label>
      Timeout minutes{" "}
      <input
        type="number"
        name="timeout_minutes"
        defaultValue={form.timeout_minutes}
      />
    </label>
    <label>
      Publish benchmark update PR (GitHub only){" "}
      <input
        type="checkbox"
        name="benchmark_pr"
        value="true"
        defaultChecked={form.benchmark_pr}
      />
    </label>
  </>
);

/** @returns The PublicationMode controls. */
export const PublicationMode = ({ form }: Props) => (
  <Choice
    name="mode"
    label="Publication mode"
    choices={["preview", "save", "pr"]}
    value={form.mode}
  />
);
