"use client";

import { BillingStatus, SiteStats } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

interface PipelineExplainerProps {
  stats: SiteStats | null;
  billing: BillingStatus | null;
  onDismiss: () => void;
}

const STEPS: { name: string; text: string }[] = [
  { name: "Track", text: "the pixel logs visits anonymously" },
  { name: "Score", text: "behavior builds a 0–100 intent score" },
  { name: "Identify", text: "at intent 40+, Beam looks up email and name" },
  { name: "Enrich", text: "identified visitors get job, company and social data" },
  {
    name: "Act",
    text: "10 new enriched visitors auto-create segments and draft campaigns for your approval",
  },
];

export function PipelineExplainer({ stats, billing, onDismiss }: PipelineExplainerProps) {
  const toSegments = stats?.enriched_unsegmented ?? stats?.enriched ?? 0;

  return (
    <Card className="mb-6">
      <CardContent className="relative p-5">
        <button
          type="button"
          aria-label="Dismiss"
          onClick={onDismiss}
          className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 6 6 18" />
            <path d="m6 6 12 12" />
          </svg>
        </button>

        <h3 className="mb-3 text-sm font-semibold">How Beam turns visitors into campaigns</h3>
        <ol className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((step, i) => (
            <li key={step.name} className="flex gap-2">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {i + 1}
              </span>
              <span className="text-muted-foreground">
                <span className="font-medium text-foreground">{step.name}</span> — {step.text}
              </span>
            </li>
          ))}
        </ol>

        {stats && (
          <p className="mt-4 text-sm">
            <span className="font-medium">{stats.total_visitors}</span> tracked ·{" "}
            <span className="font-medium">{stats.identified}</span> identified ·{" "}
            <span className="font-medium">{stats.enriched}</span> enriched ·{" "}
            <span className="font-medium">{Math.min(toSegments, 10)}/10</span> toward your next
            segments
          </p>
        )}
        {billing && (
          <p className="mt-1 text-xs text-muted-foreground">
            Identifications this month: {billing.monthly_identified_count}/
            {billing.monthly_limit ?? "∞"} ({billing.plan} plan)
          </p>
        )}
      </CardContent>
    </Card>
  );
}
