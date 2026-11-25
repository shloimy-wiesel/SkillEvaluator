"use client";

import { useSyncExternalStore } from "react";

import { Assets } from "@/components/assets/workspace";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const assetUrl = () => window.location.href;
const serverId = () => "";

/** @returns Evaluation assets for the canonical ASGI pathname. */
export const AssetDocument = () => {
  const href = useSyncExternalStore(subscribe, assetUrl, serverId);

  if (!href) {
    return <output>Opening assets…</output>;
  }

  const url = new URL(href);

  return (
    <Assets
      projectId={url.pathname.split("/")[2] ?? ""}
      pushedRevision={url.searchParams.get("pushed")}
    />
  );
};
