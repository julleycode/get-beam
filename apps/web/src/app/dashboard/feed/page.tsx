"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Platform, type GenerateMultiDraftResponse } from "@/lib/api";
import { PostCard } from "@/components/post-card";
import { DraftPicker } from "@/components/draft-picker";

const PLATFORMS: (Platform | "all")[] = [
  "all",
  "twitter",
  "facebook",
  "instagram",
  "linkedin",
  "tiktok",
];

export default function FeedPage() {
  const [page, setPage] = useState(1);
  const [platform, setPlatform] = useState<Platform | "all">("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);
  const [draftData, setDraftData] = useState<
    Record<string, GenerateMultiDraftResponse>
  >({});
  const [approvingDraft, setApprovingDraft] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importContent, setImportContent] = useState("");
  const [importAuthor, setImportAuthor] = useState("");
  const [toast, setToast] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  const filterPlatform = platform === "all" ? undefined : platform;

  const { data, isLoading } = useQuery({
    queryKey: ["feed", page, filterPlatform, dateFrom, dateTo],
    queryFn: () =>
      api.getFeed(
        page,
        filterPlatform,
        dateFrom || undefined,
        dateTo || undefined
      ),
  });

  const syncMutation = useMutation({
    mutationFn: () => api.triggerSync(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feed"] });
      setToast({ message: "Feed synced successfully!", type: "success" });
    },
    onError: (error: Error) => {
      setToast({ message: error.message || "Sync failed.", type: "error" });
    },
  });

  const draftMutation = useMutation({
    mutationFn: (postId: string) => api.generateDraft(postId),
    onSuccess: (response, postId) => {
      setGeneratingFor(null);
      setDraftData((prev) => ({ ...prev, [postId]: response }));
    },
    onError: (error: Error) => {
      setGeneratingFor(null);
      setToast({ message: error.message || "Failed to generate draft.", type: "error" });
    },
  });

  const handleGenerateDraft = (postId: string) => {
    setGeneratingFor(postId);
    draftMutation.mutate(postId);
  };

  const handleApproveDraft = async (postId: string, draftId: string) => {
    setApprovingDraft(draftId);
    try {
      await api.approveDraft(draftId);
      setDraftData((prev) => {
        const next = { ...prev };
        delete next[postId];
        return next;
      });
      queryClient.invalidateQueries({ queryKey: ["feed"] });
      queryClient.invalidateQueries({ queryKey: ["drafts"] });
      setToast({ message: "Reply sent!", type: "success" });
    } catch (error) {
      setToast({
        message: error instanceof Error ? error.message : "Failed to send reply",
        type: "error",
      });
    } finally {
      setApprovingDraft(null);
    }
  };

  const handleRejectDraft = async (postId: string, draftId: string) => {
    try {
      await api.rejectDraft(draftId);
      setDraftData((prev) => {
        const current = prev[postId];
        if (!current) return prev;
        const remaining = current.drafts.filter((d) => d.id !== draftId);
        if (remaining.length === 0) {
          const next = { ...prev };
          delete next[postId];
          return next;
        }
        return { ...prev, [postId]: { ...current, drafts: remaining } };
      });
    } catch (error) {
      setToast({
        message: error instanceof Error ? error.message : "Failed to reject draft",
        type: "error",
      });
    }
  };

  const handleEditDraft = async (draftId: string, content: string) => {
    try {
      const updated = await api.editDraft(draftId, content);
      setDraftData((prev) => {
        const next = { ...prev };
        for (const postId of Object.keys(next)) {
          next[postId] = {
            ...next[postId],
            drafts: next[postId].drafts.map((d) =>
              d.id === draftId
                ? { ...d, edited_content: updated.edited_content }
                : d
            ),
          };
        }
        return next;
      });
    } catch (error) {
      setToast({
        message: error instanceof Error ? error.message : "Failed to save edit",
        type: "error",
      });
    }
  };

  const handleDismissDrafts = (postId: string) => {
    setDraftData((prev) => {
      const next = { ...prev };
      delete next[postId];
      return next;
    });
  };

  const detectPlatform = (url: string): Platform => {
    if (url.includes("twitter.com") || url.includes("x.com")) return "twitter";
    if (url.includes("facebook.com") || url.includes("fb.com")) return "facebook";
    if (url.includes("instagram.com")) return "instagram";
    if (url.includes("linkedin.com")) return "linkedin";
    if (url.includes("tiktok.com")) return "tiktok";
    return "twitter";
  };

  const handleImport = () => {
    if (!importUrl.trim()) return;
    const detectedPlatform = detectPlatform(importUrl);
    const authorParts = importAuthor.trim().split(/\s*@\s*/);
    api
      .importPost({
        url: importUrl.trim(),
        platform: detectedPlatform,
        content: importContent.trim(),
        author_name: authorParts[0] || "Unknown",
        author_username:
          authorParts.length > 1 ? authorParts[1] : authorParts[0] || "unknown",
      })
      .then(() => {
        setShowImport(false);
        setImportUrl("");
        setImportContent("");
        setImportAuthor("");
        queryClient.invalidateQueries({ queryKey: ["feed"] });
      })
      .catch((err: Error) => {
        setToast({ message: err.message || "Import failed", type: "error" });
      });
  };

  return (
    <div className="max-w-3xl space-y-4 relative">
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium ${
            toast.type === "success"
              ? "bg-green-600 text-white"
              : "bg-red-600 text-white"
          }`}
        >
          <div className="flex items-center gap-2">
            <span>{toast.message}</span>
            <button onClick={() => setToast(null)} className="ml-2 text-white/80 hover:text-white">
              x
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Feed</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setShowImport(!showImport)}
            className="text-sm px-4 py-2 rounded-md border border-indigo-300 text-indigo-600 hover:bg-indigo-50"
          >
            + Import Post
          </button>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="text-sm px-4 py-2 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {syncMutation.isPending ? "Syncing..." : "Sync Now"}
          </button>
        </div>
      </div>

      {showImport && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 space-y-3">
          <p className="text-sm font-medium text-indigo-900">
            Paste a tweet/post URL to add it to your feed and generate a reply
          </p>
          <input
            type="text"
            placeholder="https://x.com/user/status/123456..."
            value={importUrl}
            onChange={(e) => setImportUrl(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-indigo-200 rounded-md bg-white"
          />
          <input
            type="text"
            placeholder="Author name (e.g. Elon Musk @elonmusk)"
            value={importAuthor}
            onChange={(e) => setImportAuthor(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-indigo-200 rounded-md bg-white"
          />
          <textarea
            placeholder="Paste the post content here..."
            value={importContent}
            onChange={(e) => setImportContent(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 text-sm border border-indigo-200 rounded-md bg-white resize-none"
          />
          <div className="flex items-center justify-between">
            {importUrl && (
              <span className="text-xs text-indigo-600 bg-indigo-100 px-2 py-1 rounded">
                Detected: {detectPlatform(importUrl)}
              </span>
            )}
            <div className="flex gap-2 ml-auto">
              <button
                onClick={() => setShowImport(false)}
                className="text-sm px-3 py-1.5 rounded-md text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={!importUrl.trim()}
                className="text-sm px-4 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                Import & Add to Feed
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-3">
        <div className="flex gap-2">
          {PLATFORMS.map((p) => (
            <button
              key={p}
              onClick={() => { setPlatform(p); setPage(1); }}
              className={`text-xs px-3 py-1.5 rounded-full border ${
                platform === p
                  ? "bg-indigo-600 text-white border-indigo-600"
                  : "bg-white text-gray-600 border-gray-300 hover:bg-gray-50"
              }`}
            >
              {p === "all" ? "All" : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <label className="text-xs font-medium text-gray-500">Date:</label>
          <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
            className="text-xs px-2 py-1.5 border border-gray-300 rounded-md bg-white text-gray-700" />
          <span className="text-xs text-gray-400">to</span>
          <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
            className="text-xs px-2 py-1.5 border border-gray-300 rounded-md bg-white text-gray-700" />
          {(dateFrom || dateTo) && (
            <button onClick={() => { setDateFrom(""); setDateTo(""); setPage(1); }}
              className="text-xs px-2 py-1.5 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100">
              Clear dates
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-400">Loading feed...</p>
      ) : data?.posts.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
          <p className="text-gray-500">No posts yet.</p>
          <p className="text-sm text-gray-400 mt-1">
            Connect an account and sync to see posts, or import a post by URL.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {data?.posts.map((post) => (
            <div key={post.id} className="space-y-2">
              <PostCard post={post} onGenerateDraft={handleGenerateDraft} loading={generatingFor === post.id} />
              {draftData[post.id] && (
                <DraftPicker
                  data={draftData[post.id]}
                  onApprove={(draftId) => handleApproveDraft(post.id, draftId)}
                  onReject={(draftId) => handleRejectDraft(post.id, draftId)}
                  onEdit={handleEditDraft}
                  onDismiss={() => handleDismissDrafts(post.id)}
                  loading={approvingDraft !== null}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {data && data.total > data.per_page && (
        <div className="flex items-center justify-center gap-4 pt-4">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}
            className="text-sm px-3 py-1 rounded border disabled:opacity-30">Previous</button>
          <span className="text-sm text-gray-500">Page {page} of {Math.ceil(data.total / data.per_page)}</span>
          <button onClick={() => setPage((p) => p + 1)} disabled={page * data.per_page >= data.total}
            className="text-sm px-3 py-1 rounded border disabled:opacity-30">Next</button>
        </div>
      )}
    </div>
  );
}
