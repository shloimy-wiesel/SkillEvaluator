"use client";

import { useEffect, useState } from "react";

/** Public repository coordinates, without transport credentials. */
export interface Project {
  id: string;
  name: string;
  remote: string;
  folder: string;
  branch: string;
  revision: string;
}

/**
 * @param error - Caught exception.
 * @returns An inline diagnostic.
 */
// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Catch variables have unknown type.
export const messageOf = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Studio could not complete the request.";

// oxlint-disable-next-line anti-slop/no-unknown-parameters, anti-slop/no-unsafe-dictionary-type -- JSON from HTTP is untrusted.
const isRecord = (value: unknown): value is Record<string, unknown> =>
  // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Parse the error envelope at the HTTP boundary.
  typeof value === "object" && value !== null;

/**
 * @param path - Path relative to the versioned API root.
 * @param options - Fetch options for this request.
 * @returns The response model validated by the endpoint.
 */
export const api = async <T>(path: string, options?: RequestInit) => {
  const response = await fetch(`/api/v1${path}`, {
    cache: "no-store",
    ...options,
  });

  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);

    if (isRecord(payload) && isRecord(payload.detail)) {
      const { message } = payload.detail;

      // oxlint-disable-next-line anti-slop/no-runtime-typeof -- Parse the server error at the HTTP boundary.
      if (typeof message === "string") {
        throw new TypeError(message);
      }
    }

    throw new Error(`Studio request failed (${response.status}).`);
  }

  // SAFETY: FastAPI validates successful responses against the same-origin endpoint model.
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion, anti-slop/require-safety-comment-for-type-assertion -- Typed JSON boundary.
  return (await response.json()) as T;
};

/**
 * @param path - Path relative to the versioned API root.
 * @returns The loaded data or diagnostic, empty while loading.
 */
// oxlint-disable-next-line typescript/no-unnecessary-type-parameters -- The caller specifies its endpoint’s response model.
export const useResource = <T>(path: string) => {
  const [result, setResult] = useState<{ data?: T; error?: string }>({});
  // oxlint-disable-next-line react-doctor/no-fetch-in-effect, react-doctor/no-set-state-after-await-in-effect -- Static export: abort on cleanup and gate both writes on the signal.
  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      try {
        const data = await api<T>(path, { signal: controller.signal });

        if (!controller.signal.aborted) {
          setResult({ data });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setResult({ error: messageOf(error) });
        }
      }
    };

    void load();

    return () => {
      controller.abort();
    };
  }, [path]);

  return result;
};
