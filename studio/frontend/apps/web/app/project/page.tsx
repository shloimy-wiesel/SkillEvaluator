"use client";

import { useSyncExternalStore } from "react";

import { ProjectOverview } from "@/components/project-overview";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const projectId = () => window.location.pathname.split("/")[2] ?? "";
const serverId = () => "";

/** @returns The overview for the canonical ASGI pathname. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export default function Page() {
  const id = useSyncExternalStore(subscribe, projectId, serverId);

  return id ? (
    <ProjectOverview projectId={id} />
  ) : (
    <output>Opening project…</output>
  );
}
