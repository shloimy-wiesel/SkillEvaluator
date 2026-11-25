/** JSON authored in a case may contain structured expectations and metadata. */
export type Json =
  | null
  | boolean
  | number
  | string
  | Json[]
  | { [field: string]: Json };

/** Case fields the editor understands; additional fields stay in the draft. */
export interface DatasetCase {
  id?: string | number;
  prompt?: Json;
  expected_output?: Json;
  assertions?: Json;
  files?: Json;
  should_trigger?: Json;
}

/** Editable object dataset. */
export interface Dataset {
  evals: DatasetCase[];
  skill_name?: string;
}

interface Check {
  status: string;
  path: string;
  message: string;
}

/** Redacted trace and its independent review. */
export interface Candidate {
  id: string;
  prompt: string;
  observed: { outcome: string };
  files: string[];
  redactions: Json;
  warnings: string[];
  review: {
    decision: string;
    expected_output: string;
    assertions: string[];
    suggested_assertions: string[];
  };
}

/** Project-scoped projection returned after loading or updating a draft. */
export interface DatasetView {
  project: { id: string; name: string; branch: string; revision: string };
  draft: {
    token: string;
    path: string;
    choices: string[];
    branch: string;
    revision: string;
    version: number;
    collection?: string;
    staged: string[];
  } | null;
  editable: Dataset | null;
  pushed?: boolean;
  detail?: { code: string; message: string };
  notice?: string;
  generated?: Dataset;
  migration?: Json;
  sample?: Json;
  diff?: string;
  validation?: { passed: boolean; checks: Check[] };
  review: { candidates: Candidate[]; skipped: Json[] } | null;
  trace_checks?: Check[];
  allow_native?: boolean;
}
