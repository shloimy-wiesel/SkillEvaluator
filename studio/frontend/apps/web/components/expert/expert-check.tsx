"use client";

import { useResource } from "@/lib/studio-api";

import { Choice, Flag, Input, QueueForm } from "./controls";

interface View {
  action: string;
  label: string;
  sha: string;
  folder: string;
  fields: string[];
  directories: string[];
  choices: string[];
  file_labels: { [name: string]: string };
  checks: string[];
  reports: string[];
  harnesses: string[];
}

const yesNo = ["true", "false"];
const agents = ["codex", "opencode", "claude-code"];

const TierThree = () => (
  <details>
    <summary>Tier 3 settings</summary>
    <p>
      Measured trials require Harbor and a saved chat profile. Trial budgets
      apply to each catalog member.
    </p>
    {(
      [
        ["block_on_agent_eval", "Tier 3 blocking gate"],
        ["agent_runtime_preflight", "Paid agent preflight"],
        ["autopilot", "Prepare missing dataset"],
        ["stop_on_pass", "Stop after first pass"],
        ["tolerate_baseline_timeouts", "Tolerate baseline timeouts"],
      ] as const
    ).map(([name, label]) => (
      <Choice
        key={name}
        name={name}
        label={label}
        values={yesNo}
        captions={["Yes", "No"]}
      />
    ))}
    <Choice name="env_mode" label="Sandbox" values={["docker", "kata"]} />
    <Choice
      name="kata_runtime"
      label="Kata runtime"
      values={["kata", "kata-qemu", "kata-clh"]}
    />
    <Choice multiple name="agents" label="Agents" values={agents} />
    <Choice
      name="grading_mode"
      label="Grading mode"
      values={["default", "custom_only", "default_plus_custom"]}
    />
    <Flag
      name="sandbox_grader_consent"
      label="Allow the repository grader in the sandbox"
    />
    {(
      [
        ["codex_model", "Codex model override"],
        ["opencode_model", "OpenCode model override"],
        ["claude_code_model", "Claude Code model override"],
        ["model", "Agent model"],
      ] as const
    ).map(([name, label]) => (
      <Input key={name} name={name} label={label} />
    ))}
    {(
      [
        ["n_attempts", "Attempts per case"],
        ["n_concurrent", "Concurrent cases"],
        ["max_agents", "Concurrent agents"],
        ["max_cases", "Maximum cases"],
      ] as const
    ).map(([name, label]) => (
      <Input key={name} name={name} label={label} min={1} />
    ))}
    {(
      [
        ["max_agent_tokens", "Maximum agent tokens"],
        ["max_judge_calls", "Maximum judge calls"],
        ["max_attempts_total", "Maximum total attempts"],
      ] as const
    ).map(([name, label]) => (
      <Input key={name} name={name} label={label} min={0} />
    ))}
    {(
      [
        ["max_cost_usd", "Maximum agent cost (USD)"],
        ["pass_threshold", "Case pass threshold"],
        ["timeout_multiplier", "Timeout multiplier"],
      ] as const
    ).map(([name, label]) => (
      <Input key={name} name={name} label={label} min={0} step="any" />
    ))}
    <Flag
      name="harbor_keep_jobs"
      label="Keep Harbor job evidence in private run storage"
    />
    <Flag name="skip_baseline" label="Skip baseline" />
  </details>
);

const Pipeline = () => (
  <>
    <Choice
      name="tiers"
      label="Tiers"
      placeholder="Engine default (all three tiers)"
      values={["1", "1,2", "1,3", "1,2,3"]}
      captions={[
        "Tier 1 only",
        "Tier 1 and Tier 2",
        "Tier 1 and Tier 3",
        "All three tiers",
      ]}
    />
    <Choice
      name="block_on_dedup"
      label="Tier 2 gate"
      values={yesNo}
      captions={["Blocking", "Advisory"]}
    />
    <details>
      <summary>Workflow shortcuts</summary>
      <p>
        Explicit tiers override the live shortcut. Disabling deduplication skips
        Tier 2 even when selected.
      </p>
      <Flag name="full" label="Full validation" />
      <Flag name="external" label="External policy shortcut" />
      <Choice name="dedup" label="Deduplication" values={yesNo} />
      <Choice name="agent_eval" label="Live agent evaluation" values={yesNo} />
    </details>
    <Flag
      name="include_revision"
      label="Record the pinned revision on the benchmark card (automatic with Tier 3)"
    />
    <Input
      name="evaluated_source_repository"
      label="Source repository label (owner/repository)"
    />
    <Input
      name="evaluator_container_revision"
      label="Evaluator build label (image revision or commit)"
    />
    <TierThree />
  </>
);

const CheckSettings = ({ view: v }: { view: View }) => {
  const has = (key: string) => v.fields.includes(key);

  return (
    <>
      <Choice
        name="target"
        label="Target directory"
        placeholder="Connected skill"
        values={v.directories}
      />
      {has("workers") && (
        <>
          <p>
            Select a catalog directory to validate its members at this commit.
          </p>
          <Input name="workers" label="Catalog workers" min={1} max={4} />
          <Choice
            name="catalog_root"
            label="Catalog root"
            values={v.directories}
          />
          <Choice
            name="content_type"
            label="Content type"
            values={["skill", "rules", "workflows", "plugin"]}
          />
        </>
      )}
      {has("tiers") && <Pipeline />}
      {has("checks") && (
        <>
          <Choice
            multiple
            name="checks"
            label="Checks to run"
            values={v.checks}
          />
          <Choice
            multiple
            name="skip"
            label="Checks to skip"
            values={[...v.checks, "secrets"]}
          />
          <Choice
            name="profile"
            label="Policy profile"
            values={["default", "registry", "external"]}
          />
          <Input name="previous_version" label="Previous version" />
        </>
      )}
      {(has("checks") || v.action === "security-scan") && (
        <p>
          Keyless scans use installed scanners. Missing scanner evidence is
          reported in the run.
        </p>
      )}
      {has("min_score") && (
        <Input name="min_score" label="Minimum score" min={0} max={100} />
      )}
      {has("llm") && (
        <Choice
          name="llm"
          label="Model-backed checks"
          values={yesNo}
          captions={["Enable (chat provider)", "Disable"]}
        />
      )}
      {(
        [
          ["fail_fast", "Stop on first failure"],
          ["continue_on_failure", "Continue on failure"],
          ["verbose", "Verbose output"],
          ["llm_verify", "Verify findings with chat provider"],
          ["write_json", "Write harness JSON"],
          ["headless", "Headless mode"],
          ["explicit_invocation", "Explicit invocation"],
          ["custom_provider", "Custom provider"],
        ] as const
      ).map(
        ([name, label]) =>
          has(name) && <Flag key={name} name={name} label={label} />
      )}
      {Object.entries(v.file_labels).map(
        ([name, label]) =>
          has(name) && (
            <Choice key={name} name={name} label={label} values={v.choices} />
          )
      )}
      {has("harness") && (
        <Choice
          name="harness"
          label="Harnesses"
          multiple
          values={v.harnesses}
        />
      )}
      {has("harness_profiles") && (
        <Choice
          name="harness_profiles"
          label="Managed harness profiles"
          values={["agent-clis"]}
          captions={["Agent CLIs (Claude Code, Codex, OpenCode)"]}
        />
      )}
      {has("context_tokens") && (
        <Input name="context_tokens" label="Context tokens" min={0} />
      )}
      {has("harness_versions") && (
        <details>
          <summary>Harness versions</summary>
          <p>Omit the harness selection to check all packaged profiles.</p>
          {v.harnesses.map((h) => (
            <Input key={h} name={`version_${h}`} label={`${h} version`} />
          ))}
        </details>
      )}
      {has("reports") && (
        <Choice multiple name="reports" label="Reports" values={v.reports} />
      )}
    </>
  );
};

/** @returns Command-specific controls and commit-scoped file selectors. */
export const ExpertCheck = ({ route }: { route: string }) => {
  const { data, error } = useResource<View>(route);
  const [path = "", query] = route.split("?");
  const [projectPath] = path.split("/expert/");

  const chat =
    data !== undefined &&
    (data.action === "rubric-eval" ||
      data.fields.includes("llm_verify") ||
      data.fields.includes("llm"));

  return (
    <>
      <nav aria-label="Breadcrumb">
        <a href={projectPath}>Project overview</a> /{" "}
        <a href={`${projectPath}/runs`}>Evaluation runs</a>
      </nav>
      <h1>{data?.label ?? "Expert check"}</h1>
      {error !== undefined && <p role="alert">{error}</p>}
      {(data !== undefined || error !== undefined) && (
        <form method="get">
          <Input
            key={route}
            name="sha"
            label="Commit SHA"
            initial={data?.sha ?? new URLSearchParams(query).get("sha") ?? ""}
            required
          />
          <button type="submit">Load commit files</button>
        </form>
      )}
      {data && (
        <>
          <p>
            Evaluate {data.folder} at <code>{data.sha}</code>. Leave optional
            settings empty for evaluator defaults.
          </p>
          {chat && (
            <p>
              Model-backed checks use the saved{" "}
              <a href={`${projectPath}/providers`}>chat provider</a>.
              {data.action === "rubric-eval" &&
                " Rubric evaluation requires this provider."}
            </p>
          )}
          <QueueForm path={path} label="Queue check">
            <input type="hidden" name="sha" value={data.sha} />
            <CheckSettings view={data} />
          </QueueForm>
        </>
      )}
    </>
  );
};
