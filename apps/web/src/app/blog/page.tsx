import { fetchPublishedPosts } from "@/lib/blog-fetch";
import { PostList } from "@/components/blog/post-list";

// Dynamic: the list is fetched no-store so newly published/unpublished posts
// show immediately rather than lagging an ISR window.
export const dynamic = "force-dynamic";

export default async function BlogIndexPage() {
  // Fetch up to the API max (100) so every published post is linked from the
  // index. The default 50 left later posts orphaned from the index HTML, which
  // leaves Google with "Discovered - currently not indexed".
  const posts = await fetchPublishedPosts(100);

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
