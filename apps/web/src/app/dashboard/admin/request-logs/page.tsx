"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, RefreshCw, X } from "lucide-react";
import { api } from "@/lib/api";
import type { RequestLogEntry } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { TableSkeleton } from "@/components/skeletons";

const WINDOWS = [
  { label: "1h", hours: 1 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 24 * 7 },
];

/** Reason codes emitted by services/request_logger.py. Kept in sync manually —
 *  the backend is the source of truth; an unknown code still renders, just with
 *  the neutral fallback colour. */
const REASON_STYLES: Record<string, string> = {
  bot_drop: "bg-amber-100 text-amber-800",
  abuse_flag: "bg-red-100 text-red-800",
  rate_limited: "bg-orange-100 text-orange-800",
  http_error: "bg-yellow-100 text-yellow-800",
  exception: "bg-red-100 text-red-800",
  sampled: "bg-blue-100 text-blue-800",
};

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function ReasonBadge({ reason }: { reason: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 font-mono text-xs font-medium ${
        REASON_STYLES[reason] ?? "bg-gray-100 text-gray-800"
      }`}
    >
      {reason}
    </span>
  );
}

function StatusCell({ code }: { code: number }) {
  const tone =
    code >= 500
      ? "text-red-600"
      : code >= 400
        ? "text-amber-600"
        : "text-muted-foreground";
  return <span className={`font-mono text-xs font-semibold ${tone}`}>{code}</span>;
}

/** Pretty-printed JSON block. Scrolls inside its own box so a wide payload never
 *  makes the page scroll horizontally. */
function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value == null) {
    return (
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-xs italic text-muted-foreground">empty</p>
      </div>
    );
  }
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-80 overflow-auto rounded-md bg-secondary/60 p-3 text-xs leading-relaxed">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function DetailPanel({ logId, onClose }: { logId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["request-log", logId],
    queryFn: () => api.getRequestLog(logId),
  });

  return (
    <Card className="border-primary/30">
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-semibold">
              {data ? `${data.method} ${data.path}` : "Loading…"}
            </p>
            {data && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {data.created_at} · {data.duration_ms}ms · {data.client_ip ?? "no ip"}
              </p>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading payload…</p>}

        {data && (
          <>
            {data.reason_detail && (
              <p className="rounded-md bg-secondary/60 p-2 font-mono text-xs">
                {data.reason_detail}
              </p>
            )}
            {data.truncated && (
              <p className="text-xs text-amber-600">
                One or both bodies hit the size cap and were truncated.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              User-Agent:{" "}
              <span className="font-mono">{data.user_agent ?? "none"}</span>
            </p>
            <div className="grid gap-4 lg:grid-cols-2">
              <JsonBlock label="Request body" value={data.request_body} />
              <JsonBlock label="Response body" value={data.response_body} />
              <JsonBlock label="Query params" value={data.query_params} />
              <JsonBlock label="Request headers" value={data.request_headers} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function RequestLogsPage() {
  const [hours, setHours] = useState(24);
  const [reason, setReason] = useState<string | null>(null);
  const [pathContains, setPathContains] = useState("");
  const [pathQuery, setPathQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["request-log-stats", hours],
    queryFn: () => api.getRequestLogStats(hours),
    enabled: me?.is_admin === true,
  });

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["request-logs", hours, reason, pathQuery],
    queryFn: () =>
      api.listRequestLogs({
        hours,
        reason: reason ?? undefined,
        pathContains: pathQuery || undefined,
        limit: 100,
      }),
    enabled: me?.is_admin === true,
  });

  if (me && me.is_admin !== true) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-warning-muted text-warning">
          <ShieldAlert className="h-6 w-6" />
        </div>
        <p className="font-serif text-base font-semibold">Admins only</p>
        <p className="text-sm text-muted-foreground">
          You don&apos;t have access to this area.
        </p>
      </div>
    );
  }

  const logs: RequestLogEntry[] = data?.logs ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold tracking-tight">
            Request logs
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Full request/response JSON for dropped and flagged requests. Emails and
            credentials are redacted before storage.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Capture-off notice. Without this an empty table is ambiguous: it could
          mean "clean traffic" or "nothing is being recorded at all". */}
      {stats && !stats.enabled && (
        <Card className="border-amber-300 bg-amber-50/60">
          <CardContent className="p-4 text-sm">
            <p className="font-medium">Capture is off.</p>
            <p className="mt-1 text-muted-foreground">
              Set <code className="font-mono">REQUEST_LOG_ENABLED=true</code> to start
              recording. Rows are kept for {stats.retention_days} days, then purged.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              onClick={() => setHours(w.hours)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                hours === w.hours
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary/50"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>

        <button
          onClick={() => setReason(null)}
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            reason === null ? "bg-primary text-primary-foreground" : "bg-secondary"
          }`}
        >
          All {stats ? `(${stats.total})` : ""}
        </button>
        {(stats?.by_reason ?? []).map((r) => (
          <button
            key={r.reason}
            onClick={() => setReason(r.reason === reason ? null : r.reason)}
            className={`rounded-full px-3 py-1 font-mono text-xs font-medium ${
              reason === r.reason
                ? "bg-primary text-primary-foreground"
                : REASON_STYLES[r.reason] ?? "bg-secondary"
            }`}
          >
            {r.reason} ({r.count})
          </button>
        ))}

        <form
          className="ml-auto flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPathQuery(pathContains.trim());
          }}
        >
          <Input
            value={pathContains}
            onChange={(e) => setPathContains(e.target.value)}
            placeholder="Filter path…"
            className="h-8 w-48 text-xs"
          />
          <Button type="submit" variant="outline" size="sm">
            Search
          </Button>
        </form>
      </div>

      {selected && <DetailPanel logId={selected} onClose={() => setSelected(null)} />}

      {isLoading ? (
        <TableSkeleton cols={7} />
      ) : logs.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          {stats?.enabled
            ? "No matching requests in this window."
            : "Nothing recorded. Capture is off."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-secondary/40 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Reason</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Request</th>
                <th className="px-3 py-2 font-medium">Site</th>
                <th className="px-3 py-2 font-medium">IP</th>
                <th className="px-3 py-2 font-medium">ms</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr
                  key={log.id}
                  onClick={() => setSelected(log.id === selected ? null : log.id)}
                  className={`cursor-pointer border-b transition-colors hover:bg-secondary/40 ${
                    selected === log.id ? "bg-secondary/60" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                    {timeAgo(log.created_at)}
                  </td>
                  <td className="px-3 py-2">
                    <ReasonBadge reason={log.reason} />
                  </td>
                  <td className="px-3 py-2">
                    <StatusCell code={log.status_code} />
                  </td>
                  <td className="max-w-md px-3 py-2">
                    <span className="font-mono text-xs">
                      {log.method}{" "}
                      <span className="text-muted-foreground">{log.path}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                    {log.site_id ?? "—"}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                    {log.client_ip ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {Math.round(log.duration_ms)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > logs.length && (
        <p className="text-xs text-muted-foreground">
          Showing {logs.length} of {data.total}. Narrow the window or add a path
          filter to see more.
        </p>
      )}
    </div>
  );
}
