import type { ReactNode } from "react";

/** @returns A named, labelled select with native keyboard semantics. */
export const Select = ({
  name,
  label,
  options,
  children,
  multiple = false,
  required = false,
  value,
}: {
  name: string;
  label: string;
  options?: readonly string[];
  children?: ReactNode;
  multiple?: boolean;
  required?: boolean;
  value?: string;
}) => (
  <label>
    {label}
    <select
      name={name}
      multiple={multiple}
      required={required}
      defaultValue={value}
    >
      {children}
      {options?.map((option) => (
        <option key={option}>{option}</option>
      ))}
    </select>
  </label>
);

/** @returns A numeric evaluator input. Blank means no override. */
export const Numeric = ({
  name,
  label,
  min = 0,
  max,
  step = 1,
  value,
}: {
  name: string;
  label: string;
  min?: number;
  max?: number;
  step?: number | "any";
  value?: number;
}) => (
  <label>
    {label}
    <input
      name={name}
      type="number"
      min={min}
      max={max}
      step={step}
      defaultValue={value}
    />
  </label>
);

/** @returns An explicit opt-in setting. */
export const Toggle = ({
  name,
  label,
  value = "true",
}: {
  name: string;
  label: string;
  value?: string;
}) => (
  <label>
    <input type="checkbox" name={name} value={value} /> {label}
  </label>
);
