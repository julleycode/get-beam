"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, Visitor } from "@/lib/api";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

function statusColor(status: string) {
  switch (status) {
    case "identified": return "default";
    case "enriched": return "default";
    case "anonymous": return "secondary";
    default: return "outline";
  }
}

function intentColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-yellow-600";
  return "text-muted-foreground";
}

export default function VisitorsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [visitors, setVisitors] = useState<Visitor[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("intent_score");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setError(null);
    api
      .listVisitors(siteId, {
        page,
        page_size: 50,
        identity_status: filter === "all" ? undefined : filter,
        sort_by: sortBy,
      })
      .then((res) => {
        setVisitors(res.visitors);
        setTotal(res.total);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [siteId, page, filter, sortBy, retryKey]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Visitors</h2>
        <div className="flex items-center gap-3">
          <SiteSelector value={siteId} onChange={setSiteId} />
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All status</SelectItem>
              <SelectItem value="anonymous">Anonymous</SelectItem>
              <SelectItem value="identified">Identified</SelectItem>
              <SelectItem value="enriched">Enriched</SelectItem>
            </SelectContent>
          </Select>
          <Select value={sortBy} onValueChange={setSortBy}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="intent_score">Intent score</SelectItem>
              <SelectItem value="last_seen">Last seen</SelectItem>
              <SelectItem value="pageviews">Pageviews</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view visitors.</p>
      ) : loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : error ? (
        <ErrorBanner
          message={`Couldn't load visitors — ${error}`}
          onRetry={() => setRetryKey((k) => k + 1)}
        />
      ) : (
        <>
          <p className="text-sm text-muted-foreground mb-3">
            {total} visitor{total !== 1 ? "s" : ""}
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Visitor ID</TableHead>
                <TableHead>First seen</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead className="text-right">Pageviews</TableHead>
                <TableHead className="text-right">Intent</TableHead>
                <TableHead>Identity</TableHead>
                <TableHead>Enrichment</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visitors.map((v) => (
                <TableRow key={v.id}>
                  <TableCell>
                    <Link
                      href={`/dashboard/visitors/${v.visitor_id}?site=${siteId}`}
                      className="font-mono text-xs hover:underline"
                    >
                      {v.visitor_id.slice(0, 12)}...
                    </Link>
                  </TableCell>
                  <TableCell className="text-sm">
                    {new Date(v.first_seen).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-sm">
                    {new Date(v.last_seen).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-right">{v.total_pageviews}</TableCell>
                  <TableCell className={`text-right font-medium ${intentColor(v.intent_score)}`}>
                    {Math.round(v.intent_score)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusColor(v.identity_status)}>
                      {v.identity_status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusColor(v.enrichment_status)}>
                      {v.enrichment_status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {total > 50 && (
            <div className="flex justify-center gap-2 mt-4">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground self-center">
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
