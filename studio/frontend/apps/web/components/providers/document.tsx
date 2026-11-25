/* oxlint-disable shadcn/no-unknown-classes, next/no-html-link-for-pages, react-doctor/nextjs-no-a-element -- ASGI owns browser navigation and the Studio stylesheet. */
"use client";

import { useSyncExternalStore } from "react";

import { useResource } from "@/lib/studio-api";

import { ProfilePanel } from "./profile-panel";
import { Readiness } from "./readiness";

/** Independently persisted inference roles. */
export type Role = "chat" | "embeddings";

/** Saved settings safe to display; credentials are write-only. */
export interface Profile {
  provider: string;
  base_url: string;
  model: string;
  has_key: boolean;
}

/** Project-specific profile settings and installed readiness options. */
export interface ProviderView {
  project_name: string;
  profiles: Record<Role, Profile>;
  choices: Record<Role, string[]>;
  scanners: string[];
  runtime_agents: string[];
  modes: string[];
}

const Providers = ({ id }: { id: string }) => {
  const path = `/projects/${id}/providers`;
  const { data, error } = useResource<ProviderView>(path);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  if (!data) {
    return <output>Loading provider settings…</output>;
  }

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href="/">Projects</a> /{" "}
        <a href={`/projects/${id}`}>{data.project_name}</a> /{" "}
        <span aria-current="page">Provider settings</span>
      </nav>
      <h1>Provider settings</h1>
      <p>Chat and embedding requests use separate profiles for this project.</p>
      <ProfilePanel
        role="chat"
        initial={data.profiles.chat}
        choices={data.choices.chat}
        path={`${path}/chat`}
      />
      <ProfilePanel
        role="embeddings"
        initial={data.profiles.embeddings}
        choices={data.choices.embeddings}
        path={`${path}/embeddings`}
      />
      <Readiness path={path} data={data} />
    </>
  );
};

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const projectId = () => window.location.pathname.split("/")[2] ?? "";
const serverId = () => "";

/** @returns The provider workspace at its canonical project URL. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export const ProviderDocument = () => {
  const id = useSyncExternalStore(subscribe, projectId, serverId);

  return id ? (
    <Providers id={id} />
  ) : (
    <output>Opening provider settings…</output>
  );
};
