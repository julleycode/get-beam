import { fetchPublishedPosts } from "@/lib/blog-fetch";
import { PostList } from "@/components/blog/post-list";

// Dynamic: the list is fetched no-store so newly published/unpublished posts
// show immediately rather than lagging an ISR window.
export const dynamic = "force-dynamic";

export default async function BlogIndexPage() {
  const posts = await fetchPublishedPosts();

  return (
    <div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight">Blog</h1>
      <p className="mt-2 text-muted-foreground">
        Turning anonymous website traffic into pipeline.
      </p>
      <PostList posts={posts} />
    </div>
  );
}
