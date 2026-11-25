import type { ReactNode } from "react";

import type { Json } from "./model";

/** @returns A named native submitter for single- and multi-action forms. */
export const Action = ({
  value,
  children,
}: {
  value: string;
  children: ReactNode;
}) => (
  <button
    type="submit"
    name="action"
    value={value}
    formNoValidate={value === "remove"}
  >
    {children}
  </button>
);

/** @returns A labeled, opt-in action flag. */
export const Toggle = ({
  name,
  label,
  checked = false,
}: {
  name: string;
  label: string;
  checked?: boolean;
}) => (
  <label>
    <input type="checkbox" name={name} defaultChecked={checked} /> {label}
  </label>
);

/** @returns Read-only JSON evidence, rendered as text. */
// oxlint-disable-next-line sonarjs/function-name -- React components use PascalCase.
export const Pretty = ({
  value,
  label,
}: {
  value: Json | object;
  label?: string;
}) => {
  const contents = <pre>{JSON.stringify(value, null, 2)}</pre>;

  return label === undefined ? (
    contents
  ) : (
    <section aria-label={label}>{contents}</section>
  );
};
