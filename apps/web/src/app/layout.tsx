import type { Metadata } from "next";
import { Inter, Fraunces, DM_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { Analytics } from "@vercel/analytics/next";
import { cn } from "@/lib/utils";
import { ClerkTokenSync } from "@/components/clerk-token-sync";
import { OG_IMAGE, OG_IMAGE_HEIGHT, OG_IMAGE_WIDTH, SITE_URL } from "@/lib/blog-fetch";
import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-serif", weight: ["400", "500", "600"] });
const dmMono = DM_Mono({ subsets: ["latin"], variable: "--font-mono", weight: ["400", "500"] });

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

// Social-card defaults for every App Router page. Without these, any route
// outside /blog (e.g. /pricing) shared on LinkedIn/Facebook/X previews as a
// bare title with no image, because the static landing page's OG tags live in
// public/beam/index.html and only cover "/".
//
// Next merges metadata SHALLOWLY: a child that exports its own `openGraph`
// REPLACES this object rather than extending it. Any page setting openGraph
// must therefore repeat `images` itself — see blog/page.tsx and blog/tag.
const OG_DESCRIPTION = "See who visits your site. Reach out on their turf.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "Beam",
  description: OG_DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: "Beam",
    title: "Beam — see who's into you. say hi back.",
    description: OG_DESCRIPTION,
    url: SITE_URL,
    images: [{ url: OG_IMAGE, width: OG_IMAGE_WIDTH, height: OG_IMAGE_HEIGHT }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Beam — see who's into you. say hi back.",
    description: OG_DESCRIPTION,
    images: [OG_IMAGE],
  },
};

// Warm DNS/TLS to the external Clerk + API origins during HTML parse, so the
// 320KB Clerk script and the first /auth/me + /sites fetches don't each pay a
// fresh handshake on cold dashboard loads. Hosts come from env (correct in dev
// and prod): Clerk's frontend-API host is base64-encoded in the publishable key.
const CLERK_HOST = (() => {
  const pk = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY || "";
  try {
    return Buffer.from(pk.split("_")[2] || "", "base64").toString("utf8").replace(/\$$/, "") || null;
  } catch {
    return null;
  }
})();
const API_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "").origin;
  } catch {
    return null;
  }
})();

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const inner = (
    <html lang="en">
      <head>
        {CLERK_HOST && <link rel="preconnect" href={`https://${CLERK_HOST}`} crossOrigin="anonymous" />}
        {API_ORIGIN && <link rel="preconnect" href={API_ORIGIN} crossOrigin="anonymous" />}
      </head>
      <body className={cn(inter.variable, fraunces.variable, dmMono.variable, "font-sans antialiased")}>
        {HAS_CLERK && <ClerkTokenSync />}
        <Providers>{children}</Providers>
        <Analytics />
      </body>
    </html>
  );

  if (HAS_CLERK) {
    return (
      <ClerkProvider signInUrl="/sign-in" signUpUrl="/sign-up">
        {inner}
      </ClerkProvider>
    );
  }

  return inner;
}
