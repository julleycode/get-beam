"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { api, type DraftStatus } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { DraftCard } from "@/components/draft-card";
import { EmptyState } from "@/components/empty-state";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS: { label: string; value: DraftStatus | undefined }[] = [
  { label: "Pending", value: "pending" },
  { label: "Sent", value: "sent" },
  { label: "Failed", value: "failed" },
  { label: "Rejected", value: "rejected" },
  { label: "All", value: undefined },
];

export default function DraftsPage() {
  const [tab, setTab] = useState<DraftStatus | undefined>("pending");
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["drafts", tab],
    queryFn: () => api.getDrafts(tab),
  });

  const approveMut = useMutation({
    mutationFn: (id: string) => api.approveDraft(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drafts"] }),
    onError: (error: Error) => {
      if (error.name === "AbortError") {
        alert(
          "The request took too long, but the reply may have been posted. Check the Sent tab to confirm."
        );
      } else {
        alert(error.message || "Failed to send. Check your API credentials.");
      }
      queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
  });

  const rejectMut = useMutation({
    mutationFn: (id: string) => api.rejectDraft(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drafts"] }),
  });

  const editMut = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      api.editDraft(id, content),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drafts"] }),
  });

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-serif font-semibold tracking-tight">Drafts</h1>

      <Tabs
        value={tab ?? "all"}
        onValueChange={(v) => setTab(v === "all" ? undefined : (v as DraftStatus))}
      >
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.label} value={t.value ?? "all"}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isLoading ? (
        <ListCardSkeleton rows={4} />
      ) : data?.drafts.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No drafts here"
          description="Generate replies from the Feed page to start the conversation."
        />
      ) : (
        <div className="space-y-3">
          {data?.drafts.map((draft) => (
            <DraftCard
              key={draft.id}
              draft={draft}
              onApprove={(id) => approveMut.mutate(id)}
              onReject={(id) => rejectMut.mutate(id)}
              onEdit={(id, content) => editMut.mutate({ id, content })}
              loading={approveMut.isPending || rejectMut.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}
