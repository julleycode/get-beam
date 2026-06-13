"use client";

import { useState } from "react";
import type { BlogPostAdmin, BlogPostInput } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Markdown } from "@/components/blog/markdown";

interface PostFormProps {
  initial?: BlogPostAdmin;
  submitLabel: string;
  submitting: boolean;
  error: string | null;
  onSubmit: (data: BlogPostInput) => void;
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function PostForm({
  initial,
  submitLabel,
  submitting,
  error,
  onSubmit,
}: PostFormProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [excerpt, setExcerpt] = useState(initial?.excerpt ?? "");
  const [body, setBody] = useState(initial?.body_markdown ?? "");
  const [tags, setTags] = useState((initial?.tags ?? []).join(", "));
  const [coverImageUrl, setCoverImageUrl] = useState(initial?.cover_image_url ?? "");
  const [metaTitle, setMetaTitle] = useState(initial?.meta_title ?? "");
  const [metaDescription, setMetaDescription] = useState(initial?.meta_description ?? "");
  const [canonicalUrl, setCanonicalUrl] = useState(initial?.canonical_url ?? "");
  const [ogImageUrl, setOgImageUrl] = useState(initial?.og_image_url ?? "");
  const [touched, setTouched] = useState(false);

  const titleError = touched && title.trim().length === 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (title.trim().length === 0) return;
    const tagList = tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    onSubmit({
      title: title.trim(),
      slug: slug.trim() || undefined,
      excerpt: excerpt.trim() || null,
      body_markdown: body,
      tags: tagList.length ? tagList : null,
      cover_image_url: coverImageUrl.trim() || null,
      meta_title: metaTitle.trim() || null,
      meta_description: metaDescription.trim() || null,
      canonical_url: canonicalUrl.trim() || null,
      og_image_url: ogImageUrl.trim() || null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-8 lg:grid-cols-2">
      <div className="space-y-5">
        <Field label="Title" htmlFor="title">
          <Input
            id="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => setTouched(true)}
            placeholder="How to identify anonymous visitors"
            aria-invalid={titleError}
          />
          {titleError && <p className="text-xs text-red-600">Title is required.</p>}
        </Field>

        <Field label="Slug" htmlFor="slug" hint="Leave blank to auto-generate from the title.">
          <Input
            id="slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="auto"
          />
        </Field>

        <Field label="Excerpt" htmlFor="excerpt" hint="Short summary for listings + meta description fallback.">
          <Textarea
            id="excerpt"
            value={excerpt}
            onChange={(e) => setExcerpt(e.target.value)}
            rows={2}
          />
        </Field>

        <Field label="Body (Markdown)" htmlFor="body">
          <Textarea
            id="body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={16}
            className="font-mono text-[13px]"
          />
        </Field>

        <Field label="Tags" htmlFor="tags" hint="Comma-separated.">
          <Input
            id="tags"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="retargeting, seo, guide"
          />
        </Field>

        <details className="rounded-lg border border-[rgba(43,37,48,0.12)] p-4">
          <summary className="cursor-pointer text-sm font-medium">SEO &amp; images</summary>
          <div className="mt-4 space-y-4">
            <Field label="Cover image URL" htmlFor="cover">
              <Input id="cover" value={coverImageUrl} onChange={(e) => setCoverImageUrl(e.target.value)} />
            </Field>
            <Field label="Meta title" htmlFor="meta-title" hint="Falls back to title.">
              <Input id="meta-title" value={metaTitle} onChange={(e) => setMetaTitle(e.target.value)} />
            </Field>
            <Field label="Meta description" htmlFor="meta-desc" hint="Falls back to excerpt.">
              <Textarea id="meta-desc" value={metaDescription} onChange={(e) => setMetaDescription(e.target.value)} rows={2} />
            </Field>
            <Field label="Canonical URL" htmlFor="canonical">
              <Input id="canonical" value={canonicalUrl} onChange={(e) => setCanonicalUrl(e.target.value)} />
            </Field>
            <Field label="OG image URL" htmlFor="og" hint="Falls back to cover image.">
              <Input id="og" value={ogImageUrl} onChange={(e) => setOgImageUrl(e.target.value)} />
            </Field>
          </div>
        </details>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <Button type="submit" disabled={submitting}>
          {submitting ? "Saving…" : submitLabel}
        </Button>
      </div>

      {/* Live preview */}
      <div className="lg:sticky lg:top-6 lg:self-start">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Preview
        </p>
        <div className="rounded-xl border border-[rgba(43,37,48,0.08)] bg-card p-6">
          <h1 className="font-serif text-2xl font-semibold tracking-tight">
            {title || "Untitled"}
          </h1>
          <div className="mt-4">
            <Markdown>{body || "_Nothing to preview yet._"}</Markdown>
          </div>
        </div>
      </div>
    </form>
  );
}
