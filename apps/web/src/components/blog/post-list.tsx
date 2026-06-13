import Link from "next/link";
import type { BlogPost } from "@/lib/api";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Renders a list of blog posts (shared by the index and tag hub pages). */
export function PostList({ posts }: { posts: BlogPost[] }) {
  if (posts.length === 0) {
    return <p className="mt-10 text-muted-foreground">No posts yet. Check back soon.</p>;
  }
  return (
    <ul className="mt-10 space-y-10">
      {posts.map((post) => (
        <li key={post.id}>
          <article>
            <Link href={`/blog/${post.slug}`} className="group block">
              <h2 className="font-serif text-2xl font-semibold tracking-tight transition-colors group-hover:text-[hsl(345,100%,45%)]">
                {post.title}
              </h2>
              {post.excerpt && <p className="mt-2 text-foreground/80">{post.excerpt}</p>}
              <div className="mt-3 flex items-center gap-3 text-sm text-muted-foreground">
                {post.published_at && (
                  <time dateTime={post.published_at}>{formatDate(post.published_at)}</time>
                )}
                {post.reading_time_minutes && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{post.reading_time_minutes} min read</span>
                  </>
                )}
              </div>
            </Link>
            {post.tags && post.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {post.tags.map((t) => (
                  <Link
                    key={t}
                    href={`/blog/tag/${encodeURIComponent(t)}`}
                    className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {t}
                  </Link>
                ))}
              </div>
            )}
          </article>
        </li>
      ))}
    </ul>
  );
}
