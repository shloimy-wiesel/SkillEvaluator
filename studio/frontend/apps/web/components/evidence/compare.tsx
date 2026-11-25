/* oxlint-disable shadcn/no-unknown-classes, react-doctor/no-array-index-as-key -- Immutable ordered evidence may contain duplicates. ASGI owns navigation and styles; async forms release busy state in finally. */
"use client";

import type { Project } from "@/lib/studio-api";

import { EvidencePage, Select, Version } from "./common";
import { score } from "./model";
import type { Run, Comparison } from "./model";

interface Coverage {
  scored_cases: number | null;
  expected_cases: number | null;
}

interface Arm {
  agent: string;
  model: string;
  with_skill_score: number | null;
  without_skill_score: number | null;
  lift_delta: number | null;
  coverage?: Record<string, Coverage>;
  lift_reasons: string[];
}

interface Side {
  label: string;
  sha: string;
  choices: Run[];
  run_id: string | null;
  history?: Arm[];
  results: { validator: string; status: string }[];
}

type Parts = [string, string][];

interface Diff {
  path: string;
  change: string;
  notice?: string;
  prior: Parts;
  current: Parts;
}

interface Data {
  project: Project;
  prior: string;
  current: string;
  choices: string[];
  files: Diff[];
  count: number;
  sides: Side[];
  comparison: Comparison;
}

const changes = new Map(
  Object.entries({
    M: "Modified",
    A: "Added",
    D: "Deleted",
    T: "Type changed",
  })
);

const Source = ({ parts, label }: { parts: Parts; label: string }) => (
  <section aria-label={`${label} source`}>
    <pre>
      {parts.map(([op, text], i) => {
        if (op === "equal") {
          return text;
        }

        return label === "Prior" ? (
          <del key={i}>{text}</del>
        ) : (
          <ins key={i}>{text}</ins>
        );
      })}
    </pre>
  </section>
);

const Arms = ({ rows, label }: { rows: Arm[]; label: string }) => (
  <section aria-label={`${label} arm scores`}>
    {rows.map((row, i) => (
      <article key={i}>
        <h4>
          {row.agent || "Unrecorded agent"} · {row.model || "Unrecorded model"}
        </h4>
        <dl>
          <dt>With skill</dt>
          <dd>{score(row.with_skill_score)}</dd>
          <dt>Without skill</dt>
          <dd>{score(row.without_skill_score)}</dd>
          <dt>Paired baseline lift</dt>
          <dd>{score(row.lift_delta, true)}</dd>
        </dl>
        {Object.entries(row.coverage ?? {}).map(([arm, c]) => (
          <p key={arm}>
            {arm} case coverage: {c.scored_cases ?? "?"}/
            {c.expected_cases ?? "?"}
          </p>
        ))}
        {row.lift_reasons.map((r) => (
          <p key={r}>{r}</p>
        ))}
      </article>
    ))}
  </section>
);

const Result = ({ side, project }: { side: Side; project: Project }) => {
  const key = side.label.toLowerCase();

  return (
    <article>
      <h3>{side.label} result</h3>
      <code>{side.sha}</code>
      <input type="hidden" name={key} value={side.sha} />
      {side.run_id === null ? (
        <p>No retained run for this revision.</p>
      ) : (
        <>
          <Select
            name={`${key}_run`}
            label={`${side.label} run`}
            value={side.run_id}
            options={side.choices.map((r) => ({
              value: r.id,
              label: `${r.created} · ${r.kind} · ${r.status} · ${r.id}`,
            }))}
          />
          {side.results.map((r, i) => (
            <p key={i}>
              {r.validator} · {r.status}
            </p>
          ))}
          <Arms rows={side.history ?? []} label={side.label} />
          <a href={`/projects/${project.id}/runs/${side.run_id}`}>
            Inspect {key} run
          </a>
        </>
      )}
    </article>
  );
};

const Screen = ({ data: d }: { data: Data }) => (
  <>
    <h1>Compare revisions</h1>
    <a href={`/projects/${d.project.id}/results/history`}>
      Skill lift history and version exports
    </a>
    <form>
      <datalist id="refs">
        {d.choices.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </datalist>
      {(["prior", "current"] as const).map((k) => (
        <label key={k}>
          {k === "prior" ? "Prior" : "Current"} revision
          <input list="refs" name={k} defaultValue={d[k]} required />
        </label>
      ))}
      <button type="submit">Compare revisions</button>
    </form>
    <h2>Changed files · {d.count}</h2>
    {d.files.map((f, i) => (
      <details key={f.path} open={i === 0}>
        <summary>
          {changes.get(f.change) ?? f.change} · {f.path}
        </summary>
        {f.notice === undefined ? (
          <div className="compare-pair">
            <Source parts={f.prior} label="Prior" />
            <Source parts={f.current} label="Current" />
          </div>
        ) : (
          <p>{f.notice}</p>
        )}
      </details>
    ))}
    {d.count === 0 && <p>No source changes in {d.project.folder}.</p>}
    {d.count > d.files.length && (
      <p>Showing the first {d.files.length} changed files.</p>
    )}
    <h2>Retained results</h2>
    <form>
      <div className="compare-pair">
        {d.sides.map((side) => (
          <Result key={side.label} side={side} project={d.project} />
        ))}
      </div>
      {d.sides.some((s) => s.run_id !== null) && (
        <button type="submit">Compare selected runs</button>
      )}
    </form>
    <Version result={d.comparison} />
  </>
);

/** @returns The evidence document at its canonical author URL. */
export default function Compare() {
  return <EvidencePage screen={Screen} />;
}
