/* oxlint-disable react-doctor/no-array-index-as-key -- Immutable ordered evidence may contain duplicates. ASGI owns navigation and styles; async forms release busy state in finally. */
"use client";

import type { Project } from "@/lib/studio-api";

import { EvidencePage, Select, Version } from "./common";
import { runChoices, withParam } from "./model";
import type { Comparison, Run } from "./model";

interface Row {
  run_id: string;
  agent: string;
  segment: number;
  with_skill_score: number | null;
  without_skill_score: number | null;
  lift_delta: number | null;
  lift_change: number | null;
  status: string;
  lift_reasons: string[];
}

interface Data {
  project: Project;
  choices: Run[];
  scope: string[];
  agent: string;
  prior: string;
  current: string;
  trend: { rows: Row[] };
  comparison: Comparison;
}

const Screen = ({ data: d }: { data: Data }) => {
  const choices = runChoices(d.choices);

  return (
    <>
      <h1>Skill lift history</h1>
      <p>Retained live evaluations of {d.project.folder}.</p>
      <form>
        <Select
          name="scope"
          label="Results scope"
          multiple
          value={d.scope}
          options={choices}
        />
        <label>
          Agent filter
          <input name="agent" defaultValue={d.agent} />
        </label>
        {(["current", "prior"] as const).map((k) => (
          <Select
            key={k}
            name={k}
            label={k === "current" ? "Current evaluation" : "Prior evaluation"}
            value={d[k]}
            options={[
              {
                value: "latest",
                label:
                  k === "current"
                    ? "Latest completed"
                    : "Latest earlier compatible revision",
              },
              ...choices,
            ]}
          />
        ))}
        <button type="submit">Inspect results</button>
      </form>
      <h2>Baseline lift trend</h2>
      <table>
        <thead>
          <tr>
            {[
              "Native run",
              "Agent",
              "Segment",
              "With skill",
              "Without skill",
              "Lift",
              "Lift change",
              "Evidence",
            ].map((v) => (
              <th key={v}>{v}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {d.trend.rows.map((r, i) => (
            <tr key={i}>
              {(
                [
                  "run_id",
                  "agent",
                  "segment",
                  "with_skill_score",
                  "without_skill_score",
                  "lift_delta",
                  "lift_change",
                ] as const
              ).map((k) => (
                <td key={k}>{r[k] ?? "Not measured"}</td>
              ))}
              <td>
                {r.status} {r.lift_reasons.join("; ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!d.trend.rows.length && <p>No matching retained rows.</p>}
      {Object.entries({ json: "JSON", csv: "CSV", md: "Markdown" }).map(
        ([key, label]) => (
          <p key={key}>
            <a href={withParam("download", key)}>History {label}</a>
          </p>
        )
      )}
      <Version result={d.comparison} />
      <a href={withParam("download", "comparison")}>Comparison JSON</a>
    </>
  );
};

/** @returns The evidence document at its canonical author URL. */
export default function History() {
  return <EvidencePage screen={Screen} />;
}
