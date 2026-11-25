"use client";

import { useSyncExternalStore } from "react";
import type { ComponentType } from "react";

import { useResource } from "@/lib/studio-api";
import type { Project } from "@/lib/studio-api";

import { score } from "./model";
import type { Choice, Comparison } from "./model";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const browserPath = () => window.location.pathname + window.location.search;
const serverPath = () => "";

interface View {
  project: Project;
}

interface ScreenProps<T extends View> {
  screen: ComponentType<{ data: T }>;
}

const Load = <T extends View>({
  screen: Screen,
  path,
}: ScreenProps<T> & { path: string }) => {
  const { data, error } = useResource<T>(path);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <output>Loading evidence…</output>;
  }

  return (
    <>
      <nav aria-label="Breadcrumb">
        <a href={`/projects/${data.project.id}`}>{data.project.name}</a>
      </nav>
      <Screen data={data} />
    </>
  );
};

/** @returns A scoped evidence screen for the current author URL. */
// oxlint-disable-next-line sonarjs/function-name -- React component.
export const EvidencePage = <T extends View>({ screen }: ScreenProps<T>) => {
  const path = useSyncExternalStore(subscribe, browserPath, serverPath);

  return path ? (
    <Load path={path} screen={screen} />
  ) : (
    <output>Opening evidence…</output>
  );
};

/** @returns A labeled filter or selection control. */
export const Select = ({
  name,
  label,
  value,
  options,
  multiple = false,
}: {
  name: string;
  label: string;
  value: string | string[];
  options: Choice[];
  multiple?: boolean;
}) => (
  <div>
    <label htmlFor={name}>{label}</label>
    <select id={name} name={name} multiple={multiple} defaultValue={value}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  </div>
);

/** @returns Paired changes and the reasons evidence is unavailable. */
export const Version = ({ result }: { result: Comparison }) => (
  <section aria-label="Version comparison">
    <h2>Version comparison</h2>
    <p>
      {result.status === "available"
        ? "With-skill change"
        : "Comparison unavailable"}
    </p>
    {result.source_studio_run !== undefined && (
      <p>Prior evaluation: {result.source_studio_run}</p>
    )}
    {result.reasons.map((r) => (
      <p key={r}>{r}</p>
    ))}
    {Object.entries(result.agents ?? {}).map(([agent, v]) => (
      <p key={agent}>
        {agent}: {score(v.prior_overall)} → {score(v.current_overall)} (
        {score(v.delta, true)})
      </p>
    ))}
  </section>
);
