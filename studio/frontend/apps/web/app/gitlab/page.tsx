"use client";

import { CIDocument, useCIAction } from "@/components/ci-document";

interface Access {
  root: string;
  namespace: string;
  web_url: string;
}

const GitLab = ({ data, path }: { data: Access; path: string }) => {
  const { result, problem, busy, onSubmit } = useCIAction<{ notice: string }>(
    path
  );

  return (
    <>
      <a href={path.slice(0, -7)}>Project overview</a>
      <h1>GitLab access</h1>
      <p>
        Installation: <code>{data.root}</code> · Project:{" "}
        <code>{data.namespace}</code>
      </p>
      {result && <output>{result.notice}</output>}
      {problem && <p role="alert">{problem}</p>}
      <form onSubmit={onSubmit}>
        <label htmlFor="api-token">GitLab API token</label>
        <input
          type="password"
          autoComplete="new-password"
          id="api-token"
          name="api_token"
        />
        <p>
          Use read_api for status, or api for write operations. Git repository
          access is configured separately. Saving an empty token removes API
          access.
        </p>
        <button disabled={busy} data-suffix="/token" type="submit">
          Save API token
        </button>
      </form>
      <form onSubmit={onSubmit}>
        <button disabled={busy} type="submit" data-suffix="/check">
          Check project API access
        </button>
      </form>
      <p>
        <a href={`${data.web_url}/-/merge_requests`}>Merge requests</a> ·{" "}
        <a href={`${data.web_url}/-/pipelines`}>Pipeline status</a>
      </p>
    </>
  );
};

/** @returns Project GitLab credentials and connectivity. */
export default function Page() {
  return <CIDocument screen={GitLab} />;
}
