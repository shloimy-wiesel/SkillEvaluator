/* oxlint-disable shadcn/no-unknown-classes, anti-slop/no-runtime-typeof -- The shared Studio stylesheet defines panel. Authored values can be strings or structured JSON. */
import { Action, Pretty, Toggle } from "./fields";
import type { DatasetView } from "./model";

/** @returns Validation, generation, collection and migration tools for a draft. */
export const Workbench = ({ view }: { view: DatasetView }) => {
  const { draft, validation, generated, migration } = view;

  return (
    <section className="panel">
      <h2>Dataset tools</h2>
      <form>
        <Toggle name="strict" label="Treat warnings as failures" />
        <Toggle name="harbor_contract" label="Check Harbor contract" />
        <Action value="validate">Validate draft</Action>
      </form>
      {validation && (
        <section aria-label="Validation results">
          <h3>{validation.passed ? "Passed" : "Failed"}</h3>
          <ul>
            {validation.checks.map((check) => (
              <li key={`${check.path}:${check.message}`}>
                <b>
                  {check.status} · {check.path}
                </b>{" "}
                {check.message}
              </li>
            ))}
          </ul>
          <details>
            <summary>JSON results</summary>
            <Pretty value={validation.checks} />
          </details>
        </section>
      )}
      <details>
        <summary>Generate cases</summary>
        <p>
          Preview cases for evals/evals.json using the saved chat profile or
          local templates.
        </p>
        <form>
          <label>
            Grounding
            <select name="grounding">
              {["auto", "skill", "intent", "trace"].map((mode) => (
                <option key={mode}>{mode}</option>
              ))}
            </select>
          </label>
          <Toggle name="no_llm" label="Use local templates" />
          <Toggle name="full" label="Generate full bucket set" />
          <Toggle name="force" label="Overwrite existing cases" />
          <Toggle name="refine" label="Refine with retained trajectories" />
          <label>
            Author guidance file (optional)
            <input name="prompt" />
          </label>
          <label>
            Completed results folder (optional)
            <input name="from_results" />
          </label>
          <label>
            Results root (optional)
            <input name="results_dir" />
          </label>
          <Action value="generate">Generate preview</Action>
        </form>
      </details>
      <h3>Collect a trajectory</h3>
      <p>
        Run one committed case at this draft’s revision using the saved chat
        profile, standard grader and an isolated Docker sandbox. Return to this
        draft to preview refinement.
      </p>
      <form>
        <Toggle name="sandbox_consent" label="Allow one paid sandbox trial" />
        <Action value="collect">Collect trajectory</Action>
      </form>
      {draft?.collection !== undefined && (
        <>
          <a href={`/projects/${view.project.id}/runs/${draft.collection}`}>
            Collection run
          </a>
          <form>
            <Action value="refine_collected">
              Preview collected refinement
            </Action>
          </form>
        </>
      )}
      {generated && (
        <>
          <h3>Generated preview</h3>
          {generated.evals.map((entry) => (
            <article key={entry.id}>
              <b>{entry.id}</b>
              <p>
                {typeof entry.prompt === "string"
                  ? entry.prompt
                  : JSON.stringify(entry.prompt)}
              </p>
              <p>
                {typeof entry.expected_output === "string"
                  ? entry.expected_output
                  : JSON.stringify(entry.expected_output)}
              </p>
            </article>
          ))}
          <details>
            <summary>All generated fields</summary>
            <Pretty value={generated} />
          </details>
          <form>
            <Action value="use_generation">Use generated cases</Action>
          </form>
        </>
      )}
      <details>
        <summary>Migrate dataset</summary>
        <p>
          Convert the active file without changing the source. Leave destination
          blank to preview.
        </p>
        <form>
          <label>
            Target skill identity (optional)
            <input name="skill_name" />
          </label>
          <label>
            New destination (optional)
            <input name="destination" placeholder="evals/evals.json" />
          </label>
          <Action value="migrate">Run migration</Action>
        </form>
      </details>
      {migration !== undefined && (
        <Pretty label="Migration preview" value={migration} />
      )}
    </section>
  );
};
