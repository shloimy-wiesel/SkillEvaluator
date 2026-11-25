/**
 * @param key - Selection name.
 * @param value - Selection value.
 * @returns An author URL retaining repeated query selections.
 */
export const withParam = (key: string, value: string) => {
  const url = new URL(window.location.href);
  url.searchParams.set(key, value);

  return url.href;
};

/** Retained run selector metadata. */
export interface Run {
  id: string;
  created: string;
  kind: string;
  status: string;
}

/** A labeled select option. */
export interface Choice {
  value: string;
  label: string;
}

/** Map dimension values to select options.
 * @param values - Available values.
 * @returns Labeled options. */
export const strings = (values: string[]) =>
  values.map((value) => ({ value, label: value }));

/** List retained evaluations.
 * @param runs - Scoped history.
 * @returns Run options. */
export const runChoices = (runs: Run[]) =>
  runs.map((r) => ({ value: r.id, label: `${r.created} · ${r.id}` }));

/** Paired version evidence. */
export interface Comparison {
  status: string;
  reasons: string[];
  source_studio_run?: string;
  agents?: Record<
    string,
    { prior_overall: number; current_overall: number; delta: number }
  >;
}

/** Format a measured score.
 * @param n - Score or missing measurement.
 * @param signed - Include a positive sign for deltas.
 * @returns Human-readable score. */
export const score = (n: number | null, signed = false) =>
  n === null
    ? "Not measured"
    : `${signed && n > 0 ? "+" : ""}${n.toFixed(2)}`.replace("-", "−");
