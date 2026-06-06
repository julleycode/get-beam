"use client";

import { useEffect, useState } from "react";
import { api, FeatureRequest } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const URGENCY_LABEL: Record<string, string> = {
  nice: "Nice to have",
  useful: "Would use it",
  critical: "Would pay for it",
};

const URGENCY_STYLE: Record<string, string> = {
  nice: "bg-muted text-muted-foreground",
  useful: "bg-blue-100 text-blue-700",
  critical: "bg-pink-100 text-pink-700",
};

export default function FeatureRequestsPage() {
  const [requests, setRequests] = useState<FeatureRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listFeatureRequests()
      .then((r) => {
        setRequests(r.requests);
        setTotal(r.total);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-serif font-semibold tracking-tight">Feature Requests</h1>
        <p className="text-muted-foreground">
          What people are asking for from the landing page — {total} total.
        </p>
      </div>

      {loading && <p className="text-muted-foreground">Loading…</p>}
      {error && <p className="text-destructive">Failed to load: {error}</p>}

      {!loading && !error && requests.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No feature requests yet. They&apos;ll appear here the moment someone
            submits one from the “request a feature” button on your landing page.
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {requests.map((req) => (
          <Card key={req.id}>
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between gap-3">
                <CardTitle className="text-base">{req.title}</CardTitle>
                {req.urgency && (
                  <span
                    className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
                      URGENCY_STYLE[req.urgency] || "bg-muted text-muted-foreground"
                    }`}
                  >
                    {URGENCY_LABEL[req.urgency] || req.urgency}
                  </span>
                )}
              </div>
              <CardDescription className="flex flex-wrap items-center gap-2 text-xs">
                <span>{new Date(req.created_at).toLocaleString()}</span>
                {req.email && (
                  <>
                    <span>·</span>
                    <a href={`mailto:${req.email}`} className="text-primary hover:underline">
                      {req.email}
                    </a>
                  </>
                )}
              </CardDescription>
            </CardHeader>
            {req.detail && (
              <CardContent className="pt-0 text-sm text-muted-foreground whitespace-pre-wrap">
                {req.detail}
              </CardContent>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
