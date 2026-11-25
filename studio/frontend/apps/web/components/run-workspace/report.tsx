/* oxlint-disable shadcn/no-unknown-classes -- The Studio stylesheet owns the shared panel class. */
interface Finding {
  severity: string;
  message: string;
  file_path?: string;
  suggestion?: string;
}

interface Result {
  validator: string;
  status: string;
  skip_reason?: string;
  incomplete_scans?: string[];
  legacy?: { errors?: string[]; warnings?: string[] };
  findings?: Finding[];
}

/** Public evaluator report fields used in retained run views. */
export interface Report {
  output?: string;
  diagnostics?: { level: string; paths: number; skills: number };
  tier3?: { verdict?: string; execution_status: string; summary?: object };
  execution_errors?: string[];
  diagnostic?: string;
  status?: string;
  cases?: number;
  split?: string;
  coverage?: { cases: number; attempts: number };
  qualification?: { policy_id: string; status: string; reasons: string[] };
  workflow?: { stages: Record<string, { status: string; reason?: string }> };
  results?: Result[];
  studio_dataset?: string;
  studio_member_datasets?: Record<string, string>;
  summary_path?: string;
  skills?: {
    name: string;
    passed: boolean;
    tier3?: { status: string; blocking: boolean };
  }[];
  terminal?: string;
  native?: Record<string, string>;
  studio_artifacts?: string[];
}

const Grader = ({ report, evidence }: { report: Report; evidence: string }) => (
  <>
    <p>{report.diagnostic}</p>
    {report.status === "valid" && (
      <p>
        Suite valid: {report.cases} {report.split} cases.
      </p>
    )}
    {report.coverage && (
      <>
        <p>
          {report.coverage.cases} cases · {report.coverage.attempts} attempts
        </p>
        <a href={evidence}>Download attempt evidence</a>
      </>
    )}
    {report.qualification && (
      <>
        <h3>
          Policy {report.qualification.policy_id}: {report.qualification.status}
        </h3>
        <ul>
          {report.qualification.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </>
    )}
    <details>
      <summary>Qualification evidence</summary>
      <pre>{JSON.stringify(report, null, 2)}</pre>
    </details>
  </>
);

const Checks = ({ result, overlap }: { result: Result; overlap: boolean }) => (
  <section className="panel">
    <h3>
      {result.validator} · {result.status}
    </h3>
    <p>{result.skip_reason}</p>
    {Boolean(result.incomplete_scans?.length) && (
      <p>Incomplete: {result.incomplete_scans?.join(", ")}</p>
    )}
    {overlap &&
      [
        ...(result.legacy?.errors ?? []),
        ...(result.legacy?.warnings ?? []),
      ].map((message) => <p key={message}>{message}</p>)}
    {result.findings?.map((finding) => (
      <p key={`${finding.file_path}:${finding.message}`}>
        <b>{finding.severity}</b> {finding.message}
        <br />
        {finding.file_path}
        <br />
        {finding.suggestion}
      </p>
    ))}
  </section>
);

const Expert = ({ report, files }: { report: Report; files: string }) => (
  <>
    <p>{report.studio_dataset}</p>
    {Object.entries(report.studio_member_datasets ?? {}).map(([name, note]) => (
      <p key={name}>
        {name}: {note}
      </p>
    ))}
    {report.summary_path === "catalog-summary.json" && (
      <ul>
        {report.skills?.map((skill) => (
          <li key={skill.name}>
            {skill.name}: gate {skill.passed ? "passed" : "failed"}
            {skill.tier3 &&
              ` · Tier 3 ${skill.tier3.status} (${skill.tier3.blocking ? "blocking" : "advisory"})`}
          </li>
        ))}
      </ul>
    )}
    {Boolean(report.terminal) && (
      <details>
        <summary>Evaluator output</summary>
        <pre>{report.terminal}</pre>
      </details>
    )}
    {Object.entries(report.native ?? {}).map(([name, label]) => (
      <p key={name}>
        <a
          href={`${files}/${name.split("/").map(encodeURIComponent).join("/")}`}
        >
          Download native {label}
        </a>
      </p>
    ))}
  </>
);

/** @returns Inert report text and attachment downloads. */
export const Findings = ({
  report,
  kind,
  markdown,
  base,
  id,
}: {
  report: Report;
  kind: string;
  markdown: string;
  base: string;
  id: string;
}) => (
  <>
    <h2>Results</h2>
    {kind === "changed-files-v1" && (
      <>
        <h3>Changed-file results</h3>
        <section aria-label="Check output">
          <pre>{report.output}</pre>
        </section>
      </>
    )}
    {kind === "external-metrics-v1" && (
      <p>
        External observations · SkillEvaluator did not execute these tests or
        verify their source claims.
      </p>
    )}
    {[
      "external-metrics-v1",
      "select-decoys-v1",
      "skill-interaction-v1",
    ].includes(kind) && <pre>{markdown}</pre>}
    {report.tier3 && (
      <>
        <p>
          Tier 3 verdict: {report.tier3.verdict ?? "unavailable"} · Execution:{" "}
          {report.tier3.execution_status}
        </p>
        {report.tier3.summary && (
          <details>
            <summary>Evaluation summary</summary>
            <pre>{JSON.stringify(report.tier3.summary, null, 2)}</pre>
          </details>
        )}
      </>
    )}
    {report.execution_errors?.map((reason) => (
      <p key={reason}>{reason}</p>
    ))}
    {kind === "validate-grader" && (
      <Grader report={report} evidence={`${base}/assets/evidence/${id}`} />
    )}
    {Object.entries(report.workflow?.stages ?? {}).map(([stage, detail]) => (
      <p key={stage}>
        {stage}: {detail.status}
        {Boolean(detail.reason) && ` — ${detail.reason}`}
      </p>
    ))}
    {report.results?.map((result) => (
      <Checks
        key={result.validator}
        result={result}
        overlap={kind === "tier2-overlap-v1"}
      />
    ))}
    {kind === "expert-check-v1" ? (
      <Expert report={report} files={`${base}/expert/artifacts/${id}`} />
    ) : (
      <>
        <h2>Exports</h2>
        <a href={`${base}/runs/${id}/exports/json`}>Download JSON</a> ·{" "}
        <a href={`${base}/runs/${id}/exports/md`}>Download Markdown</a>
        {Boolean(report.studio_artifacts?.length) && (
          <>
            <h2>Run files</h2>
            <ul>
              {report.studio_artifacts?.map((name) => (
                <li key={name}>
                  <a
                    href={`${base}/overlap/${id}/files/${encodeURIComponent(name)}`}
                  >
                    {name}
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
      </>
    )}
  </>
);
