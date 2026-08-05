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
import { AgentsHelp } from "@/components/page-help";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

// Stable palette color by index so the stacked vendor bar's segments stay
// distinguishable (mirrors the traffic-fit-card GEO_PALETTE pattern).
const VENDOR_PALETTE = [
  "#6366f1",
  "#06b6d4",
  "#f97316",
  "#a855f7",
  "#f43f5e",
  "#14b8a6",
  "#22c55e",
  "#eab308",
];
const vendorColor = (i: number) => VENDOR_PALETTE[i % VENDOR_PALETTE.length];

// Fixed GEO/AEO analytics cards (SPEC AC11) — a read-only snapshot below the
// Phase 3 KPI row. NOT draggable, no localStorage, no time-window toggle.
function AgentAnalyticsCards({ siteId }: { siteId: string }) {
  const { data, isError } = useQuery({
    queryKey: ["agent-analytics", siteId],
    queryFn: () => api.getAgentAnalytics(siteId),
    enabled: !!siteId,
  });

  if (isError || !data) return null;

  const vendorEntries = Object.entries(data.by_vendor).sort(
    (a, b) => b[1] - a[1]
  );
  const vendorTotal = vendorEntries.reduce((sum, [, n]) => sum + n, 0);
  const verificationEntries = Object.entries(data.by_verification).sort(
    (a, b) => b[1] - a[1]
  );

  if (vendorTotal === 0 && data.top_pages.length === 0) return null;

  return (
    <div className="mb-6 grid gap-4 md:grid-cols-2">
      {/* Vendor breakdown — hand-rolled 100%-stacked bar (traffic-fit pattern). */}
      <Card className="h-full">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Agent vendors</CardTitle>
        </CardHeader>
        <CardContent>
          {vendorTotal > 0 ? (
            <>
              <div className="flex h-8 w-full rounded-md bg-secondary">
                {vendorEntries.map(([vendor, count], i) => (
                  <div
                    key={vendor}
                    className="group relative h-full min-w-[3px] cursor-default border-r border-background/60 transition-opacity first:rounded-l-md last:border-r-0 hover:opacity-90"
                    style={{
                      width: `${Math.round((count / vendorTotal) * 100)}%`,
                      backgroundColor: vendorColor(i),
                    }}
                  >
                    <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 hidden -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md group-hover:block">
                      <div className="font-medium">{vendor}</div>
                      <div className="mt-0.5 text-muted-foreground">
                        {count} visit{count !== 1 ? "s" : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <ul className="mt-3 space-y-1 border-t pt-3 text-sm">
                {vendorEntries.map(([vendor, count], i) => (
                  <li key={vendor} className="flex items-center gap-2">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{ backgroundColor: vendorColor(i) }}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate">{vendor}</span>
                    <span className="font-mono tabular-nums text-muted-foreground">
                      {count}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">No vendor data yet.</p>
          )}
        </CardContent>
      </Card>

      {/* Page-read trends — ranked list of the most-read paths. */}
      <Card className="h-full">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Most-read pages</CardTitle>
        </CardHeader>
        <CardContent>
          {data.top_pages.length > 0 ? (
            <ul className="space-y-1 text-sm">
              {data.top_pages.map((p) => (
                <li key={p.path} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">
                    {p.path}
                  </span>
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {p.count}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">No page reads yet.</p>
          )}
          {verificationEntries.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
              {verificationEntries.map(([method, count]) => (
                <span key={method}>
                  {VERIFICATION_LABEL[method] ?? method}:{" "}
                  <span className="font-mono tabular-nums text-foreground">
                    {count}
                  </span>
                </span>
              ))}
            </div>
          )}
          {/* Handoff Detection H2: agent fetches correlated to a human click.
              Always shown with its denominator and confidence split — a bare
              count of 0 reads as "broken" when it usually means "no AI-referred
              click landed in the window after a fetch". */}
          <div
            className="mt-3 border-t pt-3 text-xs text-muted-foreground"
            title="Agent fetches Beam correlated to a human AI-referral click on the same page. Correlation is probabilistic — matched on vendor, page and a 30-minute window, not on a unique identifier."
          >
            <div>
              Human handoffs:{" "}
              <span className="font-mono tabular-nums text-foreground">
                {data.handoff_links_count}
              </span>{" "}
              of{" "}
              <span className="font-mono tabular-nums text-foreground">
                {data.on_demand_fetch_count}
              </span>{" "}
              live agent fetches
            </div>
            {data.handoff_links_count > 0 ? (
              <div className="mt-1">
                {data.handoff_confidence.high ?? 0} strong match
                {(data.handoff_confidence.high ?? 0) === 1 ? "" : "es"} ·{" "}
                {data.handoff_confidence.medium ?? 0} likely
              </div>
            ) : (
              <div className="mt-1">
                {data.on_demand_fetch_count > 0
                  ? "Agents fetched pages, but no AI-referred visit followed within 30 minutes."
                  : "No live agent fetches recorded yet — nothing to correlate."}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Handoff Detection H3: companies that appeared shortly after an AI agent
          fetched a commercial page. Read-only metadata — no action affordances,
          never a link into campaign/outreach UI. */}
      <Card className="h-full">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Appeared after AI research</CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_ai_researched_companies.length > 0 ? (
            <ul className="space-y-1 text-sm">
              {data.recent_ai_researched_companies.map((c, i) => (
                <li
                  key={`${c.domain ?? c.company_name}-${c.matched_page}-${i}`}
                  className="flex items-center gap-2"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {c.company_name}
                  </span>
                  <span className="min-w-0 max-w-[45%] truncate font-mono text-xs text-muted-foreground">
                    {c.matched_page}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">
              No AI-researched companies correlated yet.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
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
        info={<AgentsHelp />}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <SiteSelector value={siteId} onChange={handleSiteChange} />
            <Button variant="outline" size="sm" asChild>
              <Link href="/dashboard/agent-gateway">Gateway settings</Link>
            </Button>
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

      {siteId && <AgentAnalyticsCards siteId={siteId} />}

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view agent visits.</p>
      ) : isLoading ? (
        <TableSkeleton cols={5} rows={10} />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load agents: ${error instanceof Error ? error.message : "unknown error"}`}
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
              description={
                stats?.detection_enabled === false
                  ? "Agent detection must be enabled on the backend (AGENT_DETECTION_ENABLED) before visits from GPTBot, ClaudeBot, PerplexityBot and others appear here."
                  : "No agent visits yet — once AI agents like GPTBot or ClaudeBot fetch your pages they'll appear here."
              }
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
