import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Markdown } from "@/components/blog/markdown";
import {
  REVALIDATE_SECONDS,
  SITE_URL,
  fetchPublishedPost,
  fetchPublishedPosts,
} from "@/lib/blog-fetch";

export const revalidate = 300;

type Params = { params: { slug: string } };

// Pre-render known published slugs at build; new ones render on-demand (ISR).
export async function generateStaticParams() {
  const posts = await fetchPublishedPosts();
  return posts.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const post = await fetchPublishedPost(params.slug);
  if (!post) return { title: "Post not found" };

  const canonical = post.canonical_url || `${SITE_URL}/blog/${post.slug}`;
  const description = post.meta_description || post.excerpt || undefined;
  // Fall back to the site's default social card so every post has an OG image
  // (a card-less link previews poorly and the twitter summary_large_image needs
  // an image to render). Posts can still override via og_image_url/cover.
  const ogImage =
    post.og_image_url || post.cover_image_url || `${SITE_URL}/beam/social-share.png`;

  return {
    title: post.meta_title || post.title,
    description,
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: post.meta_title || post.title,
      description,
      url: canonical,
      images: [{ url: ogImage }],
      publishedTime: post.published_at || undefined,
      authors: [post.author_name],
    },
    twitter: {
      card: "summary_large_image",
      title: post.meta_title || post.title,
      description,
      images: [ogImage],
    },
  };
}

// Pull an FAQ section ("## Frequently asked questions", ### question / answer)
// out of the body so it can be emitted as FAQPage structured data — the format
// AI answer engines and Google's FAQ rich result quote most.
function extractFaq(md: string): { q: string; a: string }[] {
  const section = md.match(
    /##\s+Frequently asked questions\s*([\s\S]*?)(?=\n##\s|$)/i
  );
  if (!section) return [];
  // Lead with "\n" so the first "### " is always a split boundary (the section
  // regex may have consumed the newline before it); slice(1) drops the preamble.
  return `\n${section[1]}`
    .split(/\n###\s+/)
    .slice(1)
    .map((part) => {
      const nl = part.indexOf("\n");
      const q = (nl === -1 ? part : part.slice(0, nl)).trim();
      const a = (nl === -1 ? "" : part.slice(nl + 1))
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // markdown links → text
        .replace(/\*\*|__|`/g, "")
        .trim();
      return { q, a };
    })
    .filter((f) => f.q && f.a);
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function BlogPostPage({ params }: Params) {
  const post = await fetchPublishedPost(params.slug);
  if (!post) notFound();

  // Internal links out to sibling posts. Without a post→post link each post is
  // orphaned ("Referring page: None detected"), so Google leaves it
  // "Discovered - currently not indexed". Prefer same-tag siblings, backfill
  // with recent, dedupe and drop self. These MUST use the ISR option: a
  // no-store fetch here would opt the whole post route out of static rendering
  // and dead-letter the `export const revalidate` above.
  const primaryTag = post.tags?.[0];
  const [byTag, recent] = await Promise.all([
    primaryTag
      ? fetchPublishedPosts(8, primaryTag, { revalidate: REVALIDATE_SECONDS })
      : Promise.resolve([]),
    fetchPublishedPosts(8, undefined, { revalidate: REVALIDATE_SECONDS }),
  ]);
  const related = [...byTag, ...recent]
    .filter((p) => p.slug !== post.slug)
    .filter((p, i, arr) => arr.findIndex((x) => x.slug === p.slug) === i)
    .slice(0, 4);

  const canonical = post.canonical_url || `${SITE_URL}/blog/${post.slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: post.title,
    description: post.meta_description || post.excerpt || undefined,
    datePublished: post.published_at || undefined,
    dateModified: post.published_at || undefined,
    author: { "@type": "Person", name: post.author_name },
    image: post.og_image_url || post.cover_image_url || `${SITE_URL}/beam/social-share.png`,
    mainEntityOfPage: { "@type": "WebPage", "@id": canonical },
    url: canonical,
  };

  const faqs = extractFaq(post.body_markdown);
  const faqLd =
    faqs.length > 0
      ? {
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: faqs.map((f) => ({
            "@type": "Question",
            name: f.q,
            acceptedAnswer: { "@type": "Answer", text: f.a },
          })),
        }
      : null;

  return (
    <article className="rounded-2xl border border-[rgba(43,37,48,0.06)] bg-white p-6 sm:p-10">
      {/* JSON-LD structured data (our own data, not user raw HTML) */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {faqLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }}
        />
      )}

      <a href="/blog" className="text-sm text-muted-foreground hover:text-foreground">
        ← All posts
      </a>

      <h1 className="mt-4 font-serif text-4xl font-semibold leading-tight tracking-tight">
        {post.title}
      </h1>

      <div className="mt-3 flex items-center gap-3 text-sm text-muted-foreground">
        <span>{post.author_name}</span>
        {post.published_at && (
          <>
            <span aria-hidden>·</span>
            <time dateTime={post.published_at}>{formatDate(post.published_at)}</time>
          </>
        )}
        {post.reading_time_minutes && (
          <>
            <span aria-hidden>·</span>
            <span>{post.reading_time_minutes} min read</span>
          </>
        )}
      </div>

      {post.tags && post.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {post.tags.map((t) => (
            <a
              key={t}
              href={`/blog/tag/${encodeURIComponent(t)}`}
              className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              {t}
            </a>
          ))}
        </div>
      )}

      {post.cover_image_url && (
        // Plain <img> avoids next/image remote-host config (P2 scope decision).
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={post.cover_image_url}
          alt={post.title}
          className="mt-6 w-full rounded-xl border border-[rgba(43,37,48,0.08)]"
        />
      )}

      <div className="mt-8">
        <Markdown>{post.body_markdown}</Markdown>
      </div>

      {related.length > 0 && (
        <aside className="mt-12 border-t border-[rgba(43,37,48,0.08)] pt-8">
          <h2 className="font-serif text-2xl font-semibold tracking-tight">
            Related posts
          </h2>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {related.map((p) => (
              <li key={p.slug}>
                <a
                  href={`/blog/${p.slug}`}
                  className="block h-full rounded-xl border border-[rgba(43,37,48,0.08)] p-4 transition-colors hover:border-[rgba(43,37,48,0.2)]"
                >
                  <span className="block font-medium leading-snug">{p.title}</span>
                  {p.excerpt && (
                    <span className="mt-1 block text-sm text-muted-foreground">
                      {p.excerpt}
                    </span>
                  )}
                </a>
              </li>
            ))}
          </ul>
        </aside>
      )}
    </article>
  );
}
