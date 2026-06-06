"use client";

import { useEffect, useState, useCallback } from "react";
import { api, WaitlistSignup } from "@/lib/api";
import { Button } from "@/components/ui/button";

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
        colors[status] || "bg-gray-100 text-gray-800"
      }`}
    >
      {status}
    </span>
  );
}

export default function WaitlistPage() {
  const [signups, setSignups] = useState<WaitlistSignup[]>([]);
  const [counts, setCounts] = useState({ pending: 0, approved: 0, rejected: 0 });
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const data = await api.getWaitlist();
      setSignups(data.signups);
      setCounts(data.counts);
    } catch (err) {
      console.error("Failed to load waitlist", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function handleApprove(id: string) {
    setActing(id);
    try {
      await api.approveWaitlist(id);
      await fetchData();
    } catch (err) {
      console.error("Approve failed", err);
    } finally {
      setActing(null);
    }
  }

  async function handleReject(id: string) {
    setActing(id);
    try {
      await api.rejectWaitlist(id);
      await fetchData();
    } catch (err) {
      console.error("Reject failed", err);
    } finally {
      setActing(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-muted-foreground">Loading waitlist...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-serif font-semibold tracking-tight">
          Waitlist
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage private beta signups
        </p>
      </div>

      {/* Stats bar */}
      <div className="flex gap-4 text-sm">
        <span className="text-yellow-700 font-medium">
          {counts.pending} pending
        </span>
        <span className="text-muted-foreground">&middot;</span>
        <span className="text-green-700 font-medium">
          {counts.approved} approved
        </span>
        <span className="text-muted-foreground">&middot;</span>
        <span className="text-red-700 font-medium">
          {counts.rejected} rejected
        </span>
      </div>

      {/* Table */}
      {signups.length === 0 ? (
        <div className="rounded-lg border p-8 text-center text-muted-foreground">
          No waitlist signups yet.
        </div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="text-left px-4 py-3 font-medium">Email</th>
                <th className="text-left px-4 py-3 font-medium">Site</th>
                <th className="text-left px-4 py-3 font-medium">Signed Up</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-right px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {signups.map((s) => (
                <tr key={s.id} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-3 font-medium">{s.email}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {s.site_url ? (
                      <a
                        href={s.site_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[hsl(345,100%,60%)] hover:underline truncate block max-w-[200px]"
                      >
                        {s.site_url.replace(/^https?:\/\//, "")}
                      </a>
                    ) : (
                      <span className="text-muted-foreground/50">&mdash;</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {timeAgo(s.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {s.status === "pending" && (
                      <div className="flex gap-2 justify-end">
                        <Button
                          size="sm"
                          variant="default"
                          className="bg-green-600 hover:bg-green-700 text-white h-7 text-xs"
                          disabled={acting === s.id}
                          onClick={() => handleApprove(s.id)}
                        >
                          {acting === s.id ? "..." : "Approve"}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs text-red-600 border-red-200 hover:bg-red-50"
                          disabled={acting === s.id}
                          onClick={() => handleReject(s.id)}
                        >
                          Reject
                        </Button>
                      </div>
                    )}
                    {s.status === "approved" && (
                      <span className="text-xs text-muted-foreground">
                        invited {timeAgo(s.approved_at)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
