"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type BlogPostInput } from "@/lib/api";
import { PostForm } from "@/components/blog/post-form";

export default function NewBlogPostPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: (data: BlogPostInput) => api.createPost(data),
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
      <h1 className="mb-6 mt-3 font-serif text-2xl font-semibold tracking-tight">New post</h1>
      <PostForm
        submitLabel="Create draft"
        submitting={create.isPending}
        error={create.isError ? (create.error as Error).message : null}
        onSubmit={(data) => create.mutate(data)}
      />
    </div>
  );
}
