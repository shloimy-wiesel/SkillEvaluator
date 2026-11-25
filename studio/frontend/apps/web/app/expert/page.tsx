"use client";

import { useRoute } from "@/components/expert/controls";
import { ExpertCheck } from "@/components/expert/expert-check";

/** @returns The expert check at the canonical browser URL. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export default function Page() {
  const route = useRoute();

  return route ? (
    <ExpertCheck route={route} />
  ) : (
    <output>Opening check…</output>
  );
}
