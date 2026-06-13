// Pure, framework-free on-page SEO analysis for the post editor.
// No persistence — runs live on the current form values.

export interface SeoCheck {
  id: string;
  label: string;
  pass: boolean;
  weight: number;
}

export interface SeoAnalysis {
  checks: SeoCheck[];
  score: number; // 0–100, weighted
  passed: number;
  total: number;
  titleLen: number;
  metaLen: number;
  wordCount: number;
  band: "good" | "ok" | "poor";
}

export const TITLE_MIN = 30;
export const TITLE_MAX = 60;
export const META_MIN = 70;
export const META_MAX = 160;
const MIN_WORDS = 300;

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function wordCountOf(markdown: string): number {
  return markdown
    .replace(/[#>*_`~\-]/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean).length;
}

function headingsOf(markdown: string): string[] {
  return markdown.match(/^#{2,3}\s+.+$/gm) ?? [];
}

function firstParagraphOf(markdown: string): string {
  return (
    markdown
      .split(/\n\s*\n/)
      .map((s) => s.trim())
      .find((s) => s.length > 0 && !s.startsWith("#")) ?? ""
  );
}

// Internal links: markdown [text](/path) or an absolute getbeam.fyi link.
function hasInternalLink(markdown: string): boolean {
  return /\]\(\s*(\/(?!\/)[^)]*|https?:\/\/(?:www\.)?getbeam\.fyi[^)]*)\)/i.test(
    markdown
  );
}

export interface SeoInput {
  title: string;
  slug: string;
  metaTitle: string;
  metaDescription: string;
  excerpt: string;
  body: string;
  focusKeyword: string;
}

export function effectiveTitle(input: SeoInput): string {
  return (input.metaTitle.trim() || input.title.trim());
}

export function effectiveMeta(input: SeoInput): string {
  return (input.metaDescription.trim() || input.excerpt.trim());
}

export function analyzeSeo(input: SeoInput): SeoAnalysis {
  const kw = input.focusKeyword.trim().toLowerCase();
  const hasKw = kw.length > 0;
  const title = effectiveTitle(input);
  const meta = effectiveMeta(input);
  const slug = (input.slug.trim() || slugify(input.title));
  const headings = headingsOf(input.body);
  const firstPara = firstParagraphOf(input.body);
  const titleLen = title.length;
  const metaLen = meta.length;
  const wordCount = wordCountOf(input.body);

  const contains = (hay: string) => hasKw && hay.toLowerCase().includes(kw);

  const checks: SeoCheck[] = [
    { id: "kw", label: "Focus keyword set", pass: hasKw, weight: 1 },
    { id: "kw-title", label: "Keyword in title", pass: contains(title), weight: 2 },
    {
      id: "kw-slug",
      label: "Keyword in URL slug",
      pass: hasKw && slug.includes(kw.replace(/\s+/g, "-")),
      weight: 1,
    },
    { id: "kw-intro", label: "Keyword in the intro", pass: contains(firstPara), weight: 1 },
    {
      id: "kw-heading",
      label: "Keyword in a subheading",
      pass: headings.some((h) => contains(h)),
      weight: 1,
    },
    {
      id: "title-len",
      label: `SEO title length ${titleLen} (${TITLE_MIN}–${TITLE_MAX})`,
      pass: titleLen >= TITLE_MIN && titleLen <= TITLE_MAX,
      weight: 1,
    },
    {
      id: "meta-len",
      label: meta
        ? `Meta description ${metaLen} (${META_MIN}–${META_MAX})`
        : "Meta description set",
      pass: metaLen >= META_MIN && metaLen <= META_MAX,
      weight: 2,
    },
    { id: "headings", label: "Has subheadings (H2/H3)", pass: headings.length >= 1, weight: 1 },
    {
      id: "words",
      label: `Word count ${wordCount} (≥${MIN_WORDS})`,
      pass: wordCount >= MIN_WORDS,
      weight: 1,
    },
    { id: "links", label: "Has an internal link", pass: hasInternalLink(input.body), weight: 1 },
  ];

  const totalWeight = checks.reduce((s, c) => s + c.weight, 0);
  const earned = checks.reduce((s, c) => s + (c.pass ? c.weight : 0), 0);
  const score = Math.round((earned / totalWeight) * 100);
  const band: SeoAnalysis["band"] = score >= 80 ? "good" : score >= 50 ? "ok" : "poor";

  return {
    checks,
    score,
    passed: checks.filter((c) => c.pass).length,
    total: checks.length,
    titleLen,
    metaLen,
    wordCount,
    band,
  };
}
