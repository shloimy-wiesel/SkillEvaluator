import { useEffect, useState } from "react";

import { api, messageOf } from "@/lib/studio-api";

/**
 * @param status - Saved worker status.
 * @returns Whether the worker may still update this record.
 */
export const isActive = (status: string) =>
  status === "queued" || status === "running";

const afterInterval = (read: () => Promise<void>, delay = 1000) =>
  window.setTimeout(() => {
    void read();
  }, delay);

/**
 * @param initial - First successful read of the view.
 * @param path - Project-scoped endpoint.
 * @param pending - Determines whether this view contains active work.
 * @returns The latest run view, with at most one read in flight.
 */
export const useActiveRuns = <T>(
  initial: T,
  path: string,
  pending: (data: T) => boolean
) => {
  const [data, setData] = useState(initial);
  const [problem, setProblem] = useState("");
  const active = pending(data);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;

    const refresh = async () => {
      try {
        const next = await api<T>(path, { signal: controller.signal });

        if (!controller.signal.aborted) {
          setData(next);
          setProblem("");

          if (pending(next)) {
            timer = afterInterval(refresh);
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setProblem(messageOf(error));
          timer = afterInterval(refresh, 2000);
        }
      }
    };

    if (active) {
      timer = afterInterval(refresh);
    }

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [active, path, pending]);

  return { data, problem, active };
};
