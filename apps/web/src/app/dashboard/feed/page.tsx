"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Rss } from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { FeedHelp } from "@/components/page-help";
import { api, type Platform, type GenerateMultiDraftResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ListCardSkeleton } from "@/components/skeletons";
import { PostCard } from "@/components/post-card";
import { DraftPicker } from "@/components/draft-picker";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const PLATFORMS: (Platform | "all")[] = [
  "all",
  "twitter",
  "facebook",
  "instagram",
  "linkedin",
  "tiktok",
];

const SOURCES = [
  { value: "", label: "All Posts" },
  { value: "visitors", label: "🎯 Visitors" },
  { value: "following", label: "👥 Following" },
  { value: "my_posts", label: "📝 My Posts" },
] as const;

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
  const [source, setSource] = useState("");
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
    queryKey: ["feed", page, filterPlatform, dateFrom, dateTo, source],
    queryFn: () =>
      api.getFeed(
        page,
        filterPlatform,
        dateFrom || undefined,
        dateTo || undefined,
        source || undefined,
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
      const message =
        error.name === "AbortError"
          ? "Reply generation took too long. The AI provider may be slow. Please try again."
          : error.message || "Failed to generate draft.";
      setToast({ message, type: "error" });
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
      const rawMsg =
        error instanceof Error ? error.message : "Failed to send reply";
      // A draft that is no longer "pending" can never be approved from here
      // again — this happens when it was already used, when its siblings were
      // auto-rejected after picking another reply, or when it was approved but
      // sending to the platform failed (status becomes "failed"). In all these
      // cases the cached draft snapshot is stale, so drop the whole post's
      // drafts to remove the dead "Approve & Send" button instead of letting
      // the user re-click it into the confusing "Can only approve pending
      // drafts" error.
      const noLongerPending = /can only approve pending drafts/i.test(rawMsg);
      const sendFailed =
        /couldn't be sent to|sending to .* failed/i.test(rawMsg);
      if (noLongerPending || sendFailed) {
        setDraftData((prev) => {
          const next = { ...prev };
          delete next[postId];
          return next;
        });
        queryClient.invalidateQueries({ queryKey: ["feed"] });
        queryClient.invalidateQueries({ queryKey: ["drafts"] });
      }
      const message = noLongerPending
        ? "This draft is no longer available (already used, replaced, or expired). Generate a new reply to try again."
        : sendFailed
          ? "Reply approved but couldn't be sent. Reconnect your account in Social Accounts and try again."
          : rawMsg;
      setToast({ message, type: "error" });
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
          className={cn(
            "fixed right-4 top-4 z-50 rounded-lg px-4 py-3 text-sm font-medium shadow-lg",
            toast.type === "success"
              ? "bg-success text-primary-foreground"
              : "bg-destructive text-destructive-foreground"
          )}
        >
          <div className="flex items-center gap-2">
            <span>{toast.message}</span>
            <button onClick={() => setToast(null)} className="ml-2 opacity-80 hover:opacity-100">
              x
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-1.5 text-2xl font-serif font-semibold tracking-tight">
          Feed
          <InfoTooltip label="About Feed" align="start">
            <FeedHelp />
          </InfoTooltip>
        </h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowImport(!showImport)}>
            + Import Post
          </Button>
          <Button
            size="sm"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? "Syncing..." : "Sync Now"}
          </Button>
        </div>
      </div>

      {showImport && (
        <div className="space-y-3 rounded-lg border bg-secondary/60 p-4">
          <p className="text-sm font-medium">
            Paste a tweet/post URL to add it to your feed and generate a reply
          </p>
          <Input
            type="text"
            placeholder="https://x.com/user/status/123456..."
            value={importUrl}
            onChange={(e) => setImportUrl(e.target.value)}
          />
          <Input
            type="text"
            placeholder="Author name (e.g. Elon Musk @elonmusk)"
            value={importAuthor}
            onChange={(e) => setImportAuthor(e.target.value)}
          />
          <Textarea
            placeholder="Paste the post content here..."
            value={importContent}
            onChange={(e) => setImportContent(e.target.value)}
            rows={3}
            className="resize-none"
          />
          <div className="flex items-center justify-between">
            {importUrl && (
              <span className="rounded bg-primary/10 px-2 py-1 text-xs text-primary">
                Detected: {detectPlatform(importUrl)}
              </span>
            )}
            <div className="ml-auto flex gap-2">
              <Button variant="ghost" size="sm" onClick={() => setShowImport(false)}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleImport} disabled={!importUrl.trim()}>
                Import & Add to Feed
              </Button>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-3">
        {/* Source tabs */}
        <div className="flex flex-wrap gap-2">
          {SOURCES.map((s) => (
            <button
              key={s.value}
              onClick={() => { setSource(s.value); setPage(1); }}
              className={cn(
                "rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                source === s.value
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "border border-border bg-card text-muted-foreground hover:bg-secondary"
              )}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* Platform filter */}
        <div className="flex flex-wrap gap-2">
          {PLATFORMS.map((p) => (
            <button
              key={p}
              onClick={() => { setPlatform(p); setPage(1); }}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs transition-colors",
                platform === p
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-secondary"
              )}
            >
              {p === "all" ? "All" : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs font-medium text-muted-foreground">Date:</label>
          <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-2 py-1.5 text-xs text-foreground" />
          <span className="text-xs text-muted-foreground">to</span>
          <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-2 py-1.5 text-xs text-foreground" />
          {(dateFrom || dateTo) && (
            <Button variant="ghost" size="sm" onClick={() => { setDateFrom(""); setDateTo(""); setPage(1); }}>
              Clear dates
            </Button>
          )}
        </div>
      </div>

      {isLoading ? (
        <ListCardSkeleton rows={5} leading />
      ) : data?.posts.length === 0 ? (
        <EmptyState
          icon={Rss}
          title="No posts yet"
          description="Connect an account and sync to see posts, or import a post by URL."
        />
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
          <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">Page {page} of {Math.ceil(data.total / data.per_page)}</span>
          <Button variant="outline" size="sm" onClick={() => setPage((p) => p + 1)} disabled={page * data.per_page >= data.total}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
