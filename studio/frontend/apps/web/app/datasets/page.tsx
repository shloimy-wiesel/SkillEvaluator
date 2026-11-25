"use client";

import { DatasetEditor } from "@/components/datasets/editor";
import { useRoute } from "@/lib/use-route";

/** @returns The dataset workbench for this project and draft deep link. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export default function Page() {
  const path = useRoute();

  return path ? (
    <DatasetEditor key={path} path={path} />
  ) : (
    <output>Opening datasets…</output>
  );
}
