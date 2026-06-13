"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BlogPostAdmin } from "@/lib/api";
import { ListCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

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

      {isLoading ? (
        <ListCardSkeleton />
      ) : !data || data.posts.length === 0 ? (
        <p className="text-muted-foreground">No posts yet. Create your first one.</p>
      ) : (
        <ul className="space-y-3">
          {data.posts.map((post: BlogPostAdmin) => (
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
