import Link from "next/link";
import type { Metadata } from "next";
import { SITE_URL } from "@/lib/blog-fetch";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Blog — Beam",
    template: "%s — Beam Blog",
  },
  description:
    "Guides on website visitor identification, retargeting, and turning anonymous traffic into pipeline.",
};

export default function BlogLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-[rgba(43,37,48,0.08)]">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-5 py-4">
          <Link href="/blog" className="font-serif text-lg font-semibold tracking-tight">
            Beam <span className="text-muted-foreground">Blog</span>
          </Link>
          <a
            href="/"
            className="rounded-full bg-[hsl(345,100%,60%)] px-4 py-2 text-sm font-medium text-[#FAF6F0] transition-opacity hover:opacity-90"
          >
            Try Beam
          </a>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-10">{children}</main>
      <footer className="border-t border-[rgba(43,37,48,0.08)]">
        <div className="mx-auto max-w-3xl px-5 py-8 text-sm text-muted-foreground">
          © Beam — visitor identification &amp; retargeting for indie makers.
        </div>
      </footer>
    </div>
  );
}
