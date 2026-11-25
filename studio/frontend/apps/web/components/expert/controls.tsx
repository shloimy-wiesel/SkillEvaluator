"use client";

import { useId, useState } from "react";
import type { ReactNode, SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";

interface ChoiceProps {
  name: string;
  label: string;
  values: readonly string[];
  multiple?: boolean;
  placeholder?: string;
  captions?: readonly string[];
  required?: boolean;
}

/** @returns An omission-aware choice of evaluator settings. */
export const Choice = ({
  name,
  label,
  values,
  multiple = false,
  placeholder = "Evaluator default",
  captions,
  required,
}: ChoiceProps) => {
  const id = useId();

  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select id={id} name={name} multiple={multiple} required={required}>
        {!multiple && placeholder && <option value="">{placeholder}</option>}
        {values.map((value, i) => (
          <option key={value} value={value}>
            {captions?.[i] ?? value}
          </option>
        ))}
      </select>
    </div>
  );
};

interface InputProps {
  name: string;
  label: string;
  initial?: string;
  required?: boolean;
  min?: number;
  max?: number;
  step?: string;
}

/** @returns A labeled text or numeric input. */
export const Input = ({
  name,
  label,
  initial,
  required,
  min,
  max,
  step,
}: InputProps) => (
  <label>
    {label}
    <input
      name={name}
      defaultValue={initial}
      required={required}
      type={min === undefined ? "text" : "number"}
      min={min}
      max={max}
      step={step}
    />
  </label>
);

/** @returns A flag omitted until selected. */
export const Flag = ({
  name,
  label,
  value = "true",
}: {
  name: string;
  label: string;
  value?: string;
}) => (
  <label>
    <input type="checkbox" name={name} value={value} />
    {label}
  </label>
);

const listKeys = new Set(["agents", "checks", "skip", "harness", "reports"]);
const linesKeys = new Set(["skills", "exclude", "kata_dns"]);

const draftState = () => {
  const state: unknown = window.history.state;

  return state instanceof Object ? state : {};
};

const remember = (path: string, form: HTMLFormElement) => {
  const fields = new URLSearchParams();

  for (const [name, value] of new FormData(form)) {
    if (!(value instanceof File)) {
      fields.append(name, value);
    }
  }

  const state = draftState();
  window.history.replaceState(
    // oxlint-disable-next-line typescript/no-misused-spread -- Copy the current entry's own navigation metadata.
    { ...state, studioQueueDraft: { path, fields: fields.toString() } },
    ""
  );
};

const restore = (form: HTMLFormElement | null) => {
  if (!form) {
    return;
  }

  const state = draftState();
  const draft = "studioQueueDraft" in state ? state.studioQueueDraft : null;

  if (
    !(draft instanceof Object) ||
    !("path" in draft) ||
    draft.path !== form.dataset.queuePath
  ) {
    return;
  }

  // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Validate the serialized browser history entry before reading it.
  if (!("fields" in draft) || typeof draft.fields !== "string") {
    return;
  }

  const fields = new URLSearchParams(draft.fields);
  const revision = form.elements.namedItem("sha");

  if (
    revision instanceof HTMLInputElement &&
    revision.type === "hidden" &&
    fields.get("sha") !== revision.value
  ) {
    return;
  }

  for (const element of form.elements) {
    if (element instanceof HTMLSelectElement) {
      const selected = new Set(fields.getAll(element.name));

      for (const option of element.options) {
        option.selected = selected.has(option.value);
      }
    } else if (
      element instanceof HTMLInputElement &&
      element.type === "checkbox"
    ) {
      element.checked = fields.has(element.name, element.value);
    } else if (
      element instanceof HTMLTextAreaElement ||
      element instanceof HTMLInputElement
    ) {
      element.value = fields.get(element.name) ?? element.defaultValue;
    }
  }
};

const formPayload = (form: HTMLFormElement) => {
  const data = new FormData(form);
  const entries = new Map<string, string | string[]>();
  const versions: string[] = [];

  for (const [key, value] of data) {
    if (value === "" || value instanceof File) {
      continue;
    }

    if (key.startsWith("version_")) {
      versions.push(`${key.slice(8)}=${value}`);
    } else if (listKeys.has(key)) {
      entries.set(key, data.getAll(key).map(String));
    } else if (linesKeys.has(key)) {
      entries.set(key, value.split(/\r?\n/u));
    } else {
      entries.set(key, value);
    }
  }

  if (versions.length) {
    entries.set("harness_versions", versions);
  }

  return Object.fromEntries(entries);
};

/** @returns A JSON queue form retaining entered settings when validation fails. */
export const QueueForm = ({
  path,
  children,
  label,
}: {
  path: string;
  children: ReactNode;
  label: string;
}) => {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const body = JSON.stringify(formPayload(form));
    setBusy(true);
    setProblem("");

    try {
      const { run_id: runId } = await api<{ run_id: string }>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });

      remember(path, form);
      window.location.assign(`/projects/${path.split("/")[2]}/runs/${runId}`);
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return (
    <form
      ref={restore}
      data-queue-path={path}
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      {children}
      {problem && <p role="alert">{problem}</p>}
      <button type="submit" disabled={busy}>
        {label}
      </button>
    </form>
  );
};
