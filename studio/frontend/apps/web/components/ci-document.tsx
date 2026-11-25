"use client";

import { useState, useSyncExternalStore } from "react";
import type { ComponentType, SubmitEvent } from "react";

import { api, messageOf, useResource } from "@/lib/studio-api";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);

  return () => {
    window.removeEventListener("popstate", listener);
  };
};

const route = () => window.location.pathname + window.location.search;
const empty = () => "";

interface ScreenProps<T> {
  data: T;
  path: string;
}

const Loaded = <T,>({
  path,
  Screen,
}: {
  path: string;
  Screen: ComponentType<ScreenProps<T>>;
}) => {
  const { data, error } = useResource<T>(path);

  if (error !== undefined) {
    return <p role="alert">{error}</p>;
  }

  return data === undefined ? (
    <output>Loading…</output>
  ) : (
    <Screen path={path.split("?")[0] ?? path} data={data} />
  );
};

/** @returns the exported document at its project-scoped ASGI URL. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export const CIDocument = <T,>({
  screen,
}: {
  screen: ComponentType<ScreenProps<T>>;
}) => {
  const path = useSyncExternalStore(subscribe, route, empty);

  return path ? (
    <Loaded path={path} Screen={screen} />
  ) : (
    <output>Opening project…</output>
  );
};

interface Publication {
  location: string;
}

const download = async (target: string, request: RequestInit) => {
  const response = await fetch(`/api/v1${target}`, request);

  if (!response.ok) {
    throw new Error(
      "The reviewed plan is no longer available. Review the files and options again."
    );
  }

  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "ci-plan.json";
  link.click();
  URL.revokeObjectURL(url);
};

/**
 * @param path - The scoped project endpoint.
 * @returns Submission state and the validated response.
 */
// oxlint-disable-next-line typescript/no-unnecessary-type-parameters -- The caller declares its mutation response model.
export const useCIAction = <T extends object>(path: string) => {
  const [result, setResult] = useState<T>();
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = event.nativeEvent.submitter;

    if (!(button instanceof HTMLButtonElement)) {
      return;
    }

    const values = new FormData(form, button);
    const target = path + (button.dataset.suffix ?? "");

    const request = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(values)),
    };

    setBusy(true);
    setProblem("");

    try {
      if (button.value === "receipt") {
        await download(target, request);
      } else {
        const response = await api<T | Publication>(target, request);

        if ("location" in response) {
          window.location.assign(response.location);

          return;
        }

        setResult(response);

        if (button.dataset.suffix === "/token") {
          form.reset();
        }
      }
    } catch (error) {
      setResult(undefined);
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return {
    result,
    problem,
    busy,
    onSubmit: (event: SubmitEvent<HTMLFormElement>) => {
      void submit(event);
    },
  };
};
