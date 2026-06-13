"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BlogPostInput } from "@/lib/api";
import { PostForm } from "@/components/blog/post-form";
import { FormCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";

export default function EditBlogPostPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  // Reuse the admin list cache (P1 has no get-admin-by-id endpoint).
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-blog"],
    queryFn: () => api.getAdminPosts(),
  });

  const post = data?.posts.find((p) => p.id === params.id);

  const update = useMutation({
    mutationFn: (input: BlogPostInput) => api.updatePost(params.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-blog"] });
      router.push("/dashboard/blog");
    },
  });

  return (
    <div className="mx-auto max-w-5xl">
      <Link href="/dashboard/blog" className="text-sm text-muted-foreground hover:text-foreground">
        ← Back to posts
      </Link>
      <h1 className="mb-6 mt-3 font-serif text-2xl font-semibold tracking-tight">Edit post</h1>

      {isError && (
        <ErrorBanner message={(error as Error)?.message || "Failed to load post."} onRetry={refetch} />
      )}

      {isLoading ? (
        <FormCardSkeleton fields={5} />
      ) : !post ? (
        <p className="text-muted-foreground">Post not found.</p>
      ) : (
        <PostForm
          initial={post}
          submitLabel="Save changes"
          submitting={update.isPending}
          error={update.isError ? (update.error as Error).message : null}
          onSubmit={(input) => update.mutate(input)}
        />
      )}
    </div>
  );
}
