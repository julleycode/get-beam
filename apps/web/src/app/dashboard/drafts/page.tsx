"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type DraftStatus } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { DraftCard } from "@/components/draft-card";

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

      <div className="flex gap-2 border-b border-gray-200 pb-2">
        {TABS.map((t) => (
          <button
            key={t.label}
            onClick={() => setTab(t.value)}
            className={`text-sm px-3 py-1.5 rounded-t-md ${
              tab === t.value
                ? "bg-[#FF3366] text-white"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <ListCardSkeleton rows={4} />
      ) : data?.drafts.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
          <p className="text-gray-500">No drafts here.</p>
          <p className="text-sm text-gray-400 mt-1">
            Generate replies from the Feed page.
          </p>
        </div>
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
