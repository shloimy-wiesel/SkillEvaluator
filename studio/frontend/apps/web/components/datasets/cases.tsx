/* oxlint-disable shadcn/no-unknown-classes, anti-slop/no-runtime-typeof -- Studio defines panel. Only edit fields whose authored JSON type matches the control. */
import { Action, Pretty } from "./fields";
import type { DatasetCase, DatasetView, Json } from "./model";

const strings = (field: Json | undefined): field is string[] =>
  Array.isArray(field) && field.every((item) => typeof item === "string");

const CaseFields = ({
  entry,
  index,
  retry,
}: {
  entry: DatasetCase;
  index: number;
  retry?: FormData;
}) => {
  const prior = (field: string, fallback: string) => {
    const value = retry?.get(field);

    return typeof value === "string" ? value : fallback;
  };

  const { assertions = [], files = [], should_trigger: trigger } = entry;

  const triggerValue = trigger === true ? "yes" : "no";

  return (
    <form>
      <input type="hidden" name="index" value={index} />
      <label>
        Case ID
        <input
          required
          name="case_id"
          defaultValue={prior("case_id", String(entry.id ?? ""))}
        />
      </label>
      {(
        [
          ["prompt", "Prompt"],
          ["expected_output", "Expected output"],
        ] as const
      ).map(([name, label]) => {
        const value = entry[name];

        return typeof value === "string" || value === undefined ? (
          <div key={name}>
            <label htmlFor={`${name}-${index}`}>{label}</label>
            <textarea
              id={`${name}-${index}`}
              required
              name={name}
              defaultValue={prior(name, value ?? "")}
            />
          </div>
        ) : (
          <div key={name}>
            {label} (structured value preserved)
            <Pretty value={value} />
          </div>
        );
      })}
      {strings(assertions) ? (
        <label>
          Assertions
          <textarea
            name="assertions"
            defaultValue={prior("assertions", assertions.join("\n"))}
          />
        </label>
      ) : (
        <>
          <p>Structured assertions preserved</p>
          <Pretty value={assertions} />
        </>
      )}
      {strings(files) && (
        <>
          <label>
            Fixture selection
            <select
              name="file_mode"
              defaultValue={prior(
                "file_mode",
                entry.files === undefined ? "inherit" : "explicit"
              )}
            >
              <option value="inherit">Inherit (omit files)</option>
              <option value="explicit">
                Explicit list (empty means no files)
              </option>
            </select>
          </label>
          <label>
            Fixture paths
            <textarea
              name="files"
              defaultValue={prior("files", files.join("\n"))}
            />
          </label>
        </>
      )}
      {(trigger === undefined || typeof trigger === "boolean") && (
        <label>
          Should this skill trigger?
          <select
            name="trigger"
            defaultValue={prior(
              "trigger",
              trigger === undefined ? "inherit" : triggerValue
            )}
          >
            <option value="inherit">Infer from expected skill</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
      )}
      {index < 0 ? (
        <Action value="add">Add case</Action>
      ) : (
        <>
          <Action value="update">Update case</Action>
          <Action value="remove">Remove case</Action>
        </>
      )}
    </form>
  );
};

/** @returns Dataset management and case editing controls. */
export const Cases = ({
  view,
  retry,
}: {
  view: DatasetView;
  retry?: FormData;
}) => {
  const { draft, editable } = view;

  if (!draft) {
    return null;
  }

  return (
    <section className="panel">
      <p>Working draft · {draft.revision.slice(0, 10)}</p>
      <h2>{draft.path}</h2>
      <details>
        <summary>Manage datasets</summary>
        <form>
          <label>
            Dataset file
            <select name="dataset" defaultValue={draft.path}>
              {draft.choices.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
          <Action value="switch">Switch dataset</Action>
        </form>
        <form>
          <label>
            New dataset name
            <input name="name" required pattern={"[A-Za-z0-9_\\-]+"} />
          </label>
          <Action value="create">Create dataset</Action>
        </form>
        {editable && (
          <form>
            <label>
              Skill identity
              <input
                name="identity"
                required
                defaultValue={editable.skill_name}
              />
            </label>
            <Action value="identity">Update identity</Action>
          </form>
        )}
      </details>
      {editable ? (
        <>
          {editable.evals.map((entry, index) => {
            const attempted =
              retry?.get("index") === String(index) ? retry : undefined;

            return (
              <article key={entry.id}>
                <h3>{entry.id}</h3>
                <p>
                  {typeof entry.prompt === "string"
                    ? entry.prompt
                    : JSON.stringify(entry.prompt)}
                </p>
                <details open={Boolean(attempted)}>
                  <summary>Edit case {entry.id}</summary>
                  <CaseFields entry={entry} index={index} retry={attempted} />
                </details>
              </article>
            );
          })}
          <details
            open={editable.evals.length === 0 || retry?.get("action") === "add"}
          >
            <summary>New case</summary>
            <CaseFields
              entry={{}}
              index={-1}
              retry={retry?.get("action") === "add" ? retry : undefined}
            />
          </details>
        </>
      ) : (
        <p>Legacy dataset · Preview migration to edit its cases.</p>
      )}
    </section>
  );
};
