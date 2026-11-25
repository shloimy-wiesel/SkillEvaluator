/* oxlint-disable shadcn/no-unknown-classes -- The shared Studio stylesheet defines panel. */
import { Action, Pretty, Toggle } from "./fields";
import type { Candidate, DatasetView } from "./model";

const ReviewCase = ({ candidate }: { candidate: Candidate }) => {
  const { id, prompt, observed, files, redactions, warnings, review } =
    candidate;

  return (
    <article>
      <h3>{prompt}</h3>
      <p>
        {id} · {observed.outcome}
      </p>
      <details>
        <summary>Observed evidence and redactions</summary>
        <Pretty value={observed} />
        <p>Fixtures: {files.join(", ") || "None"}</p>
        <p>Redactions: {JSON.stringify(redactions)}</p>
        <p>{warnings.join("; ")}</p>
        <p>
          Suggested assertions:{" "}
          {review.suggested_assertions.join("; ") || "None"}
        </p>
      </details>
      <label>
        Review decision
        <select name={`decision_${id}`} defaultValue={review.decision}>
          <option value="pending">Pending</option>
          <option value="reject">Reject</option>
          <option value="accept">Accept independent expectation</option>
          <option value="accept_observed">
            Accept successful observed output
          </option>
        </select>
      </label>
      <label>
        Reviewer expectation
        <textarea
          name={`expected_${id}`}
          defaultValue={review.expected_output}
        />
      </label>
      <label>
        Reviewer assertions
        <textarea
          name={`assertions_${id}`}
          defaultValue={review.assertions.join("\n")}
        />
      </label>
    </article>
  );
};

/** @returns Upload, evidence and explicit trace acceptance controls. */
export const Traces = ({ view }: { view: DatasetView }) => {
  const { sample, review, trace_checks: checks } = view;

  return (
    <section className="panel">
      <h2>Trace review</h2>
      <details>
        <summary>Import traces</summary>
        <p>
          Sensitive fields are redacted before review. Candidates start pending.
        </p>
        <form>
          <label>
            Trace export
            <input type="file" name="export" required accept=".json,.jsonl" />
          </label>
          <Toggle name="force_import" label="Replace existing review" />
          <Toggle name="dry_import" label="Dry run (preview only)" />
          <Action value="import">Import for review</Action>
        </form>
      </details>
      {sample !== undefined && sample !== null && (
        <Pretty value={sample} label="Import preview" />
      )}
      {review && (
        <>
          <h3>Review candidates</h3>
          <p>
            Only accepted cases enter the dataset. Observed output requires a
            successful trace.
          </p>
          <form>
            {review.candidates.map((candidate) => (
              <ReviewCase key={candidate.id} candidate={candidate} />
            ))}
            {review.skipped.length > 0 && (
              <details>
                <summary>Skipped records ({review.skipped.length})</summary>
                <Pretty value={review.skipped} />
              </details>
            )}
            <Toggle
              name="allow_native"
              label="Allow acceptance for native Harbor tasks"
              checked={view.allow_native}
            />
            <Action value="preview_accept">Preview acceptance</Action>
            <Action value="accept">Stage accepted cases</Action>
          </form>
          {checks?.map((check) => (
            <p key={check.message}>
              {check.status} · {check.message}
            </p>
          ))}
        </>
      )}
    </section>
  );
};
