"use client";

import { useState, useSyncExternalStore } from "react";
import type { ReactNode, SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const locationKey = () => window.location.pathname + window.location.search;
const serverLocation = () => "";

/** @returns The canonical Studio route after hydration. */
export const useRoute = () =>
  useSyncExternalStore(subscribe, locationKey, serverLocation);

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
}: ChoiceProps) => (
  <label>
    {label}
    <select name={name} multiple={multiple} required={required}>
      {!multiple && placeholder && <option value="">{placeholder}</option>}
      {values.map((value, i) => (
        <option key={value} value={value}>
          {captions?.[i] ?? value}
        </option>
      ))}
    </select>
  </label>
);

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
    const body = JSON.stringify(formPayload(event.currentTarget));
    setBusy(true);
    setProblem("");

    try {
      const { run_id: runId } = await api<{ run_id: string }>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });

      window.location.assign(`/projects/${path.split("/")[2]}/runs/${runId}`);
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return (
    <form
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
