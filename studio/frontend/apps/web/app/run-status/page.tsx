"use client";

import { QueueForm, RunDocument } from "@/components/run-workspace/document";
import { Findings } from "@/components/run-workspace/report";
import type { Report } from "@/components/run-workspace/report";
import {
  isActive,
  useActiveRuns,
} from "@/components/run-workspace/use-active-runs";
import type { Project } from "@/lib/studio-api";

interface Status {
  project: Project;
  run: {
    id: string;
    kind: string;
    sha: string;
    status: string;
    progress: string;
    folder: string;
    options: Record<
      string,
      string | number | boolean | string[] | { provider: string; model: string }
    >;
    created: string;
    exit_code: number | null;
    markdown: string;
  };
  models: { judge: string; agents: string[] } | null;
  report: Report | null;
}

const pending = (view: Status) => isActive(view.run.status);

const RunStatus = ({ initial, path }: { initial: Status; path: string }) => {
  const { data, problem, active } = useActiveRuns(initial, path, pending);
  const { project, run, report, models } = data;
  // oxlint-disable-next-line react-doctor/no-unguarded-browser-global-in-render-or-hook-init -- RunDocument mounts its renderer only after client hydration.
  const base = `${window.location.origin}/projects/${project.id}`;
  const diag = report?.diagnostics;

  return (
    <>
      <a href={`${base}/runs`}>Evaluation runs</a>
      <h1>{run.kind}</h1>
      <details>
        <summary>Diagnostic detail</summary>
        <dl>
          <dt>Run ID</dt>
          <dd>{run.id}</dd>
          <dt>Queued (UTC)</dt>
          <dd>{run.created}</dd>
          <dt>Evaluator adapter</dt>
          <dd>{run.kind}</dd>
          <dt>Frozen commit</dt>
          <dd>{run.sha}</dd>
          <dt>Worker status</dt>
          <dd>{run.status}</dd>
          {diag && (
            <>
              <dt>Evaluator detail</dt>
              <dd>
                {diag.level} · {diag.paths} selected paths · {diag.skills}{" "}
                affected skills
              </dd>
            </>
          )}
        </dl>
      </details>
      <output>
        {run.status} · {run.progress}
      </output>
      {problem && <p role="alert">{problem} Retrying automatically.</p>}
      <dl>
        <dt>Commit</dt>
        <dd>
          <code>{run.sha}</code>
        </dd>
        <dt>Skill folder</dt>
        <dd>{run.folder}</dd>
        {models && (
          <>
            <dt>Saved chat / standard judge</dt>
            <dd>{models.judge}</dd>
            <dt>Live agent models</dt>
            {models.agents.map((agent) => (
              <dd key={agent}>{agent}</dd>
            ))}
          </>
        )}
        <dt>Configuration</dt>
        <dd>
          <code>{JSON.stringify(run.options)}</code>
        </dd>
        {run.exit_code !== null && (
          <>
            <dt>
              {[
                "select-decoys-v1",
                "external-metrics-v1",
                "skill-interaction-v1",
              ].includes(run.kind)
                ? "Command"
                : "Gate"}{" "}
              exit code
            </dt>
            <dd>{run.exit_code}</dd>
          </>
        )}
      </dl>
      {!active && run.kind === "tier3-live-v1" && (
        <p>
          <a href={`${base}/results/${run.id}`}>
            Review artifacts and feedback
          </a>{" "}
          · <a href={`${base}/results/${run.id}?agents=true`}>Compare agents</a>
        </p>
      )}
      {report && (
        <Findings
          report={report}
          markdown={run.markdown}
          kind={run.kind}
          base={base}
          id={run.id}
        />
      )}
      {!active && (
        <QueueForm
          path={`/projects/${project.id}/runs/${run.id}/rerun`}
          button="Rerun saved inputs"
        />
      )}
    </>
  );
};

const renderStatus = (data: Status, path: string) => (
  <RunStatus initial={data} path={path} />
);

/** @returns A revisitable immutable job document. */
export default function Page() {
  return <RunDocument render={renderStatus} />;
}
