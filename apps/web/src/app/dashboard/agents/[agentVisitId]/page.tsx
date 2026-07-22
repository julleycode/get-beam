"use client";

import { type ComponentType, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowLeft, Bot } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeaderSkeleton, StatGridSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { StatusBadge } from "@/components/ui/status-badge";
import { Badge } from "@/components/ui/badge";

// Human-readable label for each verification method (raw enum uses hyphens).
const VERIFICATION_LABEL: Record<string, string> = {
  "ua-only": "UA only",
  "ip-verified": "IP verified",
  "rdns-verified": "rDNS verified",
};

/* ------------------------------------------------------------------ */
/* Local presentational helpers (copied from the visitors detail page). */
/* ------------------------------------------------------------------ */

function Section({
  title,
  icon: Icon,
  children,
  className,
}: {
  title: string;
  icon?: ComponentType<{ className?: string }>;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border bg-card shadow-sm", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-5 py-3.5">
        <h3 className="flex items-center gap-2 font-serif text-base font-semibold tracking-tight">
          {Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null}
          {title}
        </h3>
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="max-w-[62%] text-right font-medium">{children}</span>
    </div>
  );
}

export default function AgentDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const agentVisitId = String(params.agentVisitId);
  const siteId = searchParams.get("site") || "";

  const { data: agent, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["agent", siteId, agentVisitId],
    queryFn: () => api.getAgent(siteId, agentVisitId),
    enabled: !!siteId && !!agentVisitId,
  });

  const backLink = (
    <Link
      href="/dashboard/agents"
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      Back to Agents
    </Link>
  );

  if (isLoading) {
    return (
      <div className="space-y-6">
        {backLink}
        <PageHeaderSkeleton />
        <StatGridSkeleton />
      </div>
    );
  }

  if (isError || !agent) {
    return (
      <div className="space-y-6">
        {backLink}
        <ErrorBanner
          message={`Couldn't load agent — ${error instanceof Error ? error.message : "not found"}`}
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {backLink}

      {/* Hero */}
      <div className="flex items-center gap-4 rounded-xl border bg-card p-5 shadow-sm">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
          <Bot className="h-6 w-6" />
        </div>
        <div className="flex flex-col gap-1">
          <h1 className="font-serif text-2xl font-semibold tracking-tight">
            {agent.vendor}
          </h1>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-muted-foreground">
              {agent.product_or_ua_token}
            </span>
            <StatusBadge
              status={agent.verification_method}
              label={VERIFICATION_LABEL[agent.verification_method] ?? agent.verification_method}
            />
          </div>
        </div>
      </div>

      {/* Activity */}
      <Section title="Activity" icon={Activity}>
        <div className="divide-y divide-border/60">
          <InfoRow label="First seen">
            {new Date(agent.first_seen_at).toLocaleString()}
          </InfoRow>
          <InfoRow label="Last seen">
            {new Date(agent.last_seen_at).toLocaleString()}
          </InfoRow>
          <InfoRow label="IP address">
            {agent.ip_address ?? "—"}
          </InfoRow>
          <InfoRow label="Visits">{agent.visit_count}</InfoRow>
          <InfoRow label="Pages read">
            {agent.page_paths.length === 0 ? (
              "—"
            ) : (
              <span className="flex flex-wrap justify-end gap-1.5">
                {agent.page_paths.map((p) => (
                  <Badge key={p} variant="secondary" className="font-mono text-xs">
                    {p}
                  </Badge>
                ))}
              </span>
            )}
          </InfoRow>
        </div>
      </Section>
    </div>
  );
}
