import type { ReactNode } from "react";
import { InfoTooltip } from "@/components/ui/info-tooltip";

/**
 * Standard page title row. Replaces the repeated
 * `flex items-center justify-between mb-6 + <h2>` block across dashboard pages.
 *
 * `info` adds a persistent ⓘ next to the title with a hover/focus explainer of
 * what the page is for — the in-page guidance counterpart to the one-time
 * per-tab intro dialog.
 */
export function PageHeader({
  title,
  info,
  actions,
}: {
  title: string;
  info?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-center justify-between gap-4">
      <h1 className="flex items-center gap-1.5 text-2xl font-serif font-semibold tracking-tight">
        {title}
        {info ? (
          <InfoTooltip label={`About ${title}`} align="start">
            {info}
          </InfoTooltip>
        ) : null}
      </h1>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
