import type { Metadata } from "next";
import { OG_IMAGE, OG_IMAGE_HEIGHT, OG_IMAGE_WIDTH, SITE_URL } from "@/lib/blog-fetch";

// pricing/page.tsx is a client component, so it cannot export metadata itself.
// This pass-through layout exists only to carry it. Without it /pricing shares
// as the root layout's generic "Beam" card with no page-specific title.
//
// openGraph is repeated in full (not just the overriding fields) because Next
// merges metadata shallowly — this object REPLACES the root layout's.
const TITLE = "Pricing — Beam";
const DESCRIPTION =
  "Free to start, $19/mo Pro, $49/mo Max. See who visits your site and reach out on their turf.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: `${SITE_URL}/pricing` },
  openGraph: {
    type: "website",
    siteName: "Beam",
    title: TITLE,
    description: DESCRIPTION,
    url: `${SITE_URL}/pricing`,
    images: [{ url: OG_IMAGE, width: OG_IMAGE_WIDTH, height: OG_IMAGE_HEIGHT }],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: [OG_IMAGE],
  },
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
