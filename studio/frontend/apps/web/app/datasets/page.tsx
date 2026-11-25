"use client";

import { useSyncExternalStore } from "react";

import { DatasetEditor } from "@/components/datasets/editor";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const pathname = () => window.location.pathname + window.location.search;
const serverPath = () => "";

/** @returns The dataset workbench for this project and draft deep link. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export default function Page() {
  const path = useSyncExternalStore(subscribe, pathname, serverPath);

  return path ? (
    <DatasetEditor key={path} path={path} />
  ) : (
    <output>Opening datasets…</output>
  );
}
