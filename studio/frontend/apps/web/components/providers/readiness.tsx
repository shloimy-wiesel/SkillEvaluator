/* oxlint-disable shadcn/no-unknown-classes -- Studio provides the shared panel stylesheet. */
import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";

import type { ProviderView } from "./document";

interface Tier {
  tier: string;
  checks: { check: string; status: string; detail: string }[];
}

interface Report {
  result:
    | { provider: string; models: { id: string; is_configured: boolean }[] }
    | { status: string; tiers: Tier[] };
  exit_code: number;
  show_json: boolean;
}

const Results = ({ report }: { report: Report }) => {
  const { result } = report;

  return (
    <>
      {"models" in result ? (
        <>
          <output>Catalog reachable: {result.provider}</output>
          <ul>
            {result.models.length ? (
              result.models.map((model) => (
                <li key={model.id}>
                  {model.id}
                  {model.is_configured && " (configured)"}
                </li>
              ))
            ) : (
              <li>No matching chat models</li>
            )}
          </ul>
        </>
      ) : (
        <>
          <output>Readiness: {result.status}</output>
          <table>
            <thead>
              <tr>
                <th>Tier</th>
                <th>Check</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            {result.tiers.map((tier) => (
              <tbody key={tier.tier}>
                {tier.checks.map((row) => (
                  <tr key={`${row.check}-${row.detail}`}>
                    <td>{tier.tier}</td>
                    <td>{row.check}</td>
                    <td>{row.status}</td>
                    <td>{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </>
      )}
      <p>Evaluator exit code: {report.exit_code}</p>
      {report.show_json && (
        <section aria-label="Native JSON">
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </section>
      )}
    </>
  );
};

// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
const Options = ({ values }: { values: string[] }) =>
  values.map((value) => <option key={value}>{value}</option>);

const RuntimeOptions = ({ data }: { data: ProviderView }) => (
  <details>
    <summary>Tier 3 runtime options</summary>
    <label>
      Runtime agents{" "}
      <select multiple name="agents">
        <Options values={data.runtime_agents} />
      </select>
    </label>
    <label>
      Runtime environment{" "}
      <select name="env_mode">
        <option value="">Evaluator default (Docker)</option>
        <Options values={data.modes} />
      </select>
    </label>
    <label>
      Kata runtime handler <input name="kata_runtime" placeholder="kata" />
    </label>
    <label>
      Kata DNS address <input name="kata_dns" />
    </label>
    <label>
      Execution backend (doctor){" "}
      <select name="backend">
        <option value="">Evaluator default (Harbor)</option>
        <option>harbor</option>
        <option>nemo-gym</option>
      </select>
    </label>
    {data.runtime_agents.map(
      (agent) =>
        agent !== "claude" && (
          <label key={agent}>
            {agent} model override{" "}
            <input
              name={`${agent.replaceAll("-", "_")}_model`}
              maxLength={256}
            />
          </label>
        )
    )}
  </details>
);

/** @returns Controls and native evaluator outcomes for the project-scoped check. */
export const Readiness = ({
  data,
  path,
}: {
  data: ProviderView;
  path: string;
}) => {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Report>();
  const [problem, setProblem] = useState("");
  const [allow, setAllow] = useState(false);

  const run = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);

    const body = JSON.stringify({
      ...Object.fromEntries(fields),
      agents: fields.getAll("agents"),
      checks: fields.getAll("checks"),
      as_json: fields.has("as_json"),
      verify_models: allow,
    });

    setReport(undefined);
    setProblem("");
    setBusy(true);
    setAllow(false);

    try {
      setReport(
        await api<Report>(`${path}/readiness/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        })
      );
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return (
    <section className="panel" aria-labelledby="project-readiness">
      <h2 id="project-readiness">Project readiness</h2>
      <p>
        Check this worker before an evaluation. Tier 1 needs the selected
        scanners, Tier 2 uses the saved provider profiles, and Tier 3 needs the
        runtime tools and a reachable backend. Each check stops after 90
        seconds.
      </p>
      <form
        method="post"
        onSubmit={(event) => {
          void run(event);
        }}
      >
        <fieldset disabled={busy}>
          <label>
            Readiness action{" "}
            <select name="action">
              <option value="doctor">Check tier readiness (doctor)</option>
              <option value="health-check">Quick health check</option>
              <option value="tier3 doctor">Inspect the live runtime</option>
              <option value="models">Discover chat models</option>
            </select>
          </label>
          <label>
            Tier scope{" "}
            <select name="tier">
              <option value="">Evaluator default (3)</option>
              <option>1</option>
              <option>2</option>
              <option>3</option>
              <option>all</option>
            </select>
          </label>
          <label>
            Scanner checks{" "}
            <select multiple name="checks">
              <Options values={data.scanners} />
            </select>
          </label>
          <label>
            Probe timeout (seconds){" "}
            <input
              type="number"
              step="any"
              min="0.001"
              max="60"
              name="timeout"
            />
          </label>
          <label>
            Catalog limit{" "}
            <input
              type="number"
              min="1"
              max="100"
              name="limit"
              placeholder="10"
            />
          </label>
          <RuntimeOptions data={data} />
          <label>
            <input
              type="checkbox"
              checked={allow}
              onChange={(event) => {
                setAllow(event.currentTarget.checked);
              }}
            />
            Allow provider probes
          </label>
          <p>
            Tier 2 sends a billable embedding and chat request. Tier 3 checks
            the selected agent models and live prerequisites. Model discovery
            only reads the chat catalog.
          </p>
          <label>
            <input name="as_json" type="checkbox" />
            Show redacted JSON
          </label>
          <button type="submit">
            {busy ? "Running check…" : "Run selected check"}
          </button>
        </fieldset>
      </form>
      {problem && <p role="alert">{problem}</p>}
      {report && <Results report={report} />}
    </section>
  );
};
