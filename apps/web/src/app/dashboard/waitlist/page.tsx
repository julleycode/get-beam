"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatGridSkeleton, TableSkeleton } from "@/components/skeletons";
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
    granted: "bg-pink-100 text-pink-800",
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
  const [acting, setActing] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["waitlist"],
    queryFn: () => api.getWaitlist(),
  });
  const signups = data?.signups ?? [];
  const counts = data?.counts ?? { pending: 0, approved: 0, granted: 0, rejected: 0 };

  function reload() {
    return queryClient.invalidateQueries({ queryKey: ["waitlist"] });
  }

  async function runAction(id: string, action: () => Promise<unknown>, label: string) {
    setActing(id);
    try {
      await action();
      await reload();
    } catch (err) {
      console.error(`${label} failed`, err);
    } finally {
      setActing(null);
    }
  }

  const handleApprove = (id: string) => runAction(id, () => api.approveWaitlist(id), "Approve");
  const handleGrant = (id: string) => runAction(id, () => api.grantWaitlist(id), "Grant");
  const handleReject = (id: string) => runAction(id, () => api.rejectWaitlist(id), "Reject");
  const handleDelete = (id: string) => runAction(id, () => api.deleteWaitlist(id), "Delete");

  if (isLoading) {
    return (
      <div className="space-y-6">
        <StatGridSkeleton cols={4} />
        <TableSkeleton cols={5} rows={8} />
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
        <span className="text-pink-700 font-medium">
          {counts.granted} granted
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
                    <div className="flex gap-2 justify-end items-center">
                      {s.status === "pending" && (
                        <>
                          <Button
                            size="sm"
                            variant="default"
                            className="bg-green-600 hover:bg-green-700 text-white h-7 text-xs"
                            disabled={acting === s.id}
                            onClick={() => handleApprove(s.id)}
                            title="Emails this person their invite link and lets them create an account."
                          >
                            {acting === s.id ? "..." : "Invite"}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs"
                            disabled={acting === s.id}
                            onClick={() => handleGrant(s.id)}
                            title="Marks a slot taken on the landing-page counter only. Does NOT email or give access."
                          >
                            {acting === s.id ? "..." : "Reserve"}
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
                        </>
                      )}
                      {s.status === "approved" && (
                        <span className="text-xs text-muted-foreground">
                          invited {timeAgo(s.approved_at)}
                        </span>
                      )}
                      {s.status === "granted" && (
                        <span className="text-xs text-pink-600">
                          slot taken
                        </span>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs text-muted-foreground hover:text-red-600"
                        disabled={acting === s.id}
                        onClick={() => handleDelete(s.id)}
                      >
                        Delete
                      </Button>
                    </div>
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
