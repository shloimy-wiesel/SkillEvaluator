/* oxlint-disable react/todo, react-doctor/no-array-index-as-key -- Immutable ordered evidence may contain duplicates. ASGI owns navigation and styles; async forms release busy state in finally. */
"use client";

import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

import { EvidencePage, Select } from "./common";
import { runChoices, strings, withParam } from "./model";
import type { Run } from "./model";

interface Data {
  project: Project;
  history: Run[];
  imported: string[];
  chosen: string[];
  choices: Record<string, string[]>;
  filters: Record<string, string[]>;
  display: string;
  metrics: string;
  metric_sets: string[];
  evidence: string;
  warnings: string[];
  rows: Record<string, string | number | null>[];
  columns: string[];
}

const Uploads = ({ path, imported }: { path: string; imported: string[] }) => {
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const file = new FormData(event.currentTarget).get("report");

    if (!(file instanceof File)) {
      return;
    }

    setBusy(true);

    try {
      const result = await api<{ location: string }>(`${path}/uploads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: file,
      });

      window.location.assign(result.location);
    } catch (error) {
      setProblem(messageOf(error));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);

    try {
      await api(`${path}/uploads/${encodeURIComponent(id)}/remove`, {
        method: "POST",
      });
      window.location.assign(path);
    } catch (error) {
      setProblem(messageOf(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <form
        onSubmit={(e) => {
          void submit(e);
        }}
      >
        <label>
          Dashboard report JSON
          <input
            type="file"
            name="report"
            accept=".json,application/json"
            required
          />
        </label>
        <button type="submit" disabled={busy}>
          Import report
        </button>
      </form>
      {imported.map((id) => (
        <button
          type="button"
          key={id}
          disabled={busy}
          onClick={() => {
            void remove(id);
          }}
        >
          Remove {id}
        </button>
      ))}
      {problem && <p role="alert">{problem}</p>}
    </>
  );
};

const Screen = ({ data: d }: { data: Data }) => {
  const root = `/projects/${d.project.id}`;

  return (
    <>
      <h1>Results dashboard</h1>
      <Uploads path={`${root}/results`} imported={d.imported} />
      <form>
        <Select
          name="run"
          label="Retained runs"
          multiple
          value={d.chosen}
          options={[...runChoices(d.history), ...strings(d.imported)]}
        />
        {Object.entries(d.choices).map(([k, v]) => (
          <Select
            key={k}
            name={k}
            label={k.charAt(0).toUpperCase() + k.slice(1)}
            multiple
            value={d.filters[k] ?? []}
            options={strings(v)}
          />
        ))}
        <Select
          name="evidence"
          label="Evidence source"
          value={d.evidence}
          options={[
            { value: "report", label: "Saved report" },
            { value: "native", label: "Native retained measurements" },
          ]}
        />
        <Select
          name="display"
          label="Display"
          value={d.display}
          options={strings(["performance", "comparison"])}
        />
        <Select
          name="metrics"
          label="Metrics"
          value={d.metrics}
          options={strings(d.metric_sets)}
        />
        <button type="submit">Apply filters</button>
      </form>
      <p>
        Empty filters include all values. Comparisons retain both conditions. A
        dash means unavailable.
      </p>
      {d.warnings.map((w, i) => (
        <p key={i}>{w}</p>
      ))}
      {d.rows.length ? (
        <>
          <a href={withParam("csv", "true")}>Download {d.display} CSV</a>
          <table>
            <thead>
              <tr>
                {d.columns.map((k) => (
                  <th key={k}>{k.replaceAll("_", " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r, i) => (
                <tr key={i}>
                  {d.columns.map((k) => (
                    <td key={k}>
                      {k === "source" &&
                      d.history.some((run) => run.id === r[k]) ? (
                        <a href={`${root}/runs/${r[k]}`}>{r[k]}</a>
                      ) : (
                        (r[k] ?? "—")
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <p>No matching agent measurements.</p>
      )}
    </>
  );
};

/** @returns The evidence document at its canonical author URL. */
export default function Results() {
  return <EvidencePage screen={Screen} />;
}
