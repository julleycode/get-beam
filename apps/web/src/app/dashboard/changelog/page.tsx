"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ChangelogCategory, type ChangelogEntryAdmin } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const QUERY_KEY = ["admin-changelog"];

const CATEGORIES: ChangelogCategory[] = ["new", "improved", "fixed"];

function CategoryBadge({ category }: { category: string }) {
  if (category === "improved") {
    return <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100">Improved</Badge>;
  }
  if (category === "fixed") {
    return <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">Fixed</Badge>;
  }
  return <Badge className="bg-green-100 text-green-700 hover:bg-green-100">New</Badge>;
}

function StatusBadge({ status }: { status: string }) {
  if (status === "published") {
    return <Badge variant="outline" className="border-green-300 text-green-700">Published</Badge>;
  }
  return <Badge variant="outline" className="text-muted-foreground">Draft</Badge>;
}

type Draft = { title: string; body: string; category: ChangelogCategory };

const EMPTY_DRAFT: Draft = { title: "", body: "", category: "new" };

export default function ChangelogAdminPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => api.getAdminChangelog(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: QUERY_KEY });

  const [newDraft, setNewDraft] = useState<Draft>(EMPTY_DRAFT);
  // Per-row edit buffer, keyed by entry id. Present => that row is in edit mode.
  const [editing, setEditing] = useState<Record<string, Draft>>({});

  const create = useMutation({
    mutationFn: (d: Draft) => api.createChangelog(d),
    onSuccess: () => {
      setNewDraft(EMPTY_DRAFT);
      invalidate();
    },
  });
  const update = useMutation({
    mutationFn: ({ id, d }: { id: string; d: Draft }) => api.updateChangelog(id, d),
    onSuccess: (_res, vars) => {
      setEditing((s) => {
        const next = { ...s };
        delete next[vars.id];
        return next;
      });
      invalidate();
    },
  });
  const publish = useMutation({
    mutationFn: (id: string) => api.publishChangelog(id),
    onSuccess: invalidate,
  });
  const unpublish = useMutation({
    mutationFn: (id: string) => api.unpublishChangelog(id),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteChangelog(id),
    onSuccess: invalidate,
  });
  const sync = useMutation({
    mutationFn: () => api.syncChangelog(),
    onSuccess: invalidate,
  });

  const busy =
    create.isPending ||
    update.isPending ||
    publish.isPending ||
    unpublish.isPending ||
    remove.isPending ||
    sync.isPending;

  const entries = data?.entries ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-2xl font-semibold tracking-tight">Changelog</h1>
          <p className="text-sm text-muted-foreground">
            Short product updates for the &ldquo;what&apos;s new&rdquo; pill on getbeam.fyi.
            Published entries show on the landing page, newest first.
          </p>
        </div>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => sync.mutate()}
          title="Pull recent merged PRs, skip internal work, auto-publish the customer-facing ones."
        >
          {sync.isPending ? "Syncing…" : "Sync from GitHub"}
        </Button>
      </div>

      {sync.isError && (
        <div className="mb-4">
          <ErrorBanner
            message={
              (sync.error as Error)?.message ||
              "Sync failed. Is GITHUB_TOKEN configured on the API?"
            }
            onRetry={() => sync.mutate()}
          />
        </div>
      )}
      {sync.isSuccess && sync.data && (
        <p className="mb-4 rounded-md bg-secondary px-3 py-2 text-sm text-muted-foreground">
          Scanned {sync.data.scanned} PRs · published {sync.data.imported} new ·
          skipped {sync.data.skipped_internal} internal ·
          {sync.data.already_present} already there.
        </p>
      )}

      {/* Quick-add form */}
      <Card className="mb-6">
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">New update</p>
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground" htmlFor="cl-title">
              Title
            </label>
            <Input
              id="cl-title"
              value={newDraft.title}
              maxLength={255}
              onChange={(e) => setNewDraft((d) => ({ ...d, title: e.target.value }))}
              placeholder="Faster visitor identification"
            />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground" htmlFor="cl-body">
              One-line description
            </label>
            <Input
              id="cl-body"
              value={newDraft.body}
              maxLength={2000}
              onChange={(e) => setNewDraft((d) => ({ ...d, body: e.target.value }))}
              placeholder="Identity resolution now runs ~3x faster on first paint."
            />
          </div>
          <div className="flex items-end justify-between gap-3">
            <div className="flex flex-col gap-2">
              <label className="text-xs text-muted-foreground" htmlFor="cl-category">
                Category
              </label>
              <select
                id="cl-category"
                value={newDraft.category}
                onChange={(e) =>
                  setNewDraft((d) => ({ ...d, category: e.target.value as ChangelogCategory }))
                }
                className="rounded-md border border-[rgba(43,37,48,0.16)] bg-card px-3 py-2 text-sm capitalize"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <Button
              disabled={busy || !newDraft.title.trim()}
              onClick={() => create.mutate({ ...newDraft, title: newDraft.title.trim() })}
            >
              Add draft
            </Button>
          </div>
        </CardContent>
      </Card>

      {isError && (
        <ErrorBanner
          message={(error as Error)?.message || "Failed to load changelog."}
          onRetry={refetch}
        />
      )}

      {isLoading ? (
        <ListCardSkeleton />
      ) : entries.length === 0 ? (
        <p className="text-muted-foreground">No updates yet. Add your first one above.</p>
      ) : (
        <ul className="space-y-3">
          {entries.map((entry: ChangelogEntryAdmin) => {
            const edit = editing[entry.id];
            return (
              <li key={entry.id}>
                <Card>
                  <CardContent className="space-y-3 p-4">
                    {edit ? (
                      <div className="space-y-2">
                        <Input
                          value={edit.title}
                          maxLength={255}
                          onChange={(e) =>
                            setEditing((s) => ({
                              ...s,
                              [entry.id]: { ...edit, title: e.target.value },
                            }))
                          }
                        />
                        <Input
                          value={edit.body}
                          maxLength={2000}
                          onChange={(e) =>
                            setEditing((s) => ({
                              ...s,
                              [entry.id]: { ...edit, body: e.target.value },
                            }))
                          }
                        />
                        <div className="flex items-center justify-between gap-2">
                          <select
                            value={edit.category}
                            onChange={(e) =>
                              setEditing((s) => ({
                                ...s,
                                [entry.id]: {
                                  ...edit,
                                  category: e.target.value as ChangelogCategory,
                                },
                              }))
                            }
                            className="rounded-md border border-[rgba(43,37,48,0.16)] bg-card px-3 py-2 text-sm capitalize"
                          >
                            {CATEGORIES.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                          <div className="flex gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              onClick={() =>
                                setEditing((s) => {
                                  const next = { ...s };
                                  delete next[entry.id];
                                  return next;
                                })
                              }
                            >
                              Cancel
                            </Button>
                            <Button
                              size="sm"
                              disabled={busy || !edit.title.trim()}
                              onClick={() =>
                                update.mutate({
                                  id: entry.id,
                                  d: { ...edit, title: edit.title.trim() },
                                })
                              }
                            >
                              Save
                            </Button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-center gap-2">
                          <CategoryBadge category={entry.category} />
                          <StatusBadge status={entry.status} />
                          <span className="ml-auto text-xs text-muted-foreground">
                            {entry.published_at
                              ? new Date(entry.published_at).toLocaleDateString()
                              : "—"}
                          </span>
                        </div>
                        <div>
                          <p className="font-medium">{entry.title}</p>
                          {entry.body && (
                            <p className="mt-0.5 text-sm text-muted-foreground">{entry.body}</p>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              setEditing((s) => ({
                                ...s,
                                [entry.id]: {
                                  title: entry.title,
                                  body: entry.body,
                                  category: (entry.category as ChangelogCategory) ?? "new",
                                },
                              }))
                            }
                          >
                            Edit
                          </Button>
                          {entry.status === "published" ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              onClick={() => unpublish.mutate(entry.id)}
                            >
                              Unpublish
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              disabled={busy}
                              onClick={() => publish.mutate(entry.id)}
                            >
                              Publish
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            onClick={() => {
                              if (confirm(`Delete "${entry.title}"? This cannot be undone.`)) {
                                remove.mutate(entry.id);
                              }
                            }}
                          >
                            Delete
                          </Button>
                        </div>
                      </>
                    )}
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
