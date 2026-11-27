"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Building2 } from "lucide-react";
import { api } from "@/lib/api";
import type { AccountSort } from "@/lib/api-types";
import { TableSkeleton } from "@/components/skeletons";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const SORTS: { value: AccountSort; label: string }[] = [
  { value: "last_seen", label: "Last seen" },
  { value: "visitors", label: "Visitors" },
  { value: "identified", label: "Identified people" },
  { value: "sessions", label: "Sessions" },
  { value: "pricing", label: "Pricing visitors" },
  { value: "touched", label: "Emails sent" },
  { value: "clicks", label: "Clicks" },
  { value: "conversions", label: "Conversions" },
];
const DAYS = [7, 30, 90, 365];
const PAGE_SIZE = 25;

function isFlagOff(err: unknown): boolean {
  return err instanceof Error && err.message === "Not found";
}

export default function AccountsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [sort, setSort] = useState<AccountSort>("last_seen");
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(1);
  const [openDomain, setOpenDomain] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["accounts", siteId, sort, days, page],
    queryFn: () => api.listAccounts(siteId, { sort, days, page, pageSize: PAGE_SIZE }),
    enabled: !!siteId,
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["account", siteId, openDomain, days],
    queryFn: () => api.getAccount(siteId, openDomain as string, days),
    enabled: !!siteId && !!openDomain,
    retry: false,
  });

  const data = list.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6" data-testid="accounts-page">
      <PageHeader
        title="Accounts"
        actions={
          <div className="flex items-center gap-3">
            <select
              aria-label="Sort accounts"
              className="rounded-md border bg-muted px-2 py-1.5 text-sm"
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as AccountSort);
                setPage(1);
              }}
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  Sort: {s.label}
                </option>
              ))}
            </select>
            <select
              aria-label="Time window"
              className="rounded-md border bg-muted px-2 py-1.5 text-sm"
              value={days}
              onChange={(e) => {
                setDays(Number(e.target.value));
                setPage(1);
              }}
            >
              {DAYS.map((d) => (
                <option key={d} value={d}>
                  Last {d} days
                </option>
              ))}
            </select>
            <SiteSelector value={siteId} onChange={setSiteId} />
          </div>
        }
      />

      {!siteId ? (
        <EmptyState
          icon={Building2}
          title="Pick a site"
          description="Choose a site to see its activity rolled up per company."
        />
      ) : list.isLoading ? (
        <TableSkeleton cols={9} />
      ) : list.isError && isFlagOff(list.error) ? (
        <EmptyState
          icon={Building2}
          title="Accounts view is not enabled"
          description="This view is turned off on this deployment."
        />
      ) : list.isError ? (
        <EmptyState
          icon={Building2}
          title="Could not load accounts"
          description="Please try again in a moment."
        />
      ) : !data || data.accounts.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No accounts yet"
          description="Accounts appear once visitors from a company domain show up in this window."
        />
      ) : (
        <>
          <Table data-testid="accounts-table">
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead className="text-right">Visitors</TableHead>
                <TableHead className="text-right">Identified</TableHead>
                <TableHead className="text-right">Sessions</TableHead>
                <TableHead className="text-right">Pricing</TableHead>
                <TableHead className="text-right">Emails</TableHead>
                <TableHead className="text-right">Clicks</TableHead>
                <TableHead className="text-right">Conversions</TableHead>
                <TableHead className="text-right">Demos</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.accounts.map((a) => (
                <TableRow
                  key={a.domain}
                  className="cursor-pointer"
                  onClick={() => setOpenDomain(a.domain)}
                >
                  <TableCell>
                    <div className="font-medium">{a.company_name || a.domain}</div>
                    {a.company_name && (
                      <div className="text-xs text-muted-foreground">{a.domain}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right">{a.visitors}</TableCell>
                  <TableCell className="text-right">{a.identified_people}</TableCell>
                  <TableCell className="text-right">{a.sessions}</TableCell>
                  <TableCell className="text-right">{a.pricing_visitors}</TableCell>
                  <TableCell className="text-right">{a.touched}</TableCell>
                  <TableCell className="text-right">{a.clicks}</TableCell>
                  <TableCell className="text-right">{a.conversions}</TableCell>
                  <TableCell className="text-right">{a.demo_bookings}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {data.total} accounts · page {page} of {pages}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Replies and CRM pipeline are not tracked yet. Counts are clicks and
            conversions, not revenue.
          </p>
        </>
      )}

      <Dialog open={!!openDomain} onOpenChange={(o) => !o && setOpenDomain(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{detail.data?.company_name || openDomain}</DialogTitle>
            <DialogDescription>
              Last {days} days{detail.data?.industry ? ` · ${detail.data.industry}` : ""}
            </DialogDescription>
          </DialogHeader>
          {detail.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : detail.isError || !detail.data ? (
            <p className="text-sm text-muted-foreground">Could not load this account.</p>
          ) : detail.data.campaigns.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No campaign activity for this account in this window.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Campaign</TableHead>
                  <TableHead className="text-right">Emails</TableHead>
                  <TableHead className="text-right">Clicks</TableHead>
                  <TableHead className="text-right">Conversions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detail.data.campaigns.map((c) => (
                  <TableRow key={c.campaign_id}>
                    <TableCell>{c.name}</TableCell>
                    <TableCell className="text-right">{c.touched}</TableCell>
                    <TableCell className="text-right">{c.clicks}</TableCell>
                    <TableCell className="text-right">{c.conversions}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
