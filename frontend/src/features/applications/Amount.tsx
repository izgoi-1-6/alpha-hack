import { useId } from "react";

/** One labelled amount tile; each figure keeps its own label and caveat. Shared by the customer and officer pages. */
export function Amount({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone?: string;
}) {
  const id = useId();
  return (
    <div
      className={"card amount" + (tone ? " " + tone : "")}
      role="group"
      aria-labelledby={id}
    >
      <span id={id}>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
