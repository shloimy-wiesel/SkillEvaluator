import { useEffect, useState } from "react";

import { api, messageOf } from "@/lib/studio-api";

/** @returns Whether the worker may still update this record. */
export const isActive = (status: string) =>
  status === "queued" || status === "running";

/** @returns The latest run view. Only poll while work is active, with at most one read in flight. */
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
          if (pending(next)) {
            schedule();
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setProblem(messageOf(error));
        }
      }
    };
    function schedule() {
      timer = window.setTimeout(() => {
        void refresh();
      }, 1000);
    }
    if (active) {
      schedule();
    }
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [active, path, pending]);
  return { data, problem, active };
};
