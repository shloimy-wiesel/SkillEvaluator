"use client";

import { useSyncExternalStore } from "react";

import { SkillEditor } from "@/components/skill-editor";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const editorPath = () => window.location.href;
const serverPath = () => "";

/** @returns The editor at its project-scoped browser URL. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export default function Page() {
  const href = useSyncExternalStore(subscribe, editorPath, serverPath);

  if (!href) {
    return <output>Opening editor…</output>;
  }

  const url = new URL(href);

  return (
    <SkillEditor path={url.pathname} pushed={url.searchParams.get("pushed")} />
  );
}
