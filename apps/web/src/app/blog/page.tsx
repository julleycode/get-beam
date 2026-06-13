import Link from "next/link";
import { fetchPublishedPosts } from "@/lib/blog-fetch";

// Dynamic: the list is fetched no-store so newly published/unpublished posts
// show immediately rather than lagging an ISR window.
export const dynamic = "force-dynamic";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function BlogIndexPage() {
  const posts = await fetchPublishedPosts();

  return (
    <div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight">Blog</h1>
      <p className="mt-2 text-muted-foreground">
        Turning anonymous website traffic into pipeline.
      </p>

      {posts.length === 0 ? (
        <p className="mt-10 text-muted-foreground">No posts yet. Check back soon.</p>
      ) : (
        <ul className="mt-10 space-y-10">
          {posts.map((post) => (
            <li key={post.id}>
              <article>
                <Link href={`/blog/${post.slug}`} className="group block">
                  <h2 className="font-serif text-2xl font-semibold tracking-tight transition-colors group-hover:text-[hsl(345,100%,45%)]">
                    {post.title}
                  </h2>
                  {post.excerpt && (
                    <p className="mt-2 text-foreground/80">{post.excerpt}</p>
                  )}
                  <div className="mt-3 flex items-center gap-3 text-sm text-muted-foreground">
                    {post.published_at && (
                      <time dateTime={post.published_at}>
                        {formatDate(post.published_at)}
                      </time>
                    )}
                    {post.reading_time_minutes && (
                      <>
                        <span aria-hidden>·</span>
                        <span>{post.reading_time_minutes} min read</span>
                      </>
                    )}
                  </div>
                </Link>
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
