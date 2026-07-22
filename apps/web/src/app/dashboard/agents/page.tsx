"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Bot } from "lucide-react";
import { TableSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { EmptyState } from "@/components/empty-state";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// Human-readable label for each verification method (raw enum uses hyphens, so
// pass an explicit label rather than the auto-humanized status transform).
const VERIFICATION_LABEL: Record<string, string> = {
  "ua-only": "UA only",
  "ip-verified": "IP verified",
  "rdns-verified": "rDNS verified",
};

function VerificationBadge({ method }: { method: string }) {
  return (
    <StatusBadge status={method} label={VERIFICATION_LABEL[method] ?? method} />
  );
}

export default function AgentsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [page, setPage] = useState(1);

  function handleSiteChange(id: string) {
    setSiteId(id);
    setPage(1);
  }

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["agents", siteId, page],
    queryFn: () => api.listAgents(siteId, { page, page_size: 50 }),
    enabled: !!siteId,
  });

  const { data: stats } = useQuery({
    queryKey: ["agent-stats", siteId],
    queryFn: () => api.getAgentStats(siteId),
    enabled: !!siteId,
  });

  const agents = data?.agents ?? [];
  const total = data?.total ?? 0;

  return (
    <div>
      <PageHeader
        title="Agents"
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <SiteSelector value={siteId} onChange={handleSiteChange} />
          </div>
        }
      />

      {siteId && stats && (
        <div className="mb-4 flex flex-wrap gap-4">
          <div className="rounded-lg border bg-card px-4 py-3 shadow-sm">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Total agent visits
            </div>
            <div className="font-mono text-2xl font-medium tabular-nums">
              {stats.total_visits}
            </div>
          </div>
          <div className="rounded-lg border bg-card px-4 py-3 shadow-sm">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Distinct vendors
            </div>
            <div className="font-mono text-2xl font-medium tabular-nums">
              {stats.distinct_vendors}
            </div>
          </div>
        </div>
      )}

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view agent visits.</p>
      ) : isLoading ? (
        <TableSkeleton cols={5} rows={10} />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load agents — ${error instanceof Error ? error.message : "unknown error"}`}
          onRetry={() => refetch()}
        />
      ) : (
        <>
          <p className="mb-3 text-sm text-muted-foreground">
            {total} agent visit{total !== 1 ? "s" : ""}
          </p>
          {agents.length === 0 ? (
            <EmptyState
              icon={Bot}
              title="No agent visits yet"
              description="When AI agents (crawlers, assistants) hit your site, they'll show up here — kept separate from your human visitors."
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Vendor</TableHead>
                  <TableHead>Product / UA token</TableHead>
                  <TableHead>Verification</TableHead>
                  <TableHead>Last seen</TableHead>
                  <TableHead className="text-right">Visits</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/agents/${a.id}?site=${siteId}`}
                        className="font-medium hover:underline"
                      >
                        {a.vendor}
                      </Link>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {a.product_or_ua_token}
                    </TableCell>
                    <TableCell>
                      <VerificationBadge method={a.verification_method} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {new Date(a.last_seen_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {a.visit_count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {total > 50 && (
            <div className="mt-4 flex justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="self-center text-sm text-muted-foreground">
                Page {page} of {Math.ceil(total / 50)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= Math.ceil(total / 50)}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
