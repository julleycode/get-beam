"use client";

import { useEffect, useState, useCallback } from "react";
import { api, FeatureRequest } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  planned: "Planned",
  shipped: "Shipped",
  closed: "Closed",
};

const STATUS_STYLE: Record<string, string> = {
  new: "bg-yellow-100 text-yellow-800 border-yellow-200",
  planned: "bg-blue-100 text-blue-800 border-blue-200",
  shipped: "bg-green-100 text-green-800 border-green-200",
  closed: "bg-gray-100 text-gray-600 border-gray-200",
};

const FILTER_OPTIONS = [
  { value: "all", label: "All" },
  { value: "new", label: "New" },
  { value: "planned", label: "Planned" },
  { value: "shipped", label: "Shipped" },
  { value: "closed", label: "Closed" },
];

export default function FeatureRequestsPage() {
  const [requests, setRequests] = useState<FeatureRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  const fetchRequests = useCallback(async (status?: string) => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.listFeatureRequests(status === "all" ? undefined : status);
      setRequests(r.requests);
      setTotal(r.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRequests(filter);
  }, [filter, fetchRequests]);

  const handleStatusChange = async (id: string, newStatus: string) => {
    setSaving(id);
    try {
      const updated = await api.updateFeatureRequest(id, { status: newStatus });
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const handleSaveNote = async (id: string) => {
    setSaving(id);
    try {
      const updated = await api.updateFeatureRequest(id, { admin_note: editNote });
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)));
      setExpandedId(null);
      setEditNote("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const toggleExpand = (req: FeatureRequest) => {
    if (expandedId === req.id) {
      setExpandedId(null);
      setEditNote("");
    } else {
      setExpandedId(req.id);
      setEditNote(req.admin_note || "");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-serif font-semibold tracking-tight">Feature Requests</h1>
          <p className="text-muted-foreground">
            What people are asking for from the landing page ({total} total).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                filter === opt.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <ListCardSkeleton rows={4} />}
      {error && <p className="text-destructive">Failed to load: {error}</p>}

      {!loading && !error && requests.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            {filter === "all"
              ? "No feature requests yet. They'll appear here the moment someone submits one from the \"request a feature\" button on your landing page."
              : `No ${STATUS_LABEL[filter]?.toLowerCase() || filter} requests.`}
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {requests.map((req) => (
          <Card key={req.id} className={expandedId === req.id ? "ring-1 ring-primary/30" : ""}>
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                  <CardTitle className="text-base truncate">{req.title}</CardTitle>
                  {req.urgency && (
                    <span
                      className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        URGENCY_STYLE[req.urgency] || "bg-muted text-muted-foreground"
                      }`}
                    >
                      {URGENCY_LABEL[req.urgency] || req.urgency}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Select
                    value={req.status}
                    onValueChange={(v) => handleStatusChange(req.id, v)}
                    disabled={saving === req.id}
                  >
                    <SelectTrigger className="h-7 w-[110px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(STATUS_LABEL).map(([value, label]) => (
                        <SelectItem key={value} value={value} className="text-xs">
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <CardDescription className="flex flex-wrap items-center gap-2 text-xs">
                <Badge
                  variant="outline"
                  className={`text-[10px] px-1.5 py-0 ${STATUS_STYLE[req.status] || ""}`}
                >
                  {STATUS_LABEL[req.status] || req.status}
                </Badge>
                <span>{new Date(req.created_at).toLocaleString()}</span>
                {req.email && (
                  <>
                    <span>·</span>
                    <a href={`mailto:${req.email}`} className="text-primary hover:underline">
                      {req.email}
                    </a>
                    {req.status !== "new" && (
                      <span className="text-muted-foreground/60">(will be notified on status change)</span>
                    )}
                  </>
                )}
              </CardDescription>
            </CardHeader>

            <CardContent className="pt-0 space-y-3">
              {req.detail && (
                <p className="text-sm text-muted-foreground whitespace-pre-wrap">{req.detail}</p>
              )}

              {req.admin_note && expandedId !== req.id && (
                <div className="rounded-md bg-muted/50 px-3 py-2 text-sm">
                  <span className="text-xs font-medium text-muted-foreground">Note: </span>
                  {req.admin_note}
                </div>
              )}

              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-muted-foreground"
                  onClick={() => toggleExpand(req)}
                >
                  {expandedId === req.id ? "Cancel" : req.admin_note ? "Edit note" : "Add note"}
                </Button>
              </div>

              {expandedId === req.id && (
                <div className="space-y-2 pt-1">
                  <Textarea
                    value={editNote}
                    onChange={(e) => setEditNote(e.target.value)}
                    placeholder="Add an internal note (visible only to you)…"
                    rows={3}
                    className="text-sm"
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="h-7 text-xs"
                      onClick={() => handleSaveNote(req.id)}
                      disabled={saving === req.id}
                    >
                      {saving === req.id ? "Saving…" : "Save note"}
                    </Button>
                    {req.admin_note && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs text-destructive"
                        onClick={() => {
                          setEditNote("");
                          handleSaveNote(req.id);
                        }}
                        disabled={saving === req.id}
                      >
                        Remove note
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
