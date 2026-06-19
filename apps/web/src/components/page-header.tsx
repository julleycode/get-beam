import type { ReactNode } from "react";

/**
 * Standard page title row. Replaces the repeated
 * `flex items-center justify-between mb-6 + <h2>` block across dashboard pages.
 */
export function PageHeader({
  title,
  actions,
}: {
  title: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-center justify-between gap-4">
      <h1 className="text-2xl font-serif font-semibold tracking-tight">{title}</h1>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
