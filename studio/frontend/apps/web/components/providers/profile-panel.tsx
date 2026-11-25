/* oxlint-disable shadcn/no-unknown-classes -- Studio provides the shared panel stylesheet. */
import { useState } from "react";
import type { SubmitEvent } from "react";

import { api, messageOf } from "@/lib/studio-api";

import type { Profile, Role } from "./document";

interface Discovery {
  notice: string;
  models: string[];
}

/** @returns An independent, write-only profile editor for one inference role. */
export const ProfilePanel = ({
  role,
  path,
  initial,
  choices,
}: {
  role: Role;
  path: string;
  initial: Profile;
  choices: string[];
}) => {
  const [profile, setProfile] = useState(initial);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [discovery, setDiscovery] = useState<Discovery>();

  const save = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setProblem("");
    setDiscovery(undefined);
    setBusy(true);

    try {
      const saved = await api<Profile>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...Object.fromEntries(values),
          clear: values.has("clear"),
        }),
      });

      setProfile(saved);
      setRevision((value) => value + 1);
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  const check = async () => {
    setBusy(true);
    setDiscovery(undefined);
    setProblem("");

    try {
      setDiscovery(await api<Discovery>(`${path}/check`, { method: "POST" }));
    } catch (error) {
      setProblem(messageOf(error));
    }

    setBusy(false);
  };

  return (
    <section className="panel" aria-labelledby={role}>
      <h2 id={role}>{role === "chat" ? "Chat" : "Embeddings"}</h2>
      <form
        method="post"
        key={revision}
        onSubmit={(event) => {
          void save(event);
        }}
      >
        <fieldset disabled={busy}>
          <label htmlFor={`${role}-provider`}>Provider</label>
          <select
            name="provider"
            id={`${role}-provider`}
            defaultValue={profile.provider}
          >
            {choices.map((choice) => (
              <option key={choice}>{choice}</option>
            ))}
          </select>
          <label htmlFor={`${role}-base`}>Base URL</label>
          <input
            id={`${role}-base`}
            type="url"
            name="base_url"
            defaultValue={profile.base_url}
            placeholder="https://gateway.example/v1"
          />
          <p>
            Private gateways require an HTTPS URL. Leave blank for the native
            provider default.
          </p>
          <label htmlFor={`${role}-model`}>Model</label>
          <input
            id={`${role}-model`}
            name="model"
            defaultValue={profile.model}
            placeholder="Provider default"
          />
          <label htmlFor={`${role}-key`}>API key</label>
          <input
            id={`${role}-key`}
            type="password"
            name="key"
            autoComplete="new-password"
          />
          <p>{profile.has_key ? "Key stored" : "No key stored"}</p>
          <p>
            A blank key keeps the saved key only for the same provider and base
            URL. Bedrock uses the worker’s AWS identity.
          </p>
          <label>
            <input type="checkbox" name="clear" /> Remove stored key
          </label>
          <button type="submit">Save settings</button>
        </fieldset>
      </form>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          void check();
        }}
      >
        Check readiness and discover models
      </button>
      {problem && <p role="alert">{problem}</p>}
      {discovery && (
        <>
          <output>{discovery.notice}</output>
          {discovery.models.length > 0 && (
            <ul aria-label="Discovered models">
              {discovery.models.map((model) => (
                <li key={model}>{model}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
};
