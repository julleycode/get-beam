"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BlogPostAdmin } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type StatusFilter = "all" | "published" | "draft";

const QUERY_KEY = ["admin-blog"];

function StatusBadge({ status }: { status: string }) {
  if (status === "published") {
    return <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Published</Badge>;
  }
  if (status === "archived") {
    return <Badge className="bg-gray-100 text-gray-600 hover:bg-gray-100">Archived</Badge>;
  }
  return <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">Draft</Badge>;
}

export default function BlogAdminPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => api.getAdminPosts(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: QUERY_KEY });

  const publish = useMutation({
    mutationFn: (id: string) => api.publishPost(id),
    onSuccess: invalidate,
  });
  const unpublish = useMutation({
    mutationFn: (id: string) => api.unpublishPost(id),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deletePost(id),
    onSuccess: invalidate,
  });

  const busy = publish.isPending || unpublish.isPending || remove.isPending;

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");

  const posts = data?.posts ?? [];
  const counts = {
    all: posts.length,
    published: posts.filter((p) => p.status === "published").length,
    draft: posts.filter((p) => p.status !== "published").length,
  };
  const q = search.trim().toLowerCase();
  const filtered = posts.filter((p) => {
    const matchesStatus =
      statusFilter === "all"
        ? true
        : statusFilter === "published"
          ? p.status === "published"
          : p.status !== "published";
    const matchesSearch =
      !q || p.title.toLowerCase().includes(q) || p.slug.toLowerCase().includes(q);
    return matchesStatus && matchesSearch;
  });

  const FILTERS: { key: StatusFilter; label: string }[] = [
    { key: "all", label: `All (${counts.all})` },
    { key: "published", label: `Published (${counts.published})` },
    { key: "draft", label: `Drafts (${counts.draft})` },
  ];

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-serif text-2xl font-semibold tracking-tight">Blog</h1>
          <p className="text-sm text-muted-foreground">Write and publish posts to getbeam.fyi/blog.</p>
        </div>
        <Button asChild>
          <Link href="/dashboard/blog/new">New post</Link>
        </Button>
      </div>

      {isError && (
        <ErrorBanner message={(error as Error)?.message || "Failed to load posts."} onRetry={refetch} />
      )}

      {!isLoading && posts.length > 0 && (
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-1.5">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setStatusFilter(f.key)}
                className={`rounded-full px-3 py-1 text-sm transition-colors ${
                  statusFilter === f.key
                    ? "bg-[hsl(345,100%,60%)] text-white"
                    : "bg-secondary text-muted-foreground hover:text-foreground"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title or slug…"
            className="sm:max-w-xs"
          />
        </div>
      )}

      {isLoading ? (
        <ListCardSkeleton />
      ) : posts.length === 0 ? (
        <p className="text-muted-foreground">No posts yet. Create your first one.</p>
      ) : filtered.length === 0 ? (
        <p className="text-muted-foreground">No posts match this filter.</p>
      ) : (
        <ul className="space-y-3">
          {filtered.map((post: BlogPostAdmin) => (
            <li key={post.id}>
              <Card>
                <CardContent className="flex items-center justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={post.status} />
                      <Link
                        href={`/dashboard/blog/${post.id}`}
                        className="truncate font-medium hover:text-[hsl(345,100%,45%)]"
                      >
                        {post.title}
                      </Link>
                    </div>
                    <p className="mt-1 truncate text-xs text-muted-foreground">/{post.slug}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {post.status === "published" ? (
                      <>
                        <Button variant="outline" size="sm" asChild>
                          <a href={`/blog/${post.slug}`} target="_blank" rel="noreferrer">View</a>
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => unpublish.mutate(post.id)}
                        >
                          Unpublish
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        disabled={busy}
                        onClick={() => publish.mutate(post.id)}
                      >
                        Publish
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        if (confirm(`Delete "${post.title}"? This cannot be undone.`)) {
                          remove.mutate(post.id);
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
