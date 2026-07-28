"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, FeatureBoardItem } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const URGENCY_LABEL: Record<string, string> = {
  nice: "Nice to have",
  useful: "Would use it",
  critical: "Would pay for it",
};

function StatusBadge({ status }: { status: string }) {
  if (status === "shipped") {
    return <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Shipped</Badge>;
  }
  if (status === "planned") {
    return <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100">Planned</Badge>;
  }
  return null;
}

function VoteButton({
  item,
  onVote,
  disabled,
}: {
  item: FeatureBoardItem;
  onVote: (id: string) => void;
  disabled: boolean;
}) {
  return (
    <button
      onClick={() => onVote(item.id)}
      disabled={disabled}
      aria-pressed={item.my_vote}
      aria-label={item.my_vote ? "Remove upvote" : "Upvote"}
      className={`flex flex-col items-center justify-center w-12 h-14 shrink-0 rounded-xl border text-sm transition-all ${
        item.my_vote
          ? "bg-[hsl(345,100%,60%)] text-white border-transparent shadow-[0_4px_12px_-4px_rgba(255,51,102,0.35)]"
          : "bg-card text-foreground border-[rgba(43,37,48,0.12)] hover:border-[hsl(345,100%,60%)]"
      } ${disabled ? "opacity-60" : ""}`}
    >
      <span className="text-xs leading-none">▲</span>
      <span className="font-semibold leading-tight">{item.votes}</span>
    </button>
  );
}

export default function FeatureBoardPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [urgency, setUrgency] = useState("useful");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["feature-board"],
    queryFn: () => api.getFeatureBoard(),
  });

  const voteMutation = useMutation({
    mutationFn: (id: string) => api.voteFeature(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["feature-board"] }),
  });

  const submitMutation = useMutation({
    mutationFn: () =>
      api.submitBoardRequest({
        title: title.trim(),
        detail: detail.trim() || undefined,
        urgency,
      }),
    onSuccess: () => {
      setTitle("");
      setDetail("");
      setShowForm(false);
      setSubmitError(null);
      queryClient.invalidateQueries({ queryKey: ["feature-board"] });
    },
    onError: (e: Error) => setSubmitError(e.message),
  });

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Feature Board</h2>
        <Button size="sm" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "Request a feature"}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground mb-6">
        Upvote what you need most. The top of this board ships first.
      </p>

      {showForm && (
        <Card className="mb-6">
          <CardContent className="pt-6 space-y-3">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={120}
              placeholder="What should Beam do for you?"
              className="w-full rounded-md border border-[rgba(43,37,48,0.12)] bg-background px-3 py-2 text-sm"
            />
            <textarea
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="Any details? What problem does it solve? (optional)"
              className="w-full rounded-md border border-[rgba(43,37,48,0.12)] bg-background px-3 py-2 text-sm"
            />
            <div className="flex items-center gap-2 text-sm">
              {Object.entries(URGENCY_LABEL).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setUrgency(value)}
                  className={`rounded-full px-3 py-1 border transition-all ${
                    urgency === value
                      ? "bg-[hsl(345,100%,60%)] text-white border-transparent"
                      : "border-[rgba(43,37,48,0.12)] text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {submitError && <p className="text-sm text-destructive">{submitError}</p>}
            <Button
              size="sm"
              disabled={!title.trim() || submitMutation.isPending}
              onClick={() => submitMutation.mutate()}
            >
              {submitMutation.isPending ? "Submitting..." : "Submit"}
            </Button>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <ListCardSkeleton rows={4} leading />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load the board: ${error?.message ?? "request failed"}`}
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <p className="text-muted-foreground">
          Nothing here yet. Request the first feature.
        </p>
      ) : (
        <div className="space-y-3">
          {data.items.map((item) => (
            <Card key={item.id}>
              <CardContent className="pt-4 pb-4 flex gap-4 items-start">
                <VoteButton
                  item={item}
                  onVote={(id) => voteMutation.mutate(id)}
                  disabled={voteMutation.isPending}
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-medium leading-snug">{item.title}</h3>
                    <StatusBadge status={item.status} />
                  </div>
                  {item.detail && (
                    <p className="text-sm text-muted-foreground mt-1 whitespace-pre-line">
                      {item.detail}
                    </p>
                  )}
                  {item.urgency && (
                    <p className="text-xs text-muted-foreground mt-2">
                      {URGENCY_LABEL[item.urgency] ?? item.urgency}
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
