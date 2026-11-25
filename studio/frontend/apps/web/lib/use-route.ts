"use client";

import { useSyncExternalStore } from "react";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const browserPath = () => window.location.pathname + window.location.search;
const serverPath = () => "";

/** @returns The project-scoped browser path and query after hydration. */
export const useRoute = () =>
  useSyncExternalStore(subscribe, browserPath, serverPath);
